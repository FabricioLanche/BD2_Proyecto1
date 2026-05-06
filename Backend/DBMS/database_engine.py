import time
from typing import Dict
from DBMS.organization.data_structures import TableConfig, Record
from DBMS.organization.heap_file import HeapFile
from DBMS.organization.sequential_file import SequentialIndex
from DBMS.organization.page_manager import PageManager, IOCounter


from DBMS.indexes.rtree import Rtree
from DBMS.indexes.extendible_hashing import ExtendibleHashing


class QueryResult:
    def __init__(self, records, io_stats: dict, elapsed_ms: float, operation: str):
        self.records    = records        # List[Record] | Record | bool | tuple
        self.io_stats   = io_stats       # {"reads": N, "writes": M, "total": T}
        self.elapsed_ms = elapsed_ms
        self.operation  = operation

    def __repr__(self):
        count = len(self.records) if isinstance(self.records, list) else 1
        return (
            f"[{self.operation}] "
            f"rows={count} | "
            f"I/O reads={self.io_stats['reads']} "
            f"writes={self.io_stats['writes']} "
            f"total={self.io_stats['total']} | "
            f"{self.elapsed_ms:.2f} ms"
        )

 # Agrupa todos los objetos asociados a una tabla
class _TableEntry:
    def __init__(
        self,
        heap: HeapFile,
        index: SequentialIndex,
        heap_pm: PageManager,
        index_pm: PageManager,
        io_counter: IOCounter,
        config: TableConfig,
        pk_col: str,
        spatial_meta: dict,
        hash_meta:list,
    ):
        self.heap       = heap
        self.index      = index
        self.heap_pm    = heap_pm
        self.index_pm   = index_pm
        self.io_counter = io_counter
        self.config     = config
        self.pk_col     = pk_col
        self.spatial_meta = spatial_meta
        self.rtree = None
        self.spatial_meta = spatial_meta
        self.rtree = None
        self.hash_meta = hash_meta or []
        self.hash_indices = {}



class DatabaseEngine:

    def __init__(self):
        self._tables: Dict[str, _TableEntry] = {}

    def create_table_from_csv(
        self,
        table_name: str,
        config: TableConfig,
        csv_path: str,
        pk_col: str,
        spatial_meta: dict,
        hash_meta: list,
    ) -> QueryResult:
        # Crea la tabla, carga el CSV en el HeapFile y construye el índice
        # Para las cargas masivas se deshabilita reconstrucciones y se hace batch indexing
        
        if table_name in self._tables:
            raise ValueError(f"Tabla '{table_name}' ya existe.")

        io_counter = IOCounter()

        heap_filename  = f"{table_name}.heap"
        index_filename = f"{table_name}_{pk_col}.idx"

        heap_pm  = PageManager(heap_filename,  io_counter)
        index_pm = PageManager(index_filename, io_counter)

        heap  = HeapFile(heap_filename,  config, heap_pm)
        index = SequentialIndex(index_filename, index_pm, config.get_pk_format())

        # Resetea contadores DESPUÉS de la inicialización (metadata no cuenta)
        heap_pm.reset_counters()
        index_pm.reset_counters()
        io_counter.reset()

        t0 = time.perf_counter()

        # Deshabilitar reconstrucciones durante carga masiva y activar bulk_load_mode
        original_k_limit = index.k_limit
        index.k_limit = 1_000_000
        
        index.bulk_load_mode = True

        # 1. Cargar CSV y retornar (RID, data_tuple)
        print(f"  Cargando CSV: {csv_path}...")
        results = heap.load_from_csv_optimized(csv_path)
        print(f"  ✓ {len(results)} registros en heap")

        entry = _TableEntry(heap, index, heap_pm, index_pm, io_counter, config, pk_col, spatial_meta, hash_meta)
        
        for meta in hash_meta:
            col_name = meta["nombre"]
            hash_pm = PageManager(f"{table_name}_{col_name}.hash", io_counter)

            # el Extendible Hashing esperaba el pk mediante el Tableconfig así que voy 
            # a engañarle para que use el de la columna que esta indexando
            original_pk_index = config.pk_index
            config.pk_index = config.column_map[col_name]

            entry.hash_indices[col_name] = ExtendibleHashing(hash_pm, config)

            config.pk_index = original_pk_index
            #TODO: quitar el engaño de pk y en su lugar modificar el Extendible Hashing


        idx_x, idx_y = -1, -1
        if spatial_meta:
            rtree_filename = f"{table_name}_spatial.bin"
            entry.rtree = Rtree(rtree_filename) # TODO: Conectar con IOcounter para que cuente lectura y escritura en el Rtree
            
            # Buscamos en qué posición (índice) de la tupla vienen la X y la Y
            idx_x = config.column_map[spatial_meta["col_x"]]
            idx_y = config.column_map[spatial_meta["col_y"]]


        # 2. Indexar utilizando el return anterior -> se evita llamar heap.search()
        print(f"  Indexando {len(results)} registros...")
        for i, (rid, data_tuple) in enumerate(results):
            pk = data_tuple[0]
            index.add(pk, rid)

            for col_name, h_index in entry.hash_indices.items():
                col_idx = config.column_map[col_name]
                val = data_tuple[col_idx]
                h_index.add(val, rid)

            if entry.rtree:
                point = (data_tuple[idx_x], data_tuple[idx_y])
                entry.rtree.insert(point, rid)


            if (i + 1) % 10_000 == 0:
                elapsed_partial = (time.perf_counter() - t0) * 1000
                print(f"    {i + 1}/{len(results)} indexados ({elapsed_partial:.1f}ms)")
        
        # Escribir todas las páginas indexadas a disco
        print(f"  Flushing índice a disco ({len(index._dirty_pages)} páginas)...")
        index.flush_metadata()
        
        # Deshabilitar bulk_load_mode
        index.bulk_load_mode = False
        
        # Restaurar k_limit original
        index.k_limit = original_k_limit
        
        # Si quedó con auxiliares, hacer un reconstruct limpio
        if index.k_aux > 0:
            print(f"  Limpiando auxiliares ({index.k_aux} entradas)...")
            index.reconstruct()

        elapsed = (time.perf_counter() - t0) * 1000

        self._tables[table_name] = entry

        result = QueryResult([], io_counter.snapshot(), elapsed, "CREATE+LOAD")
        result.records = len(results)  # devuelve cantidad de filas cargadas
        print(f"  Tabla '{table_name}' lista. {result}")

        # Flush metadata tras carga masiva
        heap.flush_metadata()
        index.flush_metadata()

        for h_index in entry.hash_indices.values():
            h_index.flush_metadata()

        return result

    def open_table(
        self,
        table_name: str,
        config: TableConfig,
        pk_col: str,
        spatial_meta: dict = None,
        hash_meta: list = None,
    ) -> None:
        # Abre una tabla que ya existe en disco (sin cargar CSV).

        if table_name in self._tables:
            return  # ya está abierta

        io_counter = IOCounter()

        heap_filename  = f"{table_name}.heap"
        index_filename = f"{table_name}_{pk_col}.idx"

        heap_pm  = PageManager(heap_filename,  io_counter)
        index_pm = PageManager(index_filename, io_counter)

        heap  = HeapFile(heap_filename,  config, heap_pm)
        index = SequentialIndex(index_filename, index_pm, config.get_pk_format())



        self._tables[table_name] = _TableEntry(
            heap, index, heap_pm, index_pm, io_counter, config, pk_col, spatial_meta, hash_meta)

        self._tables[table_name].hash_indices = {}


        if hash_meta:
            for meta in hash_meta:
                col_name = meta["nombre"]
                hash_filename = f"{table_name}_{col_name}.hash"
                h_pm = PageManager(hash_filename, io_counter)
                self._tables[table_name].hash_indices[col_name] = ExtendibleHashing(h_pm, config)

        if spatial_meta:
            rtree_filename = f"{table_name}_spatial.bin"
            self._tables[table_name].rtree = Rtree(rtree_filename)

    # Operaciones principales

    def insert(self, table_name: str, record: Record) -> QueryResult:
        t  = self._get_table(table_name)
        t0 = time.perf_counter()
        self._reset_io(t)

        rid = t.heap.insert(record)
        t.index.add(record.get_pk(), rid)

        for col_name, h_index in t.hash_indices.items():
            val = record.get_attribute(col_name)
            h_index.add(val, rid)

        if t.rtree:
            idx_x = t.config.column_map[t.spatial_meta["col_x"]]
            idx_y = t.config.column_map[t.spatial_meta["col_y"]]
            point = (record.data_tuple[idx_x], record.data_tuple[idx_y])
            t.rtree.insert(point, rid)

        elapsed = (time.perf_counter() - t0) * 1000
        return QueryResult(rid, t.io_counter.snapshot(), elapsed, "INSERT")

    def search(self, table_name: str, pk) -> QueryResult:
        t  = self._get_table(table_name)
        t0 = time.perf_counter()
        self._reset_io(t)

        rid    = t.index.search_rid(pk)
        record = t.heap.search(rid) if rid else None

        elapsed = (time.perf_counter() - t0) * 1000
        return QueryResult(record, t.io_counter.snapshot(), elapsed, "SELECT")

    def range_search(self, table_name: str, pk_start, pk_end) -> QueryResult:
        t  = self._get_table(table_name)
        t0 = time.perf_counter()
        self._reset_io(t)

        rids    = t.index.range_search_rids(pk_start, pk_end)
        records = t.heap.get_batch(rids) if rids else []

        elapsed = (time.perf_counter() - t0) * 1000
        return QueryResult(records, t.io_counter.snapshot(), elapsed, "SELECT RANGE")

    def delete(self, table_name: str, pk) -> QueryResult:
        t  = self._get_table(table_name)
        t0 = time.perf_counter()
        self._reset_io(t)

        rid     = t.index.remove(pk)
        deleted = False
        if rid:
            deleted = t.heap.delete(rid)

        elapsed = (time.perf_counter() - t0) * 1000
        return QueryResult(deleted, t.io_counter.snapshot(), elapsed, "DELETE")

    def scan(self, table_name: str) -> QueryResult:
        """Full table scan — costoso, solo para pruebas o reconstrucción."""
        t  = self._get_table(table_name)
        t0 = time.perf_counter()
        self._reset_io(t)

        records = [record for _, record in t.heap.scan()]

        elapsed = (time.perf_counter() - t0) * 1000
        return QueryResult(records, t.io_counter.snapshot(), elapsed, "FULL SCAN")

    # Métricas y estado
    def get_table_stats(self, table_name: str) -> dict:
        t = self._get_table(table_name)
        return {
            "table":          table_name,
            "total_records":  t.heap.total_records,
            "heap_pages":     t.heap.last_page_id + 1,
            "index_n_main":   t.index.n_main,
            "index_k_aux":    t.index.k_aux,
            "index_k_limit":  t.index.k_limit,
            "index_pages":    t.index.last_main_page + 1,
            "heap_io":        t.heap_pm.get_stats(),
            "index_io":       t.index_pm.get_stats(),
        }

    # Helpers internos

    def _get_table(self, table_name: str) -> _TableEntry:
        if table_name not in self._tables:
            raise KeyError(f"Tabla '{table_name}' no existe. Usa create_table_from_csv u open_table.")
        return self._tables[table_name]

    def _reset_io(self, t: _TableEntry) -> None:
        t.io_counter.reset()

    def flush_table(self, table_name: str) -> None:
        t = self._get_table(table_name)
        t.heap.flush_metadata()
        t.index.flush_metadata()

        for h_index in t.hash_indices.values():
            h_index.flush_metadata()

    def flush_all(self) -> None:
        for table_name in self._tables:
            self.flush_table(table_name)


    def search_spatial_radius(self, table_name: str, x: float, y: float, radius: float) -> QueryResult:
        t = self._get_table(table_name)
        t0 = time.perf_counter()
        self._reset_io(t)

        # Retorna: [ ((x,y), (page, slot)), ... ]
        rtree_results = t.rtree.rangeSearch((x, y), radius)
        
        # Extraemos el RID (el índice 1 de la tupla devuelta)
        rids = [res[1] for res in rtree_results]
        
        # traemos datos crudos desde el disco
        records = t.heap.get_batch(rids) if rids else []

        elapsed = (time.perf_counter() - t0) * 1000
        return QueryResult(records, t.io_counter.snapshot(), elapsed, "RTREE RADIUS")

    def search_spatial_knn(self, table_name: str, x: float, y: float, k: int) -> QueryResult:
        t = self._get_table(table_name)
        t0 = time.perf_counter()
        self._reset_io(t)

        rtree_results = t.rtree.knnSearch((x, y), k)
        
        rids = [res[1] for res in rtree_results]
        records = t.heap.get_batch(rids) if rids else []

        elapsed = (time.perf_counter() - t0) * 1000
        return QueryResult(records, t.io_counter.snapshot(), elapsed, "RTREE KNN")
    
    def search_hash(self, table_name: str, col_name: str, val) -> QueryResult:
        t = self._get_table(table_name)
        t0 = time.perf_counter()
        self._reset_io(t)

        h_index = t.hash_indices[col_name]
        rid = h_index.search_rid(val)
        record = t.heap.search(rid) if rid else None

        elapsed = (time.perf_counter() - t0) * 1000
        return QueryResult(record, t.io_counter.snapshot(), elapsed, "HASH SEARCH")    
