from fastapi import File, APIRouter, UploadFile, HTTPException
from pydantic import BaseModel
from pathlib import Path
import shutil
import os
import json

router = APIRouter()

ROOT_DIR = Path(__file__).resolve().parents[3]
UPLOAD_DIR = ROOT_DIR / "Backend" / "DBMS" / "datasets"

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
            
            # Manejar dos tipos de items:
            # 1. Log simple: {"level": "...", "message": "..."}
            # 2. Resultado tabular: {"level": "RESULT", "type": "table", "columns": [...], "rows": [...]}
            if item.get("type") == "table":
                # Serializar como JSON para que el frontend lo pueda parsear
                yield json.dumps(item) + "\n"
            else:
                # Log simple
                yield f"[{item['level']}]: {item['message']}\n"

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


@router.delete("/dataset/{filename}")
async def delete_dataset(filename: str):
    file_path = UPLOAD_DIR / filename

    if not file_path.resolve().is_file() or UPLOAD_DIR.resolve() not in file_path.resolve().parents:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")

    file_path.unlink()

    return {"message": f"{filename} eliminado"}

@router.post("/restart")
async def restart():
    if os.path.exists(UPLOAD_DIR):
        shutil.rmtree(UPLOAD_DIR)

    return {"message": "Datasets eliminados"}
