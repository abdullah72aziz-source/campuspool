import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from .database import init_db
from .services import SimulatorService
from .api import api_router
from .config import UPLOAD_DIR

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / 'frontend'

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    SimulatorService.seed_data()
    yield

app = FastAPI(
    title="CampusPool API",
    description="University Ride-Sharing System with Route Overlap, Timetable Matching, Fare Pitching & Safety Verification",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)

# Mount uploads directory for ID/selfie verification inspect
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

# Mount frontend directory for SPA
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
