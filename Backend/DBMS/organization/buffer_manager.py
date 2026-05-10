from collections import defaultdict
import os
from Backend.DBMS.LockManager import LockManager, DeadlockError

class PageLockStats:
    def __init__(self):
        self.shared_by_page = defaultdict(int)
        self.exclusive_by_page = defaultdict(int)

    def acquire_shared(self, page_id: int) -> None:
        self.shared_by_page[page_id] += 1

    def acquire_exclusive(self, page_id: int) -> None:
        self.exclusive_by_page[page_id] += 1

    @property
    def shared_total(self) -> int:
        return sum(self.shared_by_page.values())

    @property
    def exclusive_total(self) -> int:
        return sum(self.exclusive_by_page.values())

    def snapshot(self) -> dict:
        return {
            "shared_total": self.shared_total,
            "exclusive_total": self.exclusive_total,
            "shared_by_page": dict(self.shared_by_page),
            "exclusive_by_page": dict(self.exclusive_by_page),
        }

class BufferManager:
    def __init__(self, page_manager, lock_stats: PageLockStats = None, logger=None, lock_manager: LockManager = None, lock_timeout: float = 5.0):
        self.pm = page_manager
        self.lock_stats = lock_stats or PageLockStats()
        self.logger = logger
        self.lock_manager = lock_manager or LockManager(logger=logger)
        if logger is not None and hasattr(self.lock_manager, "logger"):
            self.lock_manager.logger = logger
        self.lock_timeout = lock_timeout
        self._allocation_lock = None
        self.cache = {}
        self.db_filename = self.pm.db_filename
        self.PAGE_SIZE = self.pm.PAGE_SIZE
        self.io_counter = getattr(self.pm, "io_counter", None)
        self.last_page_id_loaded = -1
        self.last_page_data = None

    def __getattr__(self, name):
        return getattr(self.pm, name)

    def _emit_concurrency(self, action: str, page_id: int, **details) -> None:
        if self.logger and getattr(self.logger, "allow_concurrency_events", False) and hasattr(self.logger, "concurrency"):
            detail = details.pop("detail", None)
            payload = {
                "cache_size": len(self.cache),
                "last_page_id_loaded": self.last_page_id_loaded,
                "last_page_data_present": self.last_page_data is not None,
            }
            if hasattr(self.pm, "get_stats"):
                payload["io_stats"] = self.pm.get_stats()
            payload.update(details)
            if detail is None:
                detail = f"{os.path.basename(self.db_filename)}:{page_id}"
            self.logger.concurrency(action, resource=f"{self.db_filename}:{page_id}", detail=detail, **payload)

    def read_page(self, page_id):
        self.lock_stats.acquire_shared(page_id)
        try:
            with self.lock_manager.shared(page_id, timeout=self.lock_timeout):
                if page_id in self.cache:
                    self._emit_concurrency("read_page", page_id, source="cache", lock_mode="shared")
                    if self.logger:
                        self.logger.debug(f"Página {page_id} servida desde la caché del PageManager para '{self.db_filename}'.")
                    data = self.cache[page_id]
                    self.last_page_id_loaded = page_id
                    self.last_page_data = data
                    return data

                if self.logger:
                    self.logger.debug(f"Página {page_id} no estaba en caché; se lee desde PageManager para '{self.db_filename}'.")
                data = self.pm.read_page(page_id)
                self.cache[page_id] = data
                self.last_page_id_loaded = page_id
                self.last_page_data = data
                self._emit_concurrency("read_page", page_id, source="disk", lock_mode="shared")
                return data
        except DeadlockError:
            if self.logger:
                self.logger.error(f"Deadlock detectado al intentar leer la página {page_id} de '{self.db_filename}'.")
            raise

    def write_page(self, page_id, data):
        self.lock_stats.acquire_exclusive(page_id)
        try:
            with self.lock_manager.exclusive(page_id, timeout=self.lock_timeout):
                if self.logger:
                    self.logger.debug(f"Página {page_id} marcada para escritura en PageManager para '{self.db_filename}'.")
                payload = data.ljust(self.PAGE_SIZE, b'\x00')
                self.cache[page_id] = payload
                self.pm.write_page(page_id, data)

                if page_id == self.last_page_id_loaded:
                    self.last_page_data = payload
                self._emit_concurrency("write_page", page_id, lock_mode="exclusive", bytes_written=len(data))
        except DeadlockError:
            raise

    def allocate_new_page(self) -> int:
        if self._allocation_lock is None:
            from threading import Lock
            self._allocation_lock = Lock()

        with self._allocation_lock:
            page_id = self.pm.allocate_new_page()
            self.lock_stats.acquire_exclusive(page_id)
            if self.logger:
                self.logger.debug(f"Se asignó la página {page_id} en PageManager para '{self.db_filename}'.")
            self.cache[page_id] = b'\x00' * self.PAGE_SIZE
            self.last_page_id_loaded = page_id
            self.last_page_data = self.cache[page_id]
            self._emit_concurrency("allocate_page", page_id, lock_mode="exclusive")
            return page_id

    def invalidate_cache(self):
        self.cache.clear()
        self.last_page_id_loaded = -1
        self.last_page_data = None

    def reset_counters(self):
        if hasattr(self.pm, "reset_counters"):
            self.pm.reset_counters()

    def get_stats(self):
        if hasattr(self.pm, "get_stats"):
            return self.pm.get_stats()
        return {"reads": 0, "writes": 0, "total": 0}