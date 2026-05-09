import time
from typing import Dict
from DBMS.organization.data_structures import TableConfig, Record
from DBMS.organization.heap_file import HeapFile
from DBMS.organization.sequential_file import SequentialIndex
from DBMS.organization.page_manager import PageManager, IOCounter
from Backend.DBMS.utils.logger import ConsoleLogger
from Backend.DBMS.utils.path_utils import resolve_dataset_path, resolve_data_path

from DBMS.indexes.rtree import Rtree

class QueryResult:
    def __init__(self, records, io_stats: dict, elapsed_ms: float, operation: str):
        self.records    = records
        self.io_stats   = io_stats
        self.elapsed_ms = elapsed_ms
        self.operation  = operation

    def __repr__(self):
        count = len(self.records) if isinstance(self.records, list) else 1
        return (
            f"operation={self.operation} | "
            f"rows={count} | "
            f"reads={self.io_stats['reads']} "
            f"writes={self.io_stats['writes']} "
            f"total={self.io_stats['total']} | "
            f"{self.elapsed_ms:.6f} ms"
        )

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
    ):
        self.heap         = heap
        self.index        = index
        self.heap_pm      = heap_pm
        self.index_pm     = index_pm
        self.io_counter   = io_counter
        self.config       = config
        self.pk_col       = pk_col
        self.spatial_meta = spatial_meta
        self.rtree        = None

class DatabaseEngine:
    def __init__(self, logger=None):
        self._tables: Dict[str, _TableEntry] = {}
        self.logger = logger or ConsoleLogger()

    def create_table_from_csv(
        self,
        table_name: str,
        config: TableConfig,
        csv_path: str,
        pk_col: str,
        spatial_meta: dict,
    ) -> QueryResult:

        if table_name in self._tables:
            self.logger.error(f"Intento de crear tabla duplicada: '{table_name}' ya existe.")
            raise ValueError(f"Tabla '{table_name}' ya existe.")

        resolved_csv_path = resolve_dataset_path(csv_path)

        io_counter = IOCounter()

        heap_filename  = resolve_data_path(f"{table_name}.heap", create_parent=True)
        index_filename = resolve_data_path(f"{table_name}_{pk_col}.idx", create_parent=True)

        heap_pm  = PageManager(heap_filename,  io_counter)
        index_pm = PageManager(index_filename, io_counter)

        heap  = HeapFile(heap_filename,  config, heap_pm)
        index = SequentialIndex(index_filename, index_pm, config.get_pk_format())

        heap_pm.reset_counters()
        index_pm.reset_counters()
        io_counter.reset()

        t0 = time.perf_counter()

        original_k_limit  = index.k_limit
        index.k_limit     = 1_000_000
        index.bulk_load_mode = True

        self.logger.info(f"Cargando CSV '{resolved_csv_path}' en la tabla '{table_name}'...")
        results = heap.load_from_csv_optimized(resolved_csv_path)
        self.logger.info(f"{len(results)} registros cargados en heap.")

        entry = _TableEntry(heap, index, heap_pm, index_pm, io_counter, config, pk_col, spatial_meta)

        idx_x, idx_y = -1, -1
        if spatial_meta:
            rtree_filename = f"{table_name}_spatial.bin"
            entry.rtree = Rtree(rtree_filename)
            idx_x = config.column_map[spatial_meta["col_x"]]
            idx_y = config.column_map[spatial_meta["col_y"]]
            self.logger.info(f"R-Tree espacial inicializado para '{table_name}'.")

        self.logger.info(f"Indexando {len(results)} registros para '{table_name}'...")
        for i, (rid, data_tuple) in enumerate(results):
            pk = data_tuple[0]
            index.add(pk, rid)

            if entry.rtree:
                point = (data_tuple[idx_x], data_tuple[idx_y])
                entry.rtree.insert(point, rid)

            if (i + 1) % 10_000 == 0:
                elapsed_partial = (time.perf_counter() - t0) * 1000
                self.logger.debug(f"{i + 1}/{len(results)} registros indexados ({elapsed_partial:.1f} ms).")

        self.logger.info(f"Flushing índice a disco ({len(index._dirty_pages)} páginas sucias)...")
        index.flush_metadata()

        index.bulk_load_mode = False
        index.k_limit        = original_k_limit

        if index.k_aux > 0:
            self.logger.info(f"Reconstruyendo índice: limpiando {index.k_aux} entradas auxiliares...")
            index.reconstruct()

        elapsed = (time.perf_counter() - t0) * 1000

        self._tables[table_name] = entry

        result         = QueryResult([], io_counter.snapshot(), elapsed, "CREATE+LOAD")
        result.records = len(results)
        self.logger.info(f"Tabla '{table_name}' lista. {result}")

        heap.flush_metadata()
        index.flush_metadata()

        return result

    def open_table(
        self,
        table_name: str,
        config: TableConfig,
        pk_col: str,
        spatial_meta: dict = None,
    ) -> None:

        if table_name in self._tables:
            self.logger.debug(f"Tabla '{table_name}' ya estaba abierta. Se omite re-apertura.")
            return

        io_counter = IOCounter()

        heap_filename  = resolve_data_path(f"{table_name}.heap", create_parent=True)
        index_filename = resolve_data_path(f"{table_name}_{pk_col}.idx", create_parent=True)

        heap_pm  = PageManager(heap_filename,  io_counter)
        index_pm = PageManager(index_filename, io_counter)

        heap  = HeapFile(heap_filename,  config, heap_pm)
        index = SequentialIndex(index_filename, index_pm, config.get_pk_format())

        self._tables[table_name] = _TableEntry(
            heap, index, heap_pm, index_pm, io_counter, config, pk_col, spatial_meta
        )
        self.logger.info(f"Tabla '{table_name}' abierta desde disco.")

        if spatial_meta:
            rtree_filename = f"{table_name}_spatial.bin"
            self._tables[table_name].rtree = Rtree(rtree_filename)
            self.logger.info(f"R-Tree espacial cargado para '{table_name}'.")

    # Operaciones principales

    def insert(self, table_name: str, record: Record) -> QueryResult:
        t  = self._get_table(table_name)
        t0 = time.perf_counter()
        self._reset_io(t)

        rid = t.heap.insert(record)
        t.index.add(record.get_pk(), rid)

        if t.rtree:
            idx_x = t.config.column_map[t.spatial_meta["col_x"]]
            idx_y = t.config.column_map[t.spatial_meta["col_y"]]
            point = (record.data_tuple[idx_x], record.data_tuple[idx_y])
            t.rtree.insert(point, rid)

        elapsed = (time.perf_counter() - t0) * 1000
        self.logger.debug(f"INSERT en '{table_name}': RID={rid} | {elapsed:.2f} ms.")
        return QueryResult(rid, t.io_counter.snapshot(), elapsed, "INSERT")

    def search(self, table_name: str, pk) -> QueryResult:
        t  = self._get_table(table_name)
        t0 = time.perf_counter()
        self._reset_io(t)

        rid    = t.index.search_rid(pk)
        record = t.heap.search(rid) if rid else None

        elapsed = (time.perf_counter() - t0) * 1000
        found = record is not None
        self.logger.debug(f"SELECT en '{table_name}': PK={pk} | encontrado={found} | {elapsed:.2f} ms.")
        return QueryResult(record, t.io_counter.snapshot(), elapsed, "SELECT")

    def range_search(self, table_name: str, pk_start, pk_end) -> QueryResult:
        t  = self._get_table(table_name)
        t0 = time.perf_counter()
        self._reset_io(t)

        rids    = t.index.range_search_rids(pk_start, pk_end)
        records = t.heap.get_batch(rids) if rids else []

        elapsed = (time.perf_counter() - t0) * 1000
        self.logger.debug(f"SELECT RANGE en '{table_name}': [{pk_start}, {pk_end}] | {len(records)} registro(s) | {elapsed:.2f} ms.")
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
        self.logger.debug(f"DELETE en '{table_name}': PK={pk} | eliminado={deleted} | {elapsed:.2f} ms.")
        return QueryResult(deleted, t.io_counter.snapshot(), elapsed, "DELETE")

    def scan(self, table_name: str) -> QueryResult:
        """Full table scan — costoso, solo para pruebas o reconstrucción."""
        t  = self._get_table(table_name)
        t0 = time.perf_counter()
        self._reset_io(t)

        self.logger.warning(f"Full Table Scan iniciado en '{table_name}'. Operación costosa.")
        records = [record for _, record in t.heap.scan()]

        elapsed = (time.perf_counter() - t0) * 1000
        self.logger.debug(f"Full Scan en '{table_name}': {len(records)} registro(s) | {elapsed:.2f} ms.")
        return QueryResult(records, t.io_counter.snapshot(), elapsed, "FULL SCAN")

    # Métricas y estado

    def get_table_stats(self, table_name: str) -> dict:
        t = self._get_table(table_name)
        return {
            "table":         table_name,
            "total_records": t.heap.total_records,
            "heap_pages":    t.heap.last_page_id + 1,
            "index_n_main":  t.index.n_main,
            "index_k_aux":   t.index.k_aux,
            "index_k_limit": t.index.k_limit,
            "index_pages":   t.index.last_main_page + 1,
            "heap_io":       t.heap_pm.get_stats(),
            "index_io":      t.index_pm.get_stats(),
        }

    # Helpers internos

    def _get_table(self, table_name: str) -> _TableEntry:
        if table_name not in self._tables:
            self.logger.error(f"Tabla '{table_name}' no encontrada. Usa create_table_from_csv u open_table primero.")
            raise KeyError(f"Tabla '{table_name}' no existe. Usa create_table_from_csv u open_table.")
        return self._tables[table_name]

    def _reset_io(self, t: _TableEntry) -> None:
        t.io_counter.reset()

    def flush_table(self, table_name: str) -> None:
        t = self._get_table(table_name)
        t.heap.flush_metadata()
        t.index.flush_metadata()
        self.logger.debug(f"Flush completado para '{table_name}'.")

    def flush_all(self) -> None:
        self.logger.info(f"Flushing todas las tablas ({len(self._tables)})...")
        for table_name in self._tables:
            self.flush_table(table_name)
        self.logger.info("Flush global completado.")

    def search_spatial_radius(self, table_name: str, x: float, y: float, radius: float) -> QueryResult:
        t  = self._get_table(table_name)
        t0 = time.perf_counter()
        self._reset_io(t)

        self.logger.info(f"Spatial Radius Search en '{table_name}': centro=({x}, {y}), radio={radius}.")
        rtree_results = t.rtree.rangeSearch((x, y), radius)
        rids    = [res[1] for res in rtree_results]
        records = t.heap.get_batch(rids) if rids else []

        elapsed = (time.perf_counter() - t0) * 1000
        self.logger.debug(f"RTREE RADIUS en '{table_name}': {len(records)} registro(s) | {elapsed:.2f} ms.")
        return QueryResult(records, t.io_counter.snapshot(), elapsed, "RTREE RADIUS")

    def search_spatial_knn(self, table_name: str, x: float, y: float, k: int) -> QueryResult:
        t  = self._get_table(table_name)
        t0 = time.perf_counter()
        self._reset_io(t)

        self.logger.info(f"Spatial KNN Search en '{table_name}': centro=({x}, {y}), k={k}.")
        rtree_results = t.rtree.knnSearch((x, y), k)
        rids    = [res[1] for res in rtree_results]
        records = t.heap.get_batch(rids) if rids else []

        elapsed = (time.perf_counter() - t0) * 1000
        self.logger.debug(f"RTREE KNN en '{table_name}': {len(records)} registro(s) | {elapsed:.2f} ms.")
        return QueryResult(records, t.io_counter.snapshot(), elapsed, "RTREE KNN")

    def visualize_rtree(self, table_name: str) -> str:
        """Genera la visualización del R-Tree asociado a la tabla y devuelve el path del archivo."""
        t = self._get_table(table_name)
        if not t.rtree:
            self.logger.error(f"La tabla '{table_name}' no tiene un R-Tree asociado.")
            raise Exception(f"La tabla '{table_name}' no tiene un R-Tree asociado.")

        # El método visualize del Rtree devuelve la ruta del PNG
        path = t.rtree.visualize()
        return path