from DBMS.parser.scanner import Scanner
from DBMS.parser.parser import SQLParser
from DBMS.storage.catalog import SystemCatalog
from DBMS.organization.data_structures import TableConfig, Record

from DBMS.database_engine import DatabaseEngine as StorageEngine

class DBMSEngine:
    def __init__(self):
        print("Iniciando DBMS SQL...")
        self.catalog = SystemCatalog()
        self.storage = StorageEngine()

        #Evitamos recalcular cargar el esquema, ConfigTable, etc.
        self._metadata_cache = {}

        print("Catalog cargado exitosamente!")

    def execute_query(self, sql_string):
        try:
            # Scanner y Parser
            scanner = Scanner(sql_string)
            tokens = scanner.tokenize()
            parser = SQLParser(tokens)
            ast_array = parser.parse()

            # Ejecutar SQL
            for ast in ast_array:
                self._route_statement(ast)
                
        except Exception as e:
            print(f"Error: {e}")

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
        # si ya estan cargados, devolver
        if table_name in self._metadata_cache:
            return self._metadata_cache[table_name]
        
        # sino cargamos del catalogo, preparamos la config y devolvemos
        esquema = self.catalog.get_table_schema(table_name)
        if not esquema:
             raise Exception(f"Error: La tabla '{table_name}' no existe en el catálogo.")
        
        spatial_meta = None
        columnas_fisicas = []
        hash_meta = []
        for col in esquema:
            if col.get("index_tech") == "HASH":
                hash_meta.append({"nombre": col["nombre"], "tipo": col["tipo"]})
            if col["tipo"] == "POINT":
                # Usa el Mapeo o el Default (_x, _y)
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
        
        self.storage.open_table(table_name, table_config, pk_col_name, spatial_meta, hash_meta)

        meta = (esquema, table_config, pk_col_name)
        self._metadata_cache[table_name] = meta
        return meta

    def _clean_tuple(self, data_tuple, esquema):
        cleaned = []
        idx = 0
        for col in esquema:
            if col["tipo"] == "POINT":
                x = data_tuple[idx]
                y = data_tuple[idx+1]
                cleaned.append(f"POINT({x}, {y})")
                idx += 2 # Avanzamos 2 espacios  porque son 2 columnas físicas (x e y)
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
        if action == "CREATE": self._execute_create(ast)
        elif action == "INSERT": self._execute_insert(ast)
        elif action == "SELECT": self._execute_select(ast)
        elif action == "DELETE": self._execute_delete(ast)
 
    # --- Lógica Semántica ---
    def _execute_create(self, ast):
        table_name = ast["table"]
        columns = ast["columns"]
        filepath = ast["file"]
        
        pk_col_name = "id"
        pk_count = 0
        rtree_count = 0
        hash_meta = []
        for col in columns:
            if col.get("primary_key"):
                pk_count += 1
                pk_col_name = col["nombre"]
                
            tech = col.get("index_tech")
            tipo = col.get("tipo")

            if col.get("primary_key") and tech and tech != "SEQUENTIAL":
                raise Exception(f"Error Semántico: La PRIMARY KEY solo soporta el índice SEQUENTIAL. La técnica '{tech}' no está soportada para la llave primaria.")
            
            if tech:
                if tech == "SEQUENTIAL":
                    if not col.get("primary_key"):
                        raise Exception(f"Error Semántico: El índice SEQUENTIAL solo está soportado para la PRIMARY KEY. La columna '{col['nombre']}' no es PK.")
                    if tipo not in ["INT", "DOUBLE"] and not tipo.startswith("VARCHAR"):
                        raise Exception(f"Error Semántico: SEQUENTIAL no soporta el tipo {tipo}. La columna '{col['nombre']}' debe ser INT, DOUBLE o VARCHAR.")
                elif tech == "HASH":
                    if tipo == "POINT":
                        raise Exception(f"Error Semántico: La técnica HASH no es compatible con el tipo POINT. Use RTREE para columnas espaciales.")
                    hash_meta.append(col)
                elif tech == "RTREE":
                    rtree_count += 1
                    if tipo != "POINT":
                        raise Exception(f"Error Semántico: RTREE es un índice espacial y solo soporta el tipo POINT. La columna '{col['nombre']}' es {tipo}.")
                if tipo == "POINT" and tech != "RTREE":
                    raise Exception(f"Error Semántico: El tipo POINT no puede ser indexado usando {tech}. Debe usar RTREE.")

        if pk_count > 1:
            raise Exception(f"Error Semántico: Múltiples PRIMARY KEY detectadas en '{table_name}'.")    
        elif pk_count == 0:
            raise Exception(f"Error Semántico: No se ha definido una PRIMARY KEY para '{table_name}'. Se requiere al menos una columna con PRIMARY KEY.")
        
        if rtree_count > 1:
            raise Exception(f"Error Semántico: Múltiples índices RTREE detectados en '{table_name}'. El motor solo soporta un índice espacial por tabla.")


        self.catalog.create_table(table_name, columns)

        # manejo de tipo point como dos columnas físicas (x e y)
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
            print(f"\n[EXECUTE] Delegando carga masiva al Storage Engine...")
            result = self.storage.create_table_from_csv(table_name, table_config, filepath, pk_col_name, spatial_meta, hash_meta)
            print(f"{result}")
        else:
             print(f"\n[EXECUTE] Delegando creación física al Storage Engine...")
             self.storage.open_table(table_name, table_config, pk_col_name, spatial_meta, hash_meta)
             print(f" [CREATE] tabla '{table_name}' creada.")



    def _execute_insert(self, ast):
        table_name = ast["table"]
        values = ast["values"]

        esquema, table_config, pk_col_name = self._get_table_metadata(table_name)

        if len(values) != len(esquema):
            raise Exception(f"INSERT fallido: Se esperaban {len(esquema)} valores.")

        # Type Checking
        for val, col in zip(values, esquema):
            expected_type = col["tipo"]
            col_name = col["nombre"]
            
            if expected_type == "INT" and not isinstance(val, int):
                raise Exception(f"Type Error: La columna '{col_name}' espera un INT.")
            
            elif expected_type == "DOUBLE" and not isinstance(val, (int, float)):
                raise Exception(f"Type Error: La columna '{col_name}' espera un DOUBLE.")
                
            elif expected_type.startswith("VARCHAR"):
                if not isinstance(val, str):
                    raise Exception(f"Type Error: La columna '{col_name}' espera un VARCHAR (String).")
                # Validar que el string no exceda el tamaño del VARCHAR
                max_len = int(expected_type.split("(")[1].replace(")", ""))
                if len(val) > max_len:
                    raise Exception(f"Type Error: El valor '{val}' excede el límite de VARCHAR({max_len}).")
            elif expected_type == "POINT":
                # (10.5, 20.0)
                if not isinstance(val, (tuple, list)) or len(val) != 2:
                    raise Exception(f"Type Error: La columna '{col_name}' espera un POINT con formato (x, y).")
                if not all(isinstance(coord, (int, float)) for coord in val):
                    raise Exception(f"Type Error: Las coordenadas del POINT '{col_name}' deben ser numéricas.")
        
        valores_aplanados = []
        for val, col in zip(values, esquema):
            expected_type = col["tipo"]
            
            if isinstance(val, tuple): 
                # Si es un POINT, sacamos X e Y por separado
                valores_aplanados.extend(val)
            elif isinstance(val, str) and expected_type.startswith("VARCHAR"):
                # Convertir String a Bytes y asegurar el tamaño exacto
                max_len = int(expected_type.split("(")[1].replace(")", ""))
                val_bytes = val.encode('utf-8')[:max_len].ljust(max_len, b'\x00')
                valores_aplanados.append(val_bytes)
            else:
                valores_aplanados.append(val)
        
        print(f"\n[EXECUTE] Preparando registro para '{table_name}'...")

        record = Record(tuple(valores_aplanados), table_config)

        print(f"[EXECUTE] Delegando INSERT físico al Storage Engine...")
        
        try:            
            result = self.storage.insert(table_name, record)
            print(f"{result}")
            
            self.storage.flush_table(table_name)
            
        except Exception as e:
            print(f"Error en el Storage Engine durante INSERT: {e}")


    def _execute_select(self, ast):
        table_name = ast["table"]
        col_name = ast["col"]
        search_type = ast["type"]

        esquema, table_config, pk_col_name = self._get_table_metadata(table_name)
        
        col_meta = next((c for c in esquema if c["nombre"] == col_name), None)
        if not col_meta:
            raise Exception(f"Error: La columna '{col_name}' no pertenece a '{table_name}'.")

        # Query Optimizer (Seleccion de si usar indice o no y cual indice usar)
        es_llave_primaria = col_meta.get("primary_key")
        tipo_columna = col_meta.get("tipo")
        tech = col_meta.get("index_tech") 

        if tipo_columna == "POINT" and search_type in ["SEARCH", "RANGE"]:
            raise Exception(f"Error Semántico: No se puede usar '=' o 'BETWEEN' en la columna espacial '{col_name}'. Usar 'IN (POINT(x, y)...)'.")
        if tipo_columna != "POINT" and search_type in ["RTREE_RADIUS", "RTREE_KNN"]:
            raise Exception(f"Error Semántico: La columna '{col_name}' es de tipo {tipo_columna}. Solo puedes usar 'IN (POINT...)' en columnas de tipo POINT.")

        if es_llave_primaria and tech == "SEQUENTIAL":
            if search_type == "SEARCH":
                val = ast["val"]
                if tipo_columna == "INT": 
                    val = int(val)
                elif tipo_columna == "DOUBLE": 
                    val = float(val)
                elif isinstance(val, str): 
                    val = val.strip("'\"")
                
                print(f"\n[EXECUTE] Index Scan: Buscando PK '{col_name} = {val}' usando Sequential Index...")
                result = self.storage.search(table_name, val)
                
                print(f"{result}")
                if result.records:
                     print(f"   -> Registro Encontrado: {self._clean_tuple(result.records.data_tuple, esquema)}")
                else:
                     print("   -> 0 registros encontrados.")

            elif search_type == "RANGE":
                v1, v2 = ast["range"]
                if tipo_columna == "INT":
                    v1, v2 = int(v1), int(v2)
                elif tipo_columna == "DOUBLE":
                    v1, v2 = float(v1), float(v2)
                    
                print(f"\n[EXECUTE] Index Scan: Buscando PK '{col_name} BETWEEN {v1} AND {v2}' usando Sequential Index...")
                result = self.storage.range_search(table_name, v1, v2)
                
                print(f"{result}")
                if result.records:
                    for r in result.records:
                        print(f"   -> Registro: {self._clean_tuple(r.data_tuple, esquema)}")
                else:
                    print("   -> 0 registros encontrados.")
                    
        # OTROS ÍNDICES 
        elif tech == "BTREE":
            print(f"\n[HOOK] Ejecutando Index Scan usando B-Tree para la columna '{col_name}'.")
            
        
        elif tech == "HASH":
            if search_type == "SEARCH":
                val = ast["val"]
                if tipo_columna == "INT": 
                    val = int(val)
                elif tipo_columna == "DOUBLE": 
                    val = float(val)
                elif isinstance(val, str): 
                    val = val.strip("'\"")

                print(f"\n[EXECUTE] Index Scan: Usando Hashing Extendible en '{col_name}'...")
                result = self.storage.search_hash(table_name, col_name, val)
                if result.records:
                     print(f"   -> Registro Encontrado: {self._clean_tuple(result.records.data_tuple, esquema)}")
                else:
                     print("   -> 0 registros encontrados.")
            else:
                print(f"\n[ERROR] El tipo de búsqueda '{search_type}' no está soportado por el índice HASH. Solo se permiten búsquedas exactas (=).")
                
        elif tech == "RTREE":
            print(f"\n[HOOK] Ejecutando Spatial Index Scan usando R-Tree para la columna '{col_name}'.")
            x, y = ast["point"]
            
            if search_type == "RTREE_RADIUS":
                radius = ast["radius"]
                print(f"\n[EXECUTE] Spatial Scan: Buscando puntos a radio {radius} de POINT({x}, {y})...")
                result = self.storage.search_spatial_radius(table_name, x, y, radius)
                
            elif search_type == "RTREE_KNN":
                k = ast["k"]
                print(f"\n[EXECUTE] Spatial Scan: Buscando {k} vecinos cercanos a POINT({x}, {y})...")
                result = self.storage.search_spatial_knn(table_name, x, y, k)
                
            print(f"{result}")
            if result.records:
                for r in result.records:
                    print(f"   -> Registro: {self._clean_tuple(r.data_tuple, esquema)}")
            else:
                print("   -> 0 registros encontrados.")
            
        # Sin índice soportado (Full Table Scan)
        else:
            print(f"\n[ADVERTENCIA] La columna '{col_name}' no tiene un índice asignado")

            if tipo_columna == "POINT":
                print(f"\n[ERROR] La columna '{col_name}' es de tipo POINT y no tiene un índice RTREE.")
                print("   -> El Full Table Scan espacial no está soportado :c.")
                return

            if search_type == "SEARCH":
                op = "="
                val = ast["val"]
                if tipo_columna == "INT": val = int(val)
                elif tipo_columna == "DOUBLE": val = float(val)
                elif isinstance(val, str): val = val.strip("'\"")
                
            elif search_type == "RANGE":
                op = "BETWEEN"
                v1, v2 = ast["range"]
                if tipo_columna == "INT": v1, v2 = int(v1), int(v2)
                elif tipo_columna == "DOUBLE": v1, v2 = float(v1), float(v2)
                elif isinstance(v1, str) and isinstance(v2, str):
                    v1, v2 = v1.strip("'\""), v2.strip("'\"")
                val = (v1, v2)
            
            try:
                tabla = self.storage._tables[table_name]
                resultados = tabla.heap.filter_records(col_name, op, val)
                
                print(f"Full Table Scan completado.")
                print(f"   -> Registros que cumplen la condición ({len(resultados)}):")
                for r in resultados:
                    print(f"      * {self._clean_tuple(r.data_tuple, esquema)}")
            except Exception as e:
                print(f"[ERROR] Fallo en el escaneo: {e}")


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

        if tipo_columna == "INT": val = int(val)
        elif tipo_columna == "DOUBLE": val = float(val)
        elif isinstance(val, str): val = val.strip("'\"")

        print(f"\n[EXECUTE] Procesando DELETE en '{table_name}' WHERE {col_name} = {val}...")

        if col_name == pk_col_name:
            result = self.storage.delete(table_name, val)
            if result.records:
                print(f"   Registro con PK '{val}' eliminado exitosamente.")
            else:
                print(f"   -> No se encontró ningún registro con PK '{val}'.")
            return

        if tech == "HASH":
            print(f"   Usando índice HASH en '{col_name}' para localizar el registro...")
            search_result = self.storage.search_hash(table_name, col_name, val)
            
            if search_result.records:
                pk_val = search_result.records.get_pk()

                if isinstance(pk_val, bytes):
                    pk_val = pk_val.decode('utf-8', errors='ignore').rstrip('\x00')

                del_result = self.storage.delete(table_name, pk_val)
                if del_result.records:
                    print(f"   Registro localizado por HASH y eliminado en cascada exitosamente.")
            else:
                print(f"   -> No se encontraron registros donde {col_name} = {val}.")
            return
        
        print(f"   La columna '{col_name}' no tiene índice. Iniciando Full Table Scan...")

        
        try:
            tabla = self.storage._tables[table_name]
            resultados = tabla.heap.filter_records(col_name, "=", val)
            
            if not resultados:
                print(f"   -> No se encontraron registros donde {col_name} = {val}.")
                return
                
            eliminados = 0
            for r in resultados:
                pk_val = r.get_pk()
                
                if isinstance(pk_val, bytes):
                    pk_val = pk_val.decode('utf-8', errors='ignore').rstrip('\x00')

                res = self.storage.delete(table_name, pk_val)
                if res.records:
                    eliminados += 1
                    
            print(f"   {eliminados} registro(s) eliminado(s) tras Full Table Scan.")
            
        except Exception as e:
            print(f"[ERROR] Fallo al eliminar: {e}")