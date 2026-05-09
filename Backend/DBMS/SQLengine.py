import os

from DBMS.parser.scanner import Scanner
from DBMS.parser.parser import SQLParser
from DBMS.storage.catalog import SystemCatalog
from DBMS.organization.data_structures import TableConfig, Record
from Backend.DBMS.utils.logger import ConsoleLogger
from Backend.DBMS.utils.path_utils import resolve_dataset_path

from DBMS.database_engine import DatabaseEngine


class DBMSEngine:
    def __init__(self, logger=None):
        self.logger = logger or ConsoleLogger()
        self.logger.info("Iniciando DBMS SQL...")
        self.catalog = SystemCatalog()
        self.storage = DatabaseEngine(logger=self.logger)
        self._metadata_cache = {}
        self.logger.info("Catalog cargado exitosamente!")

    def set_logger(self, logger):
        self.logger = logger or ConsoleLogger()
        self.storage.logger = self.logger

    def execute_query(self, sql_string):
        try:
            scanner = Scanner(sql_string)
            tokens = scanner.tokenize()
            parser = SQLParser(tokens)
            ast_array = parser.parse()

            for ast in ast_array:
                self._route_statement(ast)

        except Exception as e:
            self.logger.error(f"Error: {e}")

    def _generar_formato_struct(self, columns):
        formato = ""
        for col in columns:
            tipo = col["tipo"]
            if tipo == "INT":
                formato += "i"
            elif tipo == "DOUBLE":
                formato += "d"
            elif tipo == "POINT":
                formato += "dd"
            elif tipo.startswith("VARCHAR"):
                size = tipo.split("(")[1].replace(")", "")
                formato += f"{size}s"
        return formato

    def _get_table_metadata(self, table_name):
        if table_name in self._metadata_cache:
            return self._metadata_cache[table_name]

        esquema = self.catalog.get_table_schema(table_name)
        if not esquema:
            self.logger.error(f"La tabla '{table_name}' no existe en el catálogo.")
            raise Exception(f"La tabla '{table_name}' no existe en el catálogo.")

        spatial_meta = None
        columnas_fisicas = []
        hash_meta = []
        btree_meta = []

        for col in esquema:
            if col.get("index_tech") == "HASH":
                hash_meta.append({"nombre": col["nombre"], "tipo": col["tipo"]})
            elif col.get("index_tech") == "BTREE":
                btree_meta.append({"nombre": col["nombre"], "tipo": col["tipo"]})

            if col["tipo"] == "POINT":
                if col.get("mapped_by"):
                    cx, cy = col["mapped_by"]
                else:
                    cx, cy = f"{col['nombre']}_x", f"{col['nombre']}_y"
                columnas_fisicas.append({"nombre": cx, "tipo": "DOUBLE"})
                columnas_fisicas.append({"nombre": cy, "tipo": "DOUBLE"})

                if col.get("index_tech") == "RTREE":
                    spatial_meta = {"col_x": cx, "col_y": cy}
            else:
                columnas_fisicas.append(col)

        formato_binario = self._generar_formato_struct(columnas_fisicas)
        nombres_columnas = [col["nombre"] for col in columnas_fisicas]
        pk_col_name = next((c["nombre"] for c in esquema if c.get("primary_key")), "id")
        table_config = TableConfig(formato_binario, nombres_columnas, pk_col_name)

        self.storage.open_table(table_name, table_config, pk_col_name, spatial_meta, hash_meta, btree_meta)

        meta = (esquema, table_config, pk_col_name)
        self._metadata_cache[table_name] = meta
        return meta

    def _clean_tuple(self, data_tuple, esquema):
        cleaned = []
        idx = 0
        for col in esquema:
            if col["tipo"] == "POINT":
                x = data_tuple[idx]
                y = data_tuple[idx + 1]
                cleaned.append(f"POINT({x}, {y})")
                idx += 2
            else:
                val = data_tuple[idx]
                if isinstance(val, bytes):
                    cleaned.append(val.decode("utf-8", errors="ignore").rstrip("\x00"))
                else:
                    cleaned.append(val)
                idx += 1
        return tuple(cleaned)

    def _tuple_to_dict(self, data_tuple, esquema):
        return {col["nombre"]: val for col, val in zip(esquema, data_tuple)}

    def _route_statement(self, ast):
        action = ast["action"]
        if action == "CREATE":
            self._execute_create(ast)
        elif action == "INSERT":
            self._execute_insert(ast)
        elif action == "SELECT":
            self._execute_select(ast)
        elif action == "DELETE":
            self._execute_delete(ast)
        elif action == "VISUALIZE":
            self._execute_visualize(ast)

    def _execute_create(self, ast):
        table_name = ast["table"]
        columns = ast["columns"]
        filepath = ast["file"]

        try:
            esquema_existente = self.catalog.get_table_schema(table_name)
        except Exception:
            esquema_existente = None

        if esquema_existente:
            raise Exception(f"Error Semántico: La tabla '{table_name}' ya existe.")

        pk_col_name = "id"
        pk_count = 0
        rtree_count = 0
        hash_meta = []
        btree_meta = []

        for col in columns:
            if col.get("primary_key"):
                pk_count += 1
                pk_col_name = col["nombre"]

            tech = col.get("index_tech")
            tipo = col.get("tipo")

            if col.get("primary_key") and tech and tech != "SEQUENTIAL":
                raise Exception(
                    f"Error Semántico: La PRIMARY KEY solo soporta el índice SEQUENTIAL. La técnica '{tech}' no está soportada para la llave primaria."
                )

            if tech:
                if tech == "SEQUENTIAL":
                    if not col.get("primary_key"):
                        self.logger.error(f"Error Semántico: SEQUENTIAL solo está soportado para PRIMARY KEY. '{col['nombre']}' no es PK.")
                        raise Exception(f"Error Semántico: El índice SEQUENTIAL solo está soportado para la PRIMARY KEY. La columna '{col['nombre']}' no es PK.")
                    if tipo not in ["INT", "DOUBLE"]:
                        self.logger.error(f"Error Semántico: SEQUENTIAL solo soporta columnas numéricas. '{col['nombre']}' es {tipo}.")
                        raise Exception(f"Error Semántico: SEQUENTIAL solo soporta columnas numéricas. La columna '{col['nombre']}' es {tipo}.")
                elif tech == "HASH":
                    if tipo == "POINT":
                        raise Exception("Error Semántico: La técnica HASH no es compatible con el tipo POINT. Use RTREE para columnas espaciales.")
                    hash_meta.append(col)
                elif tech == "BTREE":
                    if tipo == "POINT":
                        raise Exception("Error Semántico: La técnica BTREE no es compatible con el tipo POINT.")
                    btree_meta.append(col)
                elif tech == "RTREE":
                    rtree_count += 1
                    if tipo != "POINT":
                        self.logger.error(f"Error Semántico: RTREE solo soporta el tipo POINT. '{col['nombre']}' es {tipo}.")
                        raise Exception(f"Error Semántico: RTREE es un índice espacial y solo soporta el tipo POINT. La columna '{col['nombre']}' es {tipo}.")

                if tipo == "POINT" and tech != "RTREE":
                    self.logger.error(f"Error Semántico: El tipo POINT no puede indexarse con {tech}. Se requiere RTREE.")
                    raise Exception(f"Error Semántico: El tipo POINT no puede ser indexado usando {tech}. Debe usar RTREE.")

        if pk_count > 1:
            self.logger.error(f"Múltiples PRIMARY KEY detectadas en '{table_name}'. Solo se permite una.")
            raise Exception(f"Error Semántico: Múltiples PRIMARY KEY detectadas en '{table_name}'.")
        if pk_count == 0:
            raise Exception(f"Error Semántico: No se ha definido una PRIMARY KEY para '{table_name}'. Se requiere al menos una columna con PRIMARY KEY.")
        if rtree_count > 1:
            raise Exception(f"Error Semántico: Múltiples índices RTREE detectados en '{table_name}'. El motor solo soporta un índice espacial por tabla.")

        self.catalog.create_table(table_name, columns)

        spatial_meta = None
        columnas_fisicas = []
        for col in columns:
            if col["tipo"] == "POINT":
                if col.get("mapped_by"):
                    cx, cy = col["mapped_by"]
                else:
                    cx, cy = f"{col['nombre']}_x", f"{col['nombre']}_y"
                columnas_fisicas.append({"nombre": cx, "tipo": "DOUBLE"})
                columnas_fisicas.append({"nombre": cy, "tipo": "DOUBLE"})
                if col.get("index_tech") == "RTREE":
                    spatial_meta = {"col_x": cx, "col_y": cy}
            else:
                columnas_fisicas.append(col)

        formato_binario = self._generar_formato_struct(columnas_fisicas)
        nombres_columnas = [col["nombre"] for col in columnas_fisicas]
        table_config = TableConfig(formato_binario, nombres_columnas, pk_col_name)
        esquema = self.catalog.get_table_schema(table_name)
        self._metadata_cache[table_name] = (esquema, table_config, pk_col_name)

        if filepath:
            resolved_filepath = resolve_dataset_path(filepath)
            self.logger.info(f"Delegando carga masiva desde CSV al Storage Engine para '{table_name}'... ({resolved_filepath})")
            result = self.storage.create_table_from_csv(table_name, table_config, resolved_filepath, pk_col_name, spatial_meta, hash_meta, btree_meta)
            self.logger.info(f"{result}")
        else:
            self.logger.info(f"Delegando creación física al Storage Engine para '{table_name}'...")
            self.storage.open_table(table_name, table_config, pk_col_name, spatial_meta, hash_meta, btree_meta)
            self.logger.info(f"Tabla '{table_name}' creada exitosamente.")

    def _execute_insert(self, ast):
        table_name = ast["table"]
        values = ast["values"]

        esquema, table_config, pk_col_name = self._get_table_metadata(table_name)

        if len(values) != len(esquema):
            self.logger.error(f"INSERT fallido en '{table_name}': se esperaban {len(esquema)} valores, se recibieron {len(values)}.")
            raise Exception(f"INSERT fallido: Se esperaban {len(esquema)} valores.")

        for val, col in zip(values, esquema):
            expected_type = col["tipo"]
            col_name = col["nombre"]

            if expected_type == "INT" and not isinstance(val, int):
                self.logger.error(f"Type Error en '{col_name}': se esperaba INT, se recibió {type(val).__name__}.")
                raise Exception(f"Type Error: La columna '{col_name}' espera un INT.")
            elif expected_type == "DOUBLE" and not isinstance(val, (int, float)):
                self.logger.error(f"Type Error en '{col_name}': se esperaba DOUBLE, se recibió {type(val).__name__}.")
                raise Exception(f"Type Error: La columna '{col_name}' espera un DOUBLE.")
            elif expected_type.startswith("VARCHAR"):
                if not isinstance(val, str):
                    self.logger.error(f"Type Error en '{col_name}': se esperaba VARCHAR (str), se recibió {type(val).__name__}.")
                    raise Exception(f"Type Error: La columna '{col_name}' espera un VARCHAR (String).")
                max_len = int(expected_type.split("(")[1].replace(")", ""))
                if len(val) > max_len:
                    self.logger.error(f"Type Error en '{col_name}': '{val}' excede el límite VARCHAR({max_len}).")
                    raise Exception(f"Type Error: El valor '{val}' excede el límite de VARCHAR({max_len}).")
            elif expected_type == "POINT":
                if not isinstance(val, (tuple, list)) or len(val) != 2:
                    self.logger.error(f"Type Error en '{col_name}': se esperaba POINT (x, y).")
                    raise Exception(f"Type Error: La columna '{col_name}' espera un POINT con formato (x, y).")
                if not all(isinstance(coord, (int, float)) for coord in val):
                    self.logger.error(f"Type Error en '{col_name}': las coordenadas del POINT deben ser numéricas.")
                    raise Exception(f"Type Error: Las coordenadas del POINT '{col_name}' deben ser numéricas.")

        valores_aplanados = []
        for val, col in zip(values, esquema):
            expected_type = col["tipo"]
            if isinstance(val, tuple):
                valores_aplanados.extend(val)
            elif isinstance(val, str) and expected_type.startswith("VARCHAR"):
                max_len = int(expected_type.split("(")[1].replace(")", ""))
                val_bytes = val.encode("utf-8")[:max_len].ljust(max_len, b"\x00")
                valores_aplanados.append(val_bytes)
            else:
                valores_aplanados.append(val)

        self.logger.info(f"Preparando registro para '{table_name}'...")
        record = Record(tuple(valores_aplanados), table_config)
        self.logger.info(f"Delegando INSERT físico al Storage Engine para '{table_name}'...")

        try:
            result = self.storage.insert(table_name, record)
            self.logger.info(f"{result}")
            self.storage.flush_table(table_name)
        except Exception as e:
            self.logger.error(f"Error en el Storage Engine durante INSERT en '{table_name}': {e}")

    def _execute_select(self, ast):
        table_name = ast["table"]
        col_name = ast["col"]
        search_type = ast["type"]

        esquema, table_config, pk_col_name = self._get_table_metadata(table_name)

        col_meta = next((c for c in esquema if c["nombre"] == col_name), None)
        if not col_meta:
            self.logger.error(f"La columna '{col_name}' no pertenece a la tabla '{table_name}'.")
            raise Exception(f"Error: La columna '{col_name}' no pertenece a '{table_name}'.")

        es_llave_primaria = col_meta.get("primary_key")
        tipo_columna = col_meta.get("tipo")
        tech = col_meta.get("index_tech")

        if tipo_columna == "POINT" and search_type in ["SEARCH", "RANGE"]:
            raise Exception(f"Error Semántico: No se puede usar '=' o 'BETWEEN' en la columna espacial '{col_name}'. Usar 'IN (POINT(x, y)...)'.")
        if tipo_columna != "POINT" and search_type in ["RTREE_RADIUS", "RTREE_KNN"]:
            raise Exception(f"Error Semántico: La columna '{col_name}' es de tipo {tipo_columna}. Solo puedes usar 'IN (POINT...)' en columnas de tipo POINT.")

        col_headers = [col["nombre"] for col in esquema]

        if es_llave_primaria and tech == "SEQUENTIAL":
            if search_type == "SEARCH":
                val = ast["val"]
                if tipo_columna == "INT":
                    val = int(val)
                elif tipo_columna == "DOUBLE":
                    val = float(val)
                elif isinstance(val, str):
                    val = val.strip("'\"")

                self.logger.info(f"Index Scan: buscando PK '{col_name} = {val}' con Sequential Index en '{table_name}'...")
                result = self.storage.search(table_name, val)
                self.logger.info(f"{result}")

                if result.records:
                    row_dict = self._tuple_to_dict(result.records.data_tuple, esquema)
                    self.logger.result(col_headers, [row_dict])
                else:
                    self.logger.info("0 registros encontrados.")

            elif search_type == "RANGE":
                v1, v2 = ast["range"]
                if tipo_columna == "INT":
                    v1, v2 = int(v1), int(v2)
                elif tipo_columna == "DOUBLE":
                    v1, v2 = float(v1), float(v2)

                self.logger.info(f"Index Scan: buscando PK '{col_name} BETWEEN {v1} AND {v2}' con Sequential Index en '{table_name}'...")
                result = self.storage.range_search(table_name, v1, v2)
                self.logger.info(f"{result}")

                if result.records:
                    rows = [self._tuple_to_dict(r.data_tuple, esquema) for r in result.records]
                    self.logger.result(col_headers, rows)
                else:
                    self.logger.info("0 registros encontrados.")

        elif tech == "BTREE":
            if search_type == "SEARCH":
                val = ast["val"]
                if tipo_columna == "INT":
                    val = int(val)
                elif tipo_columna == "DOUBLE":
                    val = float(val)
                elif isinstance(val, str):
                    val = val.strip("'\"")

                self.logger.info(f"Index Scan con B+Tree para la columna '{col_name}' en '{table_name}'.")
                result = self.storage.search_btree(table_name, col_name, val)
                self.logger.info(f"{result}")

                if result.records:
                    rows = [self._tuple_to_dict(r.data_tuple, esquema) for r in result.records]
                    self.logger.result(col_headers, rows)
                else:
                    self.logger.info("0 registros encontrados.")

            elif search_type == "RANGE":
                v1, v2 = ast["range"]
                if tipo_columna == "INT":
                    v1, v2 = int(v1), int(v2)
                elif tipo_columna == "DOUBLE":
                    v1, v2 = float(v1), float(v2)
                elif isinstance(v1, str) and isinstance(v2, str):
                    v1, v2 = v1.strip("'\""), v2.strip("'\"")

                self.logger.info(f"Index Scan con B+Tree por rango en '{col_name}' para '{table_name}'.")
                result = self.storage.range_search_btree(table_name, col_name, v1, v2)
                self.logger.info(f"{result}")

                if result.records:
                    rows = [self._tuple_to_dict(r.data_tuple, esquema) for r in result.records]
                    self.logger.result(col_headers, rows)
                else:
                    self.logger.info("0 registros encontrados.")

        elif tech == "HASH":
            if search_type == "SEARCH":
                val = ast["val"]
                if tipo_columna == "INT":
                    val = int(val)
                elif tipo_columna == "DOUBLE":
                    val = float(val)
                elif isinstance(val, str):
                    val = val.strip("'\"")

                self.logger.info(f"Index Scan con Hash Extendible para la columna '{col_name}' en '{table_name}'.")
                result = self.storage.search_hash(table_name, col_name, val)
                self.logger.info(f"{result}")

                if result.records:
                    rows = [self._tuple_to_dict(r.data_tuple, esquema) for r in result.records]
                    self.logger.result(col_headers, rows)
                else:
                    self.logger.info("0 registros encontrados.")
            else:
                self.logger.warning(f"El índice HASH no soporta búsquedas por rango para '{col_name}'.")

        elif tech == "RTREE":
            self.logger.info(f"Spatial Index Scan con R-Tree para la columna '{col_name}' en '{table_name}'.")
            x, y = ast["point"]

            if search_type == "RTREE_RADIUS":
                radius = ast["radius"]
                self.logger.info(f"Spatial Scan: puntos a radio {radius} de POINT({x}, {y})...")
                result = self.storage.search_spatial_radius(table_name, x, y, radius)
            elif search_type == "RTREE_KNN":
                k = ast["k"]
                self.logger.info(f"Spatial Scan: {k} vecinos más cercanos a POINT({x}, {y})...")
                result = self.storage.search_spatial_knn(table_name, x, y, k)
            else:
                raise Exception(f"Error Semántico: Operación espacial no soportada: {search_type}")

            self.logger.info(f"{result}")
            if result.records:
                rows = [self._tuple_to_dict(r.data_tuple, esquema) for r in result.records]
                self.logger.result(col_headers, rows)
            else:
                self.logger.info("0 registros encontrados.")

        else:
            self.logger.warning(f"La columna '{col_name}' no tiene índice asignado. Se realizará Full Table Scan en '{table_name}'.")

            if tipo_columna == "POINT":
                self.logger.error(f"La columna '{col_name}' es tipo POINT sin índice RTREE. Full Table Scan espacial no soportado.")
                return

            if search_type == "SEARCH":
                op = "="
                val = ast["val"]
                if tipo_columna == "INT":
                    val = int(val)
                elif tipo_columna == "DOUBLE":
                    val = float(val)
                elif isinstance(val, str):
                    val = val.strip("'\"")
            elif search_type == "RANGE":
                op = "BETWEEN"
                v1, v2 = ast["range"]
                if tipo_columna == "INT":
                    v1, v2 = int(v1), int(v2)
                elif tipo_columna == "DOUBLE":
                    v1, v2 = float(v1), float(v2)
                elif isinstance(v1, str) and isinstance(v2, str):
                    v1, v2 = v1.strip("'\""), v2.strip("'\"")
                val = (v1, v2)
            else:
                raise Exception(f"Error Semántico: Búsqueda no soportada sin índice para '{search_type}'.")

            try:
                result = self.storage.filter_scan(table_name, col_name, op, val)
                self.logger.info(f"{result}")

                if result.records:
                    rows = [self._tuple_to_dict(r.data_tuple, esquema) for r in result.records]
                    self.logger.result(col_headers, rows)
                else:
                    self.logger.info("0 registros encontrados.")
            except Exception as e:
                self.logger.error(f"Fallo en el Full Table Scan de '{table_name}': {e}")

    def _execute_delete(self, ast):
        table_name = ast["table"]
        col_name = ast["col"]
        val = ast["val"]

        esquema, table_config, pk_col_name = self._get_table_metadata(table_name)
        col_meta = next((c for c in esquema if c["nombre"] == col_name), None)
        if not col_meta:
            raise Exception(f"Error: La columna '{col_name}' no existe en la tabla '{table_name}'.")

        tipo_columna = col_meta["tipo"]
        tech = col_meta.get("index_tech")

        if tipo_columna == "POINT":
            raise Exception("Error Semántico: El motor no soporta eliminar registros filtrando directamente por coordenadas (POINT). Usa la Llave Primaria u otra columna.")

        if tipo_columna == "INT":
            val = int(val)
        elif tipo_columna == "DOUBLE":
            val = float(val)
        elif isinstance(val, str):
            val = val.strip("'\"")

        self.logger.info(f"DELETE en '{table_name}': columna '{col_name}' = {val}.")

        if col_name == pk_col_name:
            result = self.storage.delete(table_name, val)
            self.logger.info(f"{result}")
            if result.records:
                self.logger.info(f"Registro con PK '{val}' eliminado exitosamente.")
            else:
                self.logger.info(f"No se encontró ningún registro con PK '{val}'.")
            return

        if tech == "HASH":
            search_result = self.storage.search_hash(table_name, col_name, val)
            self.logger.info(f"{search_result}")
            if search_result.records:
                eliminados = 0
                for r in search_result.records:
                    pk_val = r.get_pk()
                    pk_val = self._decode_pk(pk_val)
                    del_result = self.storage.delete(table_name, pk_val)
                    self.logger.info(f"{del_result}")
                    if del_result.records:
                        eliminados += 1
                self.logger.info(f"{eliminados} registro(s) localizado(s) por HASH y eliminado(s).")
            else:
                self.logger.info(f"No se encontraron registros donde {col_name} = {val}.")
            return

        if tech == "BTREE":
            search_result = self.storage.search_btree(table_name, col_name, val)
            self.logger.info(f"{search_result}")
            if search_result.records:
                eliminados = 0
                for r in search_result.records:
                    pk_val = self._decode_pk(r.get_pk())
                    del_result = self.storage.delete(table_name, pk_val)
                    self.logger.info(f"{del_result}")
                    if del_result.records:
                        eliminados += 1
                self.logger.info(f"{eliminados} registro(s) localizado(s) por BTREE y eliminado(s).")
            else:
                self.logger.info(f"No se encontraron registros donde {col_name} = {val}.")
            return

        self.logger.info(f"La columna '{col_name}' no tiene índice. Iniciando Full Table Scan...")
        try:
            resultados = self.storage.filter_scan(table_name, col_name, "=", val)
            self.logger.info(f"{resultados}")
            if not resultados.records:
                self.logger.info(f"No se encontraron registros donde {col_name} = {val}.")
                return

            eliminados = 0
            for r in resultados.records:
                pk_val = self._decode_pk(r.get_pk())
                res = self.storage.delete(table_name, pk_val)
                self.logger.info(f"{res}")
                if res.records:
                    eliminados += 1

            self.logger.info(f"{eliminados} registro(s) eliminado(s) tras Full Table Scan.")
        except Exception as e:
            self.logger.error(f"[ERROR] Fallo al eliminar: {e}")

    def _execute_visualize(self, ast):
        obj = ast.get("object")
        if obj != "RTREE":
            self.logger.error("VISUALIZE: objeto no soportado")
            raise Exception("VISUALIZE solo soporta RTREE")

        table_name = ast.get("table")
        if not table_name:
            rtrees = [name for name, entry in self.storage._tables.items() if entry.rtree]
            if len(rtrees) == 1:
                table_name = rtrees[0]
            elif len(rtrees) == 0:
                self.logger.error("No hay R-Trees cargados para visualizar.")
                raise Exception("No hay R-Trees cargados para visualizar.")
            else:
                self.logger.error("Múltiples R-Trees presentes: especifique la tabla. Ej: VISUALIZE RTREE <table>;")
                raise Exception("Múltiples R-Trees presentes: especifique la tabla. Ej: VISUALIZE RTREE <table>;")

        try:
            path = self.storage.visualize_rtree(table_name)
            filename = os.path.basename(path)
            url = f"/api/graph/{filename}"
            self.logger.image(url)
            self.logger.info(f"Visualización R-Tree generada: {path} -> {url}")
        except Exception as e:
            self.logger.error(f"Error al visualizar R-Tree para '{table_name}': {e}")

    def _decode_pk(self, value):
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="ignore").rstrip("\x00")
        return value
