import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Vercel serverless has a read-only filesystem except /tmp
if os.getenv('VERCEL'):
    DATA_DIR = Path('/tmp/data')
    UPLOAD_DIR = Path('/tmp/uploads')
else:
    DATA_DIR = BASE_DIR / 'data'
    UPLOAD_DIR = BASE_DIR / 'uploads'

DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = str(DATA_DIR / 'campuspool.db')
SECRET_KEY = os.getenv('CAMPUSPOOL_SECRET', 'iobm-karachi-secret-key-2026')

# University: Institute of Business Management (IoBM), Karachi, Pakistan
UNIVERSITY_NAME = "Institute of Business Management (IoBM)"
IOBM_CAMPUS_COORDS = (24.8270, 67.1142) # Korangi Creek, Karachi

# Allowed email pattern regex: std_*****@iobm.edu.pk or admin@iobm.edu.pk
EMAIL_REGEX = r"^(std_[a-zA-Z0-9_]+@iobm\.edu\.pk|admin@iobm\.edu\.pk)$"

# Admin-Controlled Fixed Carpool Rates (in Pakistani Rupees PKR)
DEFAULT_CARPOOL_BASE_PKR = 150.0
DEFAULT_CARPOOL_PER_KM_PKR = 35.0
DEFAULT_CARPOOL_MODE = "per_km" # 'per_km' or 'flat'
DEFAULT_CARPOOL_FLAT_PKR = 350.0

# Bike Pool Suggested Base Rates (Negotiable between rider & driver)
BIKE_BASE_PKR = 70.0
BIKE_PER_KM_PKR = 18.0

# Privacy & Speed
COARSE_ZONE_RADIUS_METERS = 350
GENDER_CONFIDENCE_THRESHOLD = 0.75
MAX_DETOUR_MINUTES = 20
SPEED_KM_PER_HOUR = 30.0 # Karachi transit speed
