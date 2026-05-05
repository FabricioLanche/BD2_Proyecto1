from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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