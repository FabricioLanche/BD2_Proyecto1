from DBMS.parser.scanner import Scanner
from DBMS.parser.parser import SQLParser
from DBMS.storage.catalog import SystemCatalog
from DBMS.organization.data_structures import TableConfig, Record
from DBMS.logger import ConsoleLogger
import os

from DBMS.database_engine import DatabaseEngine
from DBMS.path_utils import resolve_dataset_path

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
            if tipo == "INT": formato += "i"
            elif tipo == "DOUBLE": formato += "d"
            elif tipo == "POINT": formato += "dd"
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
        for col in esquema:
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

        self.storage.open_table(table_name, table_config, pk_col_name, spatial_meta)

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
                    cleaned.append(val.decode('utf-8', errors='ignore').rstrip('\x00'))
                else:
                    cleaned.append(val)
                idx += 1
        return tuple(cleaned)

    def _route_statement(self, ast):
        action = ast["action"]
        if action == "CREATE":   self._execute_create(ast)
        elif action == "INSERT": self._execute_insert(ast)
        elif action == "SELECT": self._execute_select(ast)
        elif action == "DELETE": self._execute_delete(ast)
        elif action == "VISUALIZE": self._execute_visualize(ast)

    # --- Lógica Semántica ---
    def _execute_create(self, ast):
        table_name = ast["table"]
        columns    = ast["columns"]
        filepath   = ast["file"]
        resolved_filepath = None

        pk_col_name = "id"
        pk_count = 0
        for col in columns:
            if col.get("primary_key"):
                pk_count += 1
                pk_col_name = col["nombre"]

            tech = col.get("index_tech")
            tipo = col.get("tipo")

            if tech:
                if tech == "SEQUENTIAL":
                    if not col.get("primary_key"):
                        self.logger.error(f"Error Semántico: SEQUENTIAL solo está soportado para PRIMARY KEY. '{col['nombre']}' no es PK.")
                        raise Exception(f"Error Semántico: El índice SEQUENTIAL solo está soportado para la PRIMARY KEY. La columna '{col['nombre']}' no es PK.")
                    if tipo not in ["INT", "DOUBLE"]:
                        self.logger.error(f"Error Semántico: SEQUENTIAL solo soporta columnas numéricas. '{col['nombre']}' es {tipo}.")
                        raise Exception(f"Error Semántico: SEQUENTIAL solo soporta columnas numéricas. La columna '{col['nombre']}' es {tipo}.")
                elif tech == "RTREE" and tipo != "POINT":
                    self.logger.error(f"Error Semántico: RTREE solo soporta el tipo POINT. '{col['nombre']}' es {tipo}.")
                    raise Exception(f"Error Semántico: RTREE es un índice espacial y solo soporta el tipo POINT. La columna '{col['nombre']}' es {tipo}.")
                if tipo == "POINT" and tech != "RTREE":
                    self.logger.error(f"Error Semántico: El tipo POINT no puede indexarse con {tech}. Se requiere RTREE.")
                    raise Exception(f"Error Semántico: El tipo POINT no puede ser indexado usando {tech}. Debe usar RTREE.")

        if pk_count > 1:
            self.logger.error(f"Múltiples PRIMARY KEY detectadas en '{table_name}'. Solo se permite una.")
            raise Exception(f"Error Semántico: Múltiples PRIMARY KEY detectadas en '{table_name}'.")
        elif pk_count == 0:
            self.logger.error(f"No se definió PRIMARY KEY para '{table_name}'. Se requiere al menos una.")
            raise Exception(f"Error Semántico: No se ha definido una PRIMARY KEY para '{table_name}'.")

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

        formato_binario  = self._generar_formato_struct(columnas_fisicas)
        nombres_columnas = [col["nombre"] for col in columnas_fisicas]
        table_config     = TableConfig(formato_binario, nombres_columnas, pk_col_name)
        esquema          = self.catalog.get_table_schema(table_name)
        self._metadata_cache[table_name] = (esquema, table_config, pk_col_name)

        if filepath:
            resolved_filepath = resolve_dataset_path(filepath)
            self.logger.info(f"Delegando carga masiva desde CSV al Storage Engine para '{table_name}'... ({resolved_filepath})")
            result = self.storage.create_table_from_csv(table_name, table_config, resolved_filepath, pk_col_name, spatial_meta)
            self.logger.info(f"{result}")
        else:
            self.logger.info(f"Delegando creación física al Storage Engine para '{table_name}'...")
            self.storage.open_table(table_name, table_config, pk_col_name, spatial_meta)
            self.logger.info(f"Tabla '{table_name}' creada exitosamente.")

    def _execute_insert(self, ast):
        table_name = ast["table"]
        values     = ast["values"]

        esquema, table_config, pk_col_name = self._get_table_metadata(table_name)

        if len(values) != len(esquema):
            self.logger.error(f"INSERT fallido en '{table_name}': se esperaban {len(esquema)} valores, se recibieron {len(values)}.")
            raise Exception(f"INSERT fallido: Se esperaban {len(esquema)} valores.")

        # Type Checking
        for val, col in zip(values, esquema):
            expected_type = col["tipo"]
            col_name      = col["nombre"]

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
                max_len   = int(expected_type.split("(")[1].replace(")", ""))
                val_bytes = val.encode('utf-8')[:max_len].ljust(max_len, b'\x00')
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
        table_name  = ast["table"]
        col_name    = ast["col"]
        search_type = ast["type"]

        esquema, table_config, pk_col_name = self._get_table_metadata(table_name)

        col_meta = next((c for c in esquema if c["nombre"] == col_name), None)
        if not col_meta:
            self.logger.error(f"La columna '{col_name}' no pertenece a la tabla '{table_name}'.")
            raise Exception(f"Error: La columna '{col_name}' no pertenece a '{table_name}'.")

        es_llave_primaria = col_meta.get("primary_key")
        tipo_columna      = col_meta.get("tipo")
        tech              = col_meta.get("index_tech")

        # Columnas lógicas (nombres del esquema original) para el encabezado
        col_headers = [col["nombre"] for col in esquema]

        # Función auxiliar para convertir tupla a diccionario
        def tuple_to_dict(data_tuple, cols):
            return {col["nombre"]: val for col, val in zip(cols, data_tuple)}

        # PK con Sequential Index
        if es_llave_primaria and tech == "SEQUENTIAL":
            if search_type == "SEARCH":
                val = ast["val"]
                if tipo_columna == "INT":      val = int(val)
                elif tipo_columna == "DOUBLE": val = float(val)

                self.logger.info(f"Index Scan: buscando PK '{col_name} = {val}' con Sequential Index en '{table_name}'...")
                result = self.storage.search(table_name, val)
                self.logger.info(f"{result}")

                if result.records:
                    row_dict = tuple_to_dict(result.records.data_tuple, esquema)
                    self.logger.result(col_headers, [row_dict])
                else:
                    self.logger.info("0 registros encontrados.")

            elif search_type == "RANGE":
                v1, v2 = ast["range"]
                if tipo_columna == "INT":      v1, v2 = int(v1),   int(v2)
                elif tipo_columna == "DOUBLE": v1, v2 = float(v1), float(v2)

                self.logger.info(f"Index Scan: buscando PK '{col_name} BETWEEN {v1} AND {v2}' con Sequential Index en '{table_name}'...")
                result = self.storage.range_search(table_name, v1, v2)
                self.logger.info(f"{result}")

                if result.records:
                    rows = [tuple_to_dict(r.data_tuple, esquema) for r in result.records]
                    self.logger.result(col_headers, rows)
                else:
                    self.logger.info("0 registros encontrados.")

        # B-Tree
        elif tech == "BTREE":
            self.logger.info(f"Index Scan con B-Tree para la columna '{col_name}' en '{table_name}'.")

        # Extendible Hash
        elif tech == "HASH":
            if search_type == "RANGE":
                self.logger.warning(f"El índice Extendible Hash no soporta búsquedas por rango (RANGE). Se requiere Full Table Scan.")
            else:
                self.logger.info(f"Index Scan con Extendible Hash para la columna '{col_name}' en '{table_name}'.")

        # R-Tree espacial
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

            self.logger.info(f"{result}")
            if result.records:
                rows = [tuple_to_dict(r.data_tuple, esquema) for r in result.records]
                self.logger.result(col_headers, rows)
            else:
                self.logger.info("0 registros encontrados.")

        # Sin índice → Full Table Scan
        else:
            self.logger.warning(f"La columna '{col_name}' no tiene índice asignado. Se realizará Full Table Scan en '{table_name}'.")

            if tipo_columna == "POINT":
                self.logger.error(f"La columna '{col_name}' es tipo POINT sin índice RTREE. Full Table Scan espacial no soportado.")
                return

            if search_type == "SEARCH":
                op  = "="
                val = ast["val"]
                if tipo_columna == "INT":      val = int(val)
                elif tipo_columna == "DOUBLE": val = float(val)
                elif isinstance(val, str):     val = val.strip("'\"")

            elif search_type == "RANGE":
                op     = "BETWEEN"
                v1, v2 = ast["range"]
                if tipo_columna == "INT":      v1, v2 = int(v1),   int(v2)
                elif tipo_columna == "DOUBLE": v1, v2 = float(v1), float(v2)
                elif isinstance(v1, str) and isinstance(v2, str):
                    v1, v2 = v1.strip("'\""), v2.strip("'\"")
                val = (v1, v2)

            try:
                tabla      = self.storage._tables[table_name]
                resultados = tabla.heap.filter_records(col_name, op, val)
                self.logger.info(f"Full Table Scan completado. {len(resultados)} registro(s) encontrado(s).")
                if resultados:
                    rows = [tuple_to_dict(r.data_tuple, esquema) for r in resultados]
                    self.logger.result(col_headers, rows)
            except Exception as e:
                self.logger.error(f"Fallo en el Full Table Scan de '{table_name}': {e}")
                
    def _execute_delete(self, ast):
        table_name = ast["table"]
        esquema, table_config, pk_col_name = self._get_table_metadata(table_name)
        self.logger.info(f"DELETE en '{table_name}': buscando registro en índices y marcando 'is_deleted = 1' en Sequential File.")

    def _execute_visualize(self, ast):
        # AST: { action: 'VISUALIZE', object: 'RTREE', table: Optional[str] }
        obj = ast.get("object")
        if obj != "RTREE":
            self.logger.error("VISUALIZE: objeto no soportado")
            raise Exception("VISUALIZE solo soporta RTREE")

        table_name = ast.get("table")
        # Si no se especifica tabla, intentar inferir
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
            # Construir URL pública para que el frontend pueda pedir la imagen via HTTP
            filename = os.path.basename(path)
            url = f"/api/graph/{filename}"
            try:
                self.logger.image(url)
            except Exception:
                # Fallback: enviar como tabla con la ruta (compatibilidad)
                self.logger.result(["image"], [{"image": url}])
            self.logger.info(f"Visualización R-Tree generada: {path} -> {url}")
        except Exception as e:
            self.logger.error(f"Error al visualizar R-Tree para '{table_name}': {e}")