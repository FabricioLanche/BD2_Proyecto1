import time
from typing import Dict
from DBMS.organization.data_structures import TableConfig, Record
from DBMS.organization.heap_file import HeapFile
from DBMS.organization.sequential_file import SequentialIndex
from DBMS.organization.page_manager import PageManager, IOCounter

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
    ):
        self.heap       = heap
        self.index      = index
        self.heap_pm    = heap_pm
        self.index_pm   = index_pm
        self.io_counter = io_counter
        self.config     = config
        self.pk_col     = pk_col



class DatabaseEngine:

    def __init__(self):
        self._tables: Dict[str, _TableEntry] = {}

    def create_table_from_csv(
        self,
        table_name: str,
        config: TableConfig,
        csv_path: str,
        pk_col: str,
    ) -> QueryResult:
        # Crea la tabla, carga el CSV en el HeapFile y construye el índice.
        
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

        # 1. Carga CSV → HeapFile
        print(f"  Cargando CSV: {csv_path}...")
        rids = heap.load_from_csv(csv_path)

        # 2. Construye índice
        print(f"  Indexando {len(rids)} registros...")
        for i, rid in enumerate(rids):
            record = heap.search(rid)
            index.add(record.get_pk(), rid)
            if (i + 1) % 10_000 == 0:
                print(f"    {i + 1}/{len(rids)} indexados")

        elapsed = (time.perf_counter() - t0) * 1000

        entry = _TableEntry(heap, index, heap_pm, index_pm, io_counter, config, pk_col)
        self._tables[table_name] = entry

        result = QueryResult([], io_counter.snapshot(), elapsed, "CREATE+LOAD")
        result.records = len(rids)  # devuelve cantidad de filas cargadas
        print(f"  Tabla '{table_name}' lista. {result}")

        # Flush metadata tras carga masiva
        heap.flush_metadata()
        index.flush_metadata()

        return result

    def open_table(
        self,
        table_name: str,
        config: TableConfig,
        pk_col: str,
    ) -> None:
        """
        Abre una tabla que ya existe en disco (sin cargar CSV).
        Útil para reabrir el engine entre sesiones.
        """
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
            heap, index, heap_pm, index_pm, io_counter, config, pk_col
        )

    # Operaciones principales

    def insert(self, table_name: str, record: Record) -> QueryResult:
        t  = self._get_table(table_name)
        t0 = time.perf_counter()
        self._reset_io(t)

        rid = t.heap.insert(record)
        t.index.add(record.get_pk(), rid)

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

    def flush_all(self) -> None:
        for table_name in self._tables:
            self.flush_table(table_name)
