from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass


class DeadlockError(TimeoutError):
    pass


@dataclass
class _PageLockState:
    shared_count: int = 0
    exclusive_owner: int | None = None
    exclusive_count: int = 0


class LockManager:
    def __init__(self, logger=None):
        self._condition = threading.Condition(threading.RLock())
        self._locks: dict[int, _PageLockState] = {}
        self.logger = logger

    def _emit(self, action: str, page_id: int, mode: str, **details) -> None:
        if self.logger and getattr(self.logger, "allow_concurrency_events", False) and hasattr(self.logger, "concurrency"):
            detail = details.pop("detail", None)
            if detail is None:
                detail = f"{action} {mode} page:{page_id}"
            self.logger.concurrency(action, resource=f"page:{page_id}", mode=mode, detail=detail, **details)

    def _get_state(self, page_id: int) -> _PageLockState:
        state = self._locks.get(page_id)
        if state is None:
            state = _PageLockState()
            self._locks[page_id] = state
        return state

    def _thread_id(self) -> int:
        return threading.get_ident()

    def acquire_shared(self, page_id: int, timeout: float | None = None) -> None:
        deadline = None if timeout is None else time.monotonic() + timeout
        thread_id = self._thread_id()
        
        with self._condition:
            state = self._get_state(page_id)
            # Esperar a que no haya exclusive lock
            while state.exclusive_owner is not None:
                self._emit(
                    "wait",
                    page_id,
                    "shared",
                    thread_id=thread_id,
                    owner=state.exclusive_owner,
                    shared_count=state.shared_count,
                    exclusive_count=state.exclusive_count,
                )
                if deadline is not None and time.monotonic() >= deadline:
                    self._emit(
                        "deadlock",
                        page_id,
                        "shared",
                        thread_id=thread_id,
                        owner=state.exclusive_owner,
                        shared_count=state.shared_count,
                        exclusive_count=state.exclusive_count,
                    )
                    raise DeadlockError(f"timeout esperando lock shared page:{page_id}")
                
                remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
                self._condition.wait(timeout=remaining)
            
            # Ya no hay exclusive lock, adquirir shared
            state.shared_count += 1
            self._emit(
                "acquired",
                page_id,
                "shared",
                thread_id=thread_id,
                shared_count=state.shared_count,
                exclusive_count=state.exclusive_count,
            )

    def acquire_exclusive(self, page_id: int, timeout: float | None = None) -> None:
        deadline = None if timeout is None else time.monotonic() + timeout
        thread_id = self._thread_id()

        with self._condition:
            state = self._get_state(page_id)
            while True:
                can_reenter = state.exclusive_owner == thread_id
                # Solo adquirir si: no hay shared locks y (no hay exclusive o somos el owner)
                if (state.shared_count == 0 and state.exclusive_owner is None) or can_reenter:
                    state.exclusive_owner = thread_id
                    state.exclusive_count += 1
                    self._emit(
                        "acquired",
                        page_id,
                        "exclusive",
                        thread_id=thread_id,
                        shared_count=state.shared_count,
                        exclusive_count=state.exclusive_count,
                    )
                    return

                self._emit(
                    "wait",
                    page_id,
                    "exclusive",
                    thread_id=thread_id,
                    owner=state.exclusive_owner,
                    shared_count=state.shared_count,
                    exclusive_count=state.exclusive_count,
                )
                if deadline is not None and time.monotonic() >= deadline:
                    # Incluir métricas de lock al emitir deadlock para trazabilidad
                    self._emit(
                        "deadlock",
                        page_id,
                        "exclusive",
                        thread_id=thread_id,
                        owner=state.exclusive_owner,
                        shared_count=state.shared_count,
                        exclusive_count=state.exclusive_count,
                    )
                    raise DeadlockError(f"timeout esperando lock exclusive page:{page_id}")

                remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
                self._condition.wait(timeout=remaining)

    def release_shared(self, page_id: int) -> None:
        with self._condition:
            state = self._locks.get(page_id)
            if state is None or state.shared_count <= 0:
                return

            state.shared_count -= 1
            self._emit(
                "released",
                page_id,
                "shared",
                shared_count=state.shared_count,
                exclusive_count=state.exclusive_count,
            )
            if state.shared_count == 0 and state.exclusive_owner is None:
                self._locks.pop(page_id, None)
            self._condition.notify_all()

    def release_exclusive(self, page_id: int) -> None:
        with self._condition:
            state = self._locks.get(page_id)
            if state is None or state.exclusive_count <= 0:
                return

            state.exclusive_count -= 1
            if state.exclusive_count == 0:
                state.exclusive_owner = None
                if state.shared_count == 0:
                    self._locks.pop(page_id, None)
            self._emit(
                "released",
                page_id,
                "exclusive",
                shared_count=state.shared_count,
                exclusive_count=state.exclusive_count,
            )
            self._condition.notify_all()

    @contextmanager
    def shared(self, page_id: int, timeout: float | None = None):
        self.acquire_shared(page_id, timeout=timeout)
        try:
            yield
        finally:
            self.release_shared(page_id)

    @contextmanager
    def exclusive(self, page_id: int, timeout: float | None = None):
        self.acquire_exclusive(page_id, timeout=timeout)
        try:
            yield
        finally:
            self.release_exclusive(page_id)
