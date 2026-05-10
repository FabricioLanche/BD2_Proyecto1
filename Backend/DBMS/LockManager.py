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
    def __init__(self):
        self._condition = threading.Condition(threading.RLock())
        self._locks: dict[int, _PageLockState] = {}

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
            while state.exclusive_owner is not None and state.exclusive_owner != thread_id:
                if deadline is not None and time.monotonic() >= deadline:
                    raise DeadlockError(f"Deadlock: timeout esperando lock shared para página {page_id}")
                remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
                self._condition.wait(timeout=remaining)

            state.shared_count += 1

    def acquire_exclusive(self, page_id: int, timeout: float | None = None) -> None:
        deadline = None if timeout is None else time.monotonic() + timeout
        thread_id = self._thread_id()

        with self._condition:
            state = self._get_state(page_id)
            while True:
                can_reenter = state.exclusive_owner == thread_id
                no_shared_owners = state.shared_count == 0 or (can_reenter and state.shared_count == 1)
                if can_reenter or (state.exclusive_owner is None and no_shared_owners):
                    state.exclusive_owner = thread_id
                    state.exclusive_count += 1
                    return

                if deadline is not None and time.monotonic() >= deadline:
                    raise DeadlockError(f"Deadlock: timeout esperando lock exclusive para página {page_id}")

                remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
                self._condition.wait(timeout=remaining)

    def release_shared(self, page_id: int) -> None:
        with self._condition:
            state = self._locks.get(page_id)
            if state is None or state.shared_count <= 0:
                return

            state.shared_count -= 1
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
