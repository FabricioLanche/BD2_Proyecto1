from fastapi import File, APIRouter, UploadFile, HTTPException
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel
from pathlib import Path
import shutil
import threading
import queue
import os
import json
import time
from typing import Optional
import base64

from Backend.DBMS.utils.logger import QueueLogger
from Backend.DBMS.SQLengine import DBMSEngine
from Backend.DBMS.utils.path_utils import DATA_DIR, DATASETS_DIR, GRAPH_DIR

router = APIRouter()

ROOT_DIR = Path(__file__).resolve().parents[3]
UPLOAD_DIR = ROOT_DIR / "Backend" / "DBMS" / "datasets"

ENGINE = DBMSEngine()
ENGINE_LOCK = threading.Lock()

def _json_bytes_default(o):
    if isinstance(o, (bytes, bytearray)):
        return base64.b64encode(o).decode('ascii')
    raise TypeError(f'Object of type {o.__class__.__name__} is not JSON serializable')

class QueryRequest(BaseModel):
    query: str


class ConcurrentUserRequest(BaseModel):
    user_id: Optional[str] = None
    query: str


class ConcurrentQueryRequest(BaseModel):
    users: list[ConcurrentUserRequest]


class ConcurrentQueueLogger:
    def __init__(self, q: queue.Queue):
        self.q = q
        self._local = threading.local()
        self.allow_concurrency_events = True

    def bind_user(self, user_id: str, started_at: float | None = None) -> None:
        self._local.user_id = user_id
        if started_at is not None:
            self._local.started_at = started_at

    def clear_user(self) -> None:
        if hasattr(self._local, 'user_id'):
            del self._local.user_id
        if hasattr(self._local, 'started_at'):
            del self._local.started_at

    def _current_user_id(self) -> str:
        return getattr(self._local, 'user_id', 'unknown')

    def _push(self, payload: dict) -> None:
        payload['user_id'] = self._current_user_id()
        payload['time_ms'] = round((time.perf_counter() - getattr(self._local, 'started_at', time.perf_counter())) * 1000, 3)
        self.q.put(payload)

    def log(self, level, msg: str):
        self._push({
            'level': getattr(level, 'value', str(level)),
            'message': msg,
        })

    def result(self, columns: list, rows: list, description: str = ''):
        self._push({
            'level': 'RESULT',
            'type': 'table',
            'columns': columns,
            'rows': rows,
            'description': description,
        })

    def image(self, path: str):
        self._push({
            'level': 'IMAGE',
            'type': 'image',
            'path': path,
        })

    def info(self, msg: str):
        self.log('INFO', msg)

    def error(self, msg: str):
        self.log('ERROR', msg)

    def warning(self, msg: str):
        self.log('WARNING', msg)

    def debug(self, msg: str):
        self.log('DEBUG', msg)

    def concurrency(self, action: str, resource: str = '', **details):
        payload = {
            'level': 'CONCURRENCY',
            'type': 'concurrency',
            'action': action,
            'resource': resource,
        }
        payload.update(details)
        if 'detail' not in payload:
            detail_bits = [action]
            if resource:
                detail_bits.append(resource)
            payload['detail'] = ' | '.join(detail_bits)
        self._push(payload)

@router.post("/query")
def ejecutar_query(data: QueryRequest):

    log_queue = queue.Queue()
    logger = QueueLogger(log_queue)

    _SENTINEL = object()

    def run_engine():
        try:
            with ENGINE_LOCK:
                previous_logger = ENGINE.logger
                ENGINE.set_logger(logger)
                try:
                    ENGINE.execute_query(data.query)
                finally:
                    ENGINE.set_logger(previous_logger)
        except Exception as e:
            logger.error(f"Error inesperado en el engine: {e}")
        finally:
            log_queue.put(_SENTINEL)

    def generator():
        thread = threading.Thread(target=run_engine, daemon=True)
        thread.start()

        while True:
            item = log_queue.get()
            if item is _SENTINEL:
                break
            
            if item.get("type") == "table":
                yield json.dumps(item, ensure_ascii=False, default=_json_bytes_default) + "\n"
            elif item.get("type") == "image":
                yield json.dumps(item, ensure_ascii=False, default=_json_bytes_default) + "\n"
            elif item.get("type") == "concurrency":
                yield json.dumps(item, ensure_ascii=False, default=_json_bytes_default) + "\n"
            else:
                msg = item.get('message')
                if msg is None:
                    yield json.dumps(item, ensure_ascii=False, default=_json_bytes_default) + "\n"
                else:
                    yield f"[{item['level']}]: {msg}\n"

        thread.join()

    return StreamingResponse(generator(), media_type="text/plain")


@router.post("/query/concurrent")
def ejecutar_query_concurrente(data: ConcurrentQueryRequest):
    if not data.users:
        raise HTTPException(status_code=400, detail="Se requiere al menos un usuario")

    normalized_users = [
        ConcurrentUserRequest(
            user_id=user.user_id or f"user-{index + 1}",
            query=user.query,
        )
        for index, user in enumerate(data.users)
    ]

    log_queue = queue.Queue()
    logger = ConcurrentQueueLogger(log_queue)
    total_users = len(normalized_users)

    def run_user(user: ConcurrentUserRequest):
        started_at = time.perf_counter()
        logger.bind_user(user.user_id or 'unknown', started_at)
        log_queue.put({
            'type': 'start',
            'user_id': logger._current_user_id(),
            'time_ms': 0.0,
            'query': user.query,
        })

        try:
            ENGINE.execute_query(user.query)
        except Exception as e:
            logger.error(f"Error inesperado en la simulacion concurrente: {e}")
        finally:
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            log_queue.put({
                'type': 'done',
                'user_id': logger._current_user_id(),
                'time_ms': round((time.perf_counter() - started_at) * 1000, 3),
                'elapsed_ms': round(elapsed_ms, 3),
            })
            logger.clear_user()

    def generator():
        previous_logger = None
        with ENGINE_LOCK:
            previous_logger = ENGINE.logger
            ENGINE.set_logger(logger)

        try:
            threads = [
                threading.Thread(target=run_user, args=(user,), daemon=True)
                for user in normalized_users
            ]

            for thread in threads:
                thread.start()

            finished_users = 0
            while finished_users < total_users:
                item = log_queue.get()
                yield json.dumps(item, ensure_ascii=False, default=_json_bytes_default) + "\n"
                if item.get('type') == 'done':
                    finished_users += 1

            for thread in threads:
                thread.join()
        finally:
            with ENGINE_LOCK:
                ENGINE.set_logger(previous_logger)

    return StreamingResponse(generator(), media_type="text/plain")

@router.get("/dataset/list")
async def list_datasets():
    if not os.path.exists(UPLOAD_DIR):
        return {"datasets": []}
    archivos = [
        file
        for file in os.listdir(UPLOAD_DIR)
        if file.endswith(".csv") and os.path.isfile(os.path.join(UPLOAD_DIR, file))
    ]
    return {"datasets": archivos}

def get_unique_filename(directory, filename):
    name, ext = os.path.splitext(filename)
    counter = 2
    new_filename = filename
    while os.path.exists(os.path.join(directory, new_filename)):
        new_filename = f"{name}({counter}){ext}"
        counter += 1
    return new_filename

@router.post("/dataset")
async def create_dataset(file: UploadFile = File(...)):
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    unique_name = get_unique_filename(UPLOAD_DIR, file.filename)
    file_path = os.path.join(UPLOAD_DIR, unique_name)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return {"message": "Dataset guardado", "path": file_path}


@router.get("/graph/{filename}")
def get_graph(filename: str):
    graph_dir = ROOT_DIR / "Backend" / "DBMS" / "graphs"
    file_path = graph_dir / filename
    if not file_path.exists() or not file_path.resolve().is_file() or graph_dir.resolve() not in file_path.resolve().parents:
        raise HTTPException(status_code=404, detail="Imagen no encontrada")
    return FileResponse(str(file_path), media_type="image/png")

@router.delete("/dataset/{filename}")
async def delete_dataset(filename: str):
    file_path = UPLOAD_DIR / filename
    if not file_path.resolve().is_file() or UPLOAD_DIR.resolve() not in file_path.resolve().parents:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    file_path.unlink()
    return {"message": f"{filename} eliminado"}

@router.post("/restart")
async def restart():
    global ENGINE
    
    for directory in [DATA_DIR, DATASETS_DIR, GRAPH_DIR]:
        dir_path = Path(directory)
        if dir_path.exists():
            shutil.rmtree(dir_path)
    
    with ENGINE_LOCK:
        ENGINE = DBMSEngine()
    
    return {"message": "Sistema reiniciado: directorios eliminados y engine reiniciado"}