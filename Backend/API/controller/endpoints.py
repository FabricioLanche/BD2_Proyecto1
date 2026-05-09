from fastapi import File, APIRouter, UploadFile, HTTPException
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel
from pathlib import Path
import shutil
import threading
import queue
import os
import json

from Backend.DBMS.utils.logger import QueueLogger
from DBMS.SQLengine import DBMSEngine
from Backend.DBMS.utils.path_utils import DATA_DIR, DATASETS_DIR, GRAPH_DIR

router = APIRouter()

ROOT_DIR = Path(__file__).resolve().parents[3]
UPLOAD_DIR = ROOT_DIR / "Backend" / "DBMS" / "datasets"

ENGINE = DBMSEngine()
ENGINE_LOCK = threading.Lock()

class QueryRequest(BaseModel):
    query: str

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
                yield json.dumps(item) + "\n"
            elif item.get("type") == "image":
                yield json.dumps(item) + "\n"
            else:
                msg = item.get('message')
                if msg is None:
                    yield json.dumps(item) + "\n"
                else:
                    yield f"[{item['level']}]: {msg}\n"

        thread.join()

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