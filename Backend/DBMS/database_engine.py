import time
from typing import Dict
import struct

from Backend.DBMS.organization.data_structures import TableConfig, Record
from Backend.DBMS.organization.buffer_manager import BufferManager, PageLockStats
from Backend.DBMS.organization.heap_file import HeapFile
from Backend.DBMS.organization.sequential_file import SequentialIndex
from Backend.DBMS.organization.page_manager import PageManager, IOCounter
from Backend.DBMS.utils.logger import ConsoleLogger
from Backend.DBMS.utils.path_utils import resolve_dataset_path, resolve_data_path

from Backend.DBMS.indexes.rtree import Rtree
from Backend.DBMS.indexes.extendible_hashing import ExtendibleHashing
from Backend.DBMS.indexes.b_plus_tree import BPlusTree


class QueryResult:
    def __init__(self, records, io_stats: dict, elapsed_ms: float, operation: str):
        self.records = records
        self.io_stats = io_stats
        self.elapsed_ms = elapsed_ms
        self.operation = operation

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
        hash_meta: list,
        btree_meta: list,
    ):
        self.heap = heap
        self.index = index
        self.heap_pm = heap_pm
        self.index_pm = index_pm
        self.io_counter = io_counter
        self.config = config
        self.pk_col = pk_col
        self.spatial_meta = spatial_meta
        self.rtree = None
        self.hash_meta = hash_meta or []
        self.hash_indices = {}
        self.btree_meta = btree_meta or []
        self.btree_indices = {}


class DatabaseEngine:
    def __init__(self, logger=None):
        self._tables: Dict[str, _TableEntry] = {}
        self.logger = logger or ConsoleLogger()
        self.lock_stats = PageLockStats()

    def _emit_concurrency(self, action: str, table_name: str, **details) -> None:
        if self.logger and getattr(self.logger, "allow_concurrency_events", False) and hasattr(self.logger, "concurrency"):
            detail = details.pop("detail", None)
            if detail is None:
                detail = f"{action} table:{table_name}"
            self.logger.concurrency(action, resource=f"table:{table_name}", detail=detail, **details)

    def _make_buffer_manager(self, filename: str, io_counter: IOCounter, page_size: int = None) -> BufferManager:
        page_manager = PageManager(filename, io_counter, page_size=page_size)
        return BufferManager(page_manager, self.lock_stats, logger=self.logger)

    def _decode_value(self, value):
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="ignore").rstrip("\x00")
        return value

    def create_table_from_csv(
        self,
        table_name: str,
        config: TableConfig,
        csv_path: str,
        pk_col: str,
        spatial_meta: dict,
        hash_meta: list = None,
        btree_meta: list = None,
        page_size: int = None,
    ) -> QueryResult:
        if table_name in self._tables:
            self.logger.error(f"Intento de crear tabla duplicada: '{table_name}' ya existe.")
            raise ValueError(f"Tabla '{table_name}' ya existe.")

        resolved_csv_path = resolve_dataset_path(csv_path)
        io_counter = IOCounter()

        heap_filename = resolve_data_path(f"{table_name}.heap", create_parent=True)
        index_filename = resolve_data_path(f"{table_name}_{pk_col}.idx", create_parent=True)

        heap_pm = self._make_buffer_manager(heap_filename, io_counter, page_size=page_size)
        index_pm = self._make_buffer_manager(index_filename, io_counter, page_size=page_size)

        heap = HeapFile(heap_filename, config, heap_pm)
        index = SequentialIndex(index_filename, index_pm, config.get_pk_format(), logger=self.logger)

        heap_pm.reset_counters()
        index_pm.reset_counters()
        io_counter.reset()

        t0 = time.perf_counter()

        original_k_limit = index.k_limit
        index.k_limit = 1_000_000
        index.bulk_load_mode = True

        self.logger.info(f"Cargando CSV '{resolved_csv_path}' en la tabla '{table_name}'...")
        results = heap.load_from_csv_optimized(resolved_csv_path)

        entry = _TableEntry(heap, index, heap_pm, index_pm, io_counter, config, pk_col, spatial_meta, hash_meta or [], btree_meta or [])

        for meta in hash_meta or []:
            col_name = meta["nombre"]
            hash_path = resolve_data_path(f"{table_name}_{col_name}.hash", create_parent=True)
            hash_pm = self._make_buffer_manager(hash_path, io_counter, page_size=page_size)
            entry.hash_indices[col_name] = ExtendibleHashing(hash_pm, config, col_name)

        for meta in btree_meta or []:
            col_name = meta["nombre"]
            btree_path = resolve_data_path(f"{table_name}_{col_name}.btree", create_parent=True)
            btree_pm = self._make_buffer_manager(btree_path, io_counter, page_size=page_size)
            key_fmt = config.get_column_format(col_name)
            entry.btree_indices[col_name] = BPlusTree(btree_path, btree_pm, key_format=key_fmt)

        idx_x, idx_y = -1, -1
        if spatial_meta:
            rtree_filename = f"{table_name}_spatial.bin"
            rtree_path = resolve_data_path(rtree_filename, create_parent=True)
            rtree_pm = self._make_buffer_manager(rtree_path, io_counter, page_size=page_size)
            entry.rtree = Rtree(rtree_filename, page_manager=rtree_pm)
            idx_x = config.column_map[spatial_meta["col_x"]]
            idx_y = config.column_map[spatial_meta["col_y"]]

        pk_idx = config.column_map[pk_col]

        for i, (rid, data_tuple) in enumerate(results):
            pk = self._decode_value(data_tuple[pk_idx])
            index.add(pk, rid)

            for col_name, h_index in entry.hash_indices.items():
                col_idx = config.column_map[col_name]
                h_index.add(self._decode_value(data_tuple[col_idx]), rid)

            for col_name, b_index in entry.btree_indices.items():
                col_idx = config.column_map[col_name]
                b_index.insert(self._decode_value(data_tuple[col_idx]), rid)

            if entry.rtree:
                point = (data_tuple[idx_x], data_tuple[idx_y])
                entry.rtree.insert(point, rid)

        index.flush_metadata()
        index.bulk_load_mode = False
        index.k_limit = original_k_limit

        if index.k_aux > 0:
            index.reconstruct()

        elapsed = (time.perf_counter() - t0) * 1000
        self._tables[table_name] = entry

        result = QueryResult([], io_counter.snapshot(), elapsed, "CREATE+LOAD")
        result.records = len(results)
        self.logger.info(f"Tabla '{table_name}' lista. {result}")

        heap.flush_metadata()
        index.flush_metadata()
        for h_index in entry.hash_indices.values():
            h_index.flush_metadata()
        for b_index in entry.btree_indices.values():
            b_index.flush_metadata()

        return result

    def open_table(
        self,
        table_name: str,
        config: TableConfig,
        pk_col: str,
        spatial_meta: dict = None,
        hash_meta: list = None,
        btree_meta: list = None,
        page_size: int = None,
    ) -> None:
        if table_name in self._tables:
            self.logger.debug(f"Tabla '{table_name}' ya estaba abierta. Se omite re-apertura.")
            return

        io_counter = IOCounter()

        heap_filename = resolve_data_path(f"{table_name}.heap", create_parent=True)
        index_filename = resolve_data_path(f"{table_name}_{pk_col}.idx", create_parent=True)

        heap_pm = self._make_buffer_manager(heap_filename, io_counter, page_size=page_size)
        index_pm = self._make_buffer_manager(index_filename, io_counter, page_size=page_size)

        heap = HeapFile(heap_filename, config, heap_pm)
        index = SequentialIndex(index_filename, index_pm, config.get_pk_format(), logger=self.logger)

        self._tables[table_name] = _TableEntry(
            heap, index, heap_pm, index_pm, io_counter, config, pk_col, spatial_meta, hash_meta or [], btree_meta or []
        )
        self.logger.info(f"Tabla '{table_name}' abierta desde disco.")

        if hash_meta:
            for meta in hash_meta:
                col_name = meta["nombre"]
                hash_path = resolve_data_path(f"{table_name}_{col_name}.hash", create_parent=True)
                hash_pm = self._make_buffer_manager(hash_path, io_counter, page_size=page_size)
                self._tables[table_name].hash_indices[col_name] = ExtendibleHashing(hash_pm, config, col_name)

        if btree_meta:
            for meta in btree_meta:
                col_name = meta["nombre"]
                btree_path = resolve_data_path(f"{table_name}_{col_name}.btree", create_parent=True)
                btree_pm = self._make_buffer_manager(btree_path, io_counter, page_size=page_size)
                key_fmt = config.get_column_format(col_name)
                self._tables[table_name].btree_indices[col_name] = BPlusTree(btree_path, btree_pm, key_format=key_fmt)

        if spatial_meta:
            rtree_filename = f"{table_name}_spatial.bin"
            rtree_path = resolve_data_path(rtree_filename, create_parent=True)
            rtree_pm = self._make_buffer_manager(rtree_path, io_counter, page_size=page_size)
            self._tables[table_name].rtree = Rtree(rtree_filename, page_manager=rtree_pm)
            self.logger.info(f"R-Tree espacial cargado para '{table_name}'.")

    def insert(self, table_name: str, record: Record) -> QueryResult:
        t = self._get_table(table_name)
        t0 = time.perf_counter()
        self._reset_io(t)
        pk_idx = t.config.column_map[t.pk_col]
        pk_val = self._decode_value(record.data_tuple[pk_idx])

        self._emit_concurrency(
            "insert_begin",
            table_name,
            pk=pk_val,
            detail=f"insert begin pk={pk_val}",
            heap_io=t.heap_pm.get_stats() if hasattr(t.heap_pm, "get_stats") else None,
            index_io=t.index_pm.get_stats() if hasattr(t.index_pm, "get_stats") else None,
        )

        rid = t.heap.insert(record)
        self._emit_concurrency(
            "heap_inserted",
            table_name,
            pk=pk_val,
            rid=rid,
            detail=f"heap inserted rid={rid}",
            heap_io=t.heap_pm.get_stats() if hasattr(t.heap_pm, "get_stats") else None,
        )

        t.index.add(pk_val, rid)
        self._emit_concurrency(
            "index_updated",
            table_name,
            pk=pk_val,
            rid=rid,
            detail=f"sequential index updated rid={rid}",
            index_io=t.index_pm.get_stats() if hasattr(t.index_pm, "get_stats") else None,
        )

        for col_name, h_index in t.hash_indices.items():
            col_idx = t.config.column_map[col_name]
            h_index.add(self._decode_value(record.data_tuple[col_idx]), rid)

        for col_name, b_index in t.btree_indices.items():
            col_idx = t.config.column_map[col_name]
            b_index.insert(self._decode_value(record.data_tuple[col_idx]), rid)

        if t.rtree:
            idx_x = t.config.column_map[t.spatial_meta["col_x"]]
            idx_y = t.config.column_map[t.spatial_meta["col_y"]]
            point = (record.data_tuple[idx_x], record.data_tuple[idx_y])
            t.rtree.insert(point, rid)

        elapsed = (time.perf_counter() - t0) * 1000
        self._emit_concurrency(
            "flush_begin",
            table_name,
            pk=pk_val,
            elapsed_ms=round(elapsed, 3),
            detail=f"flush begin pk={pk_val}",
        )
        self.flush_table(table_name)
        self._emit_concurrency(
            "flush_end",
            table_name,
            pk=pk_val,
            elapsed_ms=round(elapsed, 3),
            detail=f"flush end pk={pk_val}",
            heap_io=t.heap_pm.get_stats() if hasattr(t.heap_pm, "get_stats") else None,
            index_io=t.index_pm.get_stats() if hasattr(t.index_pm, "get_stats") else None,
        )
        return QueryResult(rid, t.io_counter.snapshot(), elapsed, "INSERT")

    def search(self, table_name: str, pk) -> QueryResult:
        t = self._get_table(table_name)
        t0 = time.perf_counter()
        self._reset_io(t)

        rid = t.index.search_rid(pk)
        record = t.heap.search(rid) if rid else None

        elapsed = (time.perf_counter() - t0) * 1000
        found = record is not None
        return QueryResult(record, t.io_counter.snapshot(), elapsed, "SELECT")

    def range_search(self, table_name: str, pk_start, pk_end) -> QueryResult:
        t = self._get_table(table_name)
        t0 = time.perf_counter()
        self._reset_io(t)

        rids = t.index.range_search_rids(pk_start, pk_end)
        records = t.heap.get_batch(rids) if rids else []

        elapsed = (time.perf_counter() - t0) * 1000
        return QueryResult(records, t.io_counter.snapshot(), elapsed, "SELECT RANGE")

    def delete(self, table_name: str, pk) -> QueryResult:
        t = self._get_table(table_name)
        t0 = time.perf_counter()
        self._reset_io(t)

        rid = t.index.search_rid(pk)
        if not rid:
            elapsed = (time.perf_counter() - t0) * 1000
            return QueryResult(False, t.io_counter.snapshot(), elapsed, "DELETE")

        record = t.heap.search(rid)

        if record:
            for col_name, h_index in t.hash_indices.items():
                col_idx = t.config.column_map[col_name]
                h_index.remove(self._decode_value(record.data_tuple[col_idx]), rid)

            for col_name, b_index in t.btree_indices.items():
                col_idx = t.config.column_map[col_name]
                b_index.remove(self._decode_value(record.data_tuple[col_idx]), rid)

            if t.rtree:
                idx_x = t.config.column_map[t.spatial_meta["col_x"]]
                idx_y = t.config.column_map[t.spatial_meta["col_y"]]
                point = (record.data_tuple[idx_x], record.data_tuple[idx_y])
                t.rtree.remove(point)

        deleted = t.heap.delete(rid)
        t.index.remove(pk)

        elapsed = (time.perf_counter() - t0) * 1000
        self.flush_table(table_name)
        return QueryResult(deleted, t.io_counter.snapshot(), elapsed, "DELETE")

    def scan(self, table_name: str) -> QueryResult:
        t = self._get_table(table_name)
        t0 = time.perf_counter()
        self._reset_io(t)

        records = [record for _, record in t.heap.scan()]

        elapsed = (time.perf_counter() - t0) * 1000
        return QueryResult(records, t.io_counter.snapshot(), elapsed, "FULL SCAN")

    def search_hash(self, table_name: str, col_name: str, val) -> QueryResult:
        t = self._get_table(table_name)
        t0 = time.perf_counter()
        self._reset_io(t)

        h_index = t.hash_indices[col_name]
        rids = h_index.search_rid(self._decode_value(val))
        records = [t.heap.search(rid) for rid in rids] if rids else []

        elapsed = (time.perf_counter() - t0) * 1000
        return QueryResult(records, t.io_counter.snapshot(), elapsed, "HASH SEARCH")

    def search_btree(self, table_name: str, col_name: str, val) -> QueryResult:
        t = self._get_table(table_name)
        t0 = time.perf_counter()
        self._reset_io(t)

        b_index = t.btree_indices[col_name]
        rids = b_index.search(self._decode_value(val))
        records = [t.heap.search(rid) for rid in rids] if rids else []

        elapsed = (time.perf_counter() - t0) * 1000
        return QueryResult(records, t.io_counter.snapshot(), elapsed, "BTREE SEARCH")

    def range_search_btree(self, table_name: str, col_name: str, v1, v2) -> QueryResult:
        t = self._get_table(table_name)
        t0 = time.perf_counter()
        self._reset_io(t)

        b_index = t.btree_indices[col_name]
        results = b_index.range_search(self._decode_value(v1), self._decode_value(v2))
        rids = [res[1] for res in results] if results else []
        records = [t.heap.search(rid) for rid in rids] if rids else []

        elapsed = (time.perf_counter() - t0) * 1000
        return QueryResult(records, t.io_counter.snapshot(), elapsed, "BTREE RANGE")

    def filter_scan(self, table_name: str, col_name: str, op: str, val) -> QueryResult:
        t = self._get_table(table_name)
        t0 = time.perf_counter()
        self._reset_io(t)

        records = t.heap.filter_records(col_name, op, self._decode_value(val))

        elapsed = (time.perf_counter() - t0) * 1000
        return QueryResult(records, t.io_counter.snapshot(), elapsed, "FULL TABLE SCAN")

    def get_table_stats(self, table_name: str) -> dict:
        t = self._get_table(table_name)
        return {
            "table": table_name,
            "total_records": t.heap.total_records,
            "heap_pages": t.heap.last_page_id + 1,
            "index_n_main": t.index.n_main,
            "index_k_aux": t.index.k_aux,
            "index_k_limit": t.index.k_limit,
            "index_pages": t.index.last_main_page + 1,
            "heap_io": t.heap_pm.get_stats(),
            "index_io": t.index_pm.get_stats(),
        }

    def _get_table(self, table_name: str) -> _TableEntry:
        if table_name not in self._tables:
            self.logger.error(f"Tabla '{table_name}' no encontrada. Usa create_table_from_csv u open_table primero.")
            raise KeyError(f"Tabla '{table_name}' no existe. Usa create_table_from_csv u open_table.")
        return self._tables[table_name]

    def _reset_io(self, t: _TableEntry) -> None:
        t.io_counter.reset()

    def flush_table(self, table_name: str) -> None:
        t = self._get_table(table_name)
        self._emit_concurrency(
            "flush_table_begin",
            table_name,
            detail=f"flush_table begin {table_name}",
            heap_io=t.heap_pm.get_stats() if hasattr(t.heap_pm, "get_stats") else None,
            index_io=t.index_pm.get_stats() if hasattr(t.index_pm, "get_stats") else None,
        )
        t.heap.flush_metadata()
        t.index.flush_metadata()
        for h_index in t.hash_indices.values():
            h_index.flush_metadata()
        for b_index in t.btree_indices.values():
            b_index.flush_metadata()
        self.logger.debug(f"Flush completado para '{table_name}'.")
        self._emit_concurrency(
            "flush_table_end",
            table_name,
            detail=f"flush_table end {table_name}",
            heap_io=t.heap_pm.get_stats() if hasattr(t.heap_pm, "get_stats") else None,
            index_io=t.index_pm.get_stats() if hasattr(t.index_pm, "get_stats") else None,
        )

    def flush_all(self) -> None:
        self.logger.info(f"Flushing todas las tablas ({len(self._tables)})...")
        for table_name in self._tables:
            self.flush_table(table_name)
        self.logger.info("Flush global completado.")

    def search_spatial_radius(self, table_name: str, x: float, y: float, radius: float) -> QueryResult:
        t = self._get_table(table_name)
        t0 = time.perf_counter()
        self._reset_io(t)

        rtree_results = t.rtree.rangeSearch((x, y), radius)
        rids = [res[1] for res in rtree_results]
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

    def visualize_rtree(self, table_name: str) -> str:
        t = self._get_table(table_name)
        if not t.rtree:
            self.logger.error(f"La tabla '{table_name}' no tiene un R-Tree asociado.")
            raise Exception(f"La tabla '{table_name}' no tiene un R-Tree asociado.")

        return t.rtree.visualize()

    def rebuild_rtree(self, table_name: str) -> None:
        t = self._get_table(table_name)
        if not t.rtree:
            self.logger.error(f"La tabla '{table_name}' no tiene un R-Tree asociado.")
            raise Exception(f"La tabla '{table_name}' no tiene un R-Tree asociado.")

        # Vaciar/reestructurar archivo rtree (recrear estructura)
        rtree_filename = f"{table_name}_spatial.bin"
        rtree_path = resolve_data_path(rtree_filename, create_parent=True)
        rtree_pm = self._make_buffer_manager(rtree_path, t.io_counter, page_size=t.heap_pm.PAGE_SIZE)
        t.rtree = Rtree(rtree_filename, page_manager=rtree_pm)

        count = 0
        # Recorrer páginas del heap y reinsertar registros no eliminados
        deleted_rids = t.heap._get_deleted_rids()
        for page_id in range(1, t.heap.last_page_id + 1):
            try:
                page = t.heap.pm.read_page(page_id)
            except Exception:
                continue
            record_count = t.heap._read_page_header(page)
            for slot_id in range(record_count):
                if (page_id, slot_id) in deleted_rids:
                    continue
                record_bytes = t.heap._read_record_from_slot(page, slot_id)
                data_tuple = struct.unpack(t.heap.config.data_format, record_bytes)
                # crear Record-like estructura mínima
                point = (data_tuple[t.config.column_map[t.spatial_meta["col_x"]]], data_tuple[t.config.column_map[t.spatial_meta["col_y"]]])
                rid = (page_id, slot_id)
                ok = t.rtree.insert(point, rid)
                if ok:
                    count += 1

        self.logger.info(f"R-Tree reconstruido para '{table_name}': {count} entradas insertadas.")
