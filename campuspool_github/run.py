import sys
import os
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

import uvicorn
from backend.app.database import init_db
from backend.app.services import SimulatorService
from backend.app.main import app

def main():
    print("=" * 60)
    print("CampusPool - University-Only Ride Sharing System")
    print("=" * 60)
    print("Initializing SQLite Database...")
    init_db()
    print("Checking / Seeding demo campus users, vehicles, and rides...")
    SimulatorService.seed_data()
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    print("-" * 60)
    print("CampusPool Server Starting at:")
    print(f"   -> Web Application: http://{host}:{port}")
    print(f"   -> Swagger API Docs: http://{host}:{port}/docs")
    print("-" * 60)
    print("Press CTRL+C to stop the server.")
    uvicorn.run("backend.app.main:app", host=host, port=port, reload=False)

if __name__ == "__main__":
    main()
