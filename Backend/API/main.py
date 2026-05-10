import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
try:
    from Backend.API.controller import endpoints as endpoints_module
except Exception:
    # fallback for direct execution context
    from controller import endpoints as endpoints_module

app = FastAPI(title="BD2 Proyecto1 API")

app.include_router(endpoints_module.router, prefix="/api")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)