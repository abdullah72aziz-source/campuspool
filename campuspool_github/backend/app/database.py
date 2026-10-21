import sqlite3
import math
from contextlib import contextmanager
from .config import (
    DB_PATH, SPEED_KM_PER_HOUR, DEFAULT_CARPOOL_BASE_PKR,
    DEFAULT_CARPOOL_PER_KM_PKR, DEFAULT_CARPOOL_MODE, DEFAULT_CARPOOL_FLAT_PKR
)

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (math.sin(d_lat / 2.0) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(d_lon / 2.0) ** 2)
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return r * c

def calculate_detour(orig_lat, orig_lng, dest_lat, dest_lng, pick_lat, pick_lng, drop_lat, drop_lng):
    direct_dist = haversine_distance(orig_lat, orig_lng, dest_lat, dest_lng)
    shared_dist = (haversine_distance(orig_lat, orig_lng, pick_lat, pick_lng) +
                   haversine_distance(pick_lat, pick_lng, drop_lat, drop_lng) +
                   haversine_distance(drop_lat, drop_lng, dest_lat, dest_lng))
    detour_km = max(0.0, shared_dist - direct_dist)
    detour_mins = (detour_km / SPEED_KM_PER_HOUR) * 60.0
    return round(detour_km, 2), round(detour_mins, 1)

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    conn.execute('PRAGMA journal_mode = WAL')
    return conn

@contextmanager
def get_db():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    with get_db() as conn:
        c = conn.cursor()
        
        # 1. Users
        c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            university_id TEXT UNIQUE NOT NULL,
            role TEXT NOT NULL DEFAULT 'rider',
            gender_on_record TEXT NOT NULL,
            verified_status TEXT NOT NULL DEFAULT 'pending',
            rating REAL NOT NULL DEFAULT 5.0,
            rating_count INTEGER NOT NULL DEFAULT 0,
            emergency_contact_name TEXT DEFAULT '',
            emergency_contact_phone TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')

        # Add profile_pic_url column if it doesn't exist (SQLite doesn't support IF NOT EXISTS for ALTER)
        try:
            c.execute("ALTER TABLE users ADD COLUMN profile_pic_url TEXT DEFAULT ''")
        except Exception:
            pass  # Column already exists

        # Add bio column if it doesn't exist
        try:
            c.execute("ALTER TABLE users ADD COLUMN bio TEXT DEFAULT ''")
        except Exception:
            pass  # Column already exists

        # 2. Vehicles with full feature details (AC/non-AC, Year, Model, Make, Color)
        c.execute('''
        CREATE TABLE IF NOT EXISTS vehicles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL,
            vehicle_type TEXT NOT NULL, -- car, bike
            make TEXT NOT NULL,         -- e.g. Toyota, Honda, Suzuki, Yamaha
            model TEXT NOT NULL,        -- e.g. Corolla, Alto, YBR 125, CD70
            year INTEGER NOT NULL,      -- e.g. 2022
            ac_type TEXT NOT NULL DEFAULT 'AC', -- 'AC' or 'Non-AC'
            color TEXT NOT NULL DEFAULT 'White',
            license_plate TEXT NOT NULL,
            seats_total INTEGER NOT NULL,
            is_verified INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE
        )''')

        # 3. Admin Settings (for Carpool Fixed Rates decided by Admin)
        c.execute('''
        CREATE TABLE IF NOT EXISTS admin_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )''')

        # Default settings if not already present
        c.execute("INSERT OR IGNORE INTO admin_settings (key, value) VALUES ('carpool_base_pkr', ?)", (str(DEFAULT_CARPOOL_BASE_PKR),))
        c.execute("INSERT OR IGNORE INTO admin_settings (key, value) VALUES ('carpool_per_km_pkr', ?)", (str(DEFAULT_CARPOOL_PER_KM_PKR),))
        c.execute("INSERT OR IGNORE INTO admin_settings (key, value) VALUES ('carpool_pricing_mode', ?)", (DEFAULT_CARPOOL_MODE,))
        c.execute("INSERT OR IGNORE INTO admin_settings (key, value) VALUES ('carpool_flat_pkr', ?)", (str(DEFAULT_CARPOOL_FLAT_PKR),))

        # 3b. App Settings (branding, logo, tagline)
        c.execute('''
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )''')

        # Seed app_settings defaults
        c.execute("INSERT OR IGNORE INTO app_settings (key, value) VALUES ('app_name', 'IoBM CampusPool')")
        c.execute("INSERT OR IGNORE INTO app_settings (key, value) VALUES ('app_logo_emoji', '🎓')")
        c.execute("INSERT OR IGNORE INTO app_settings (key, value) VALUES ('app_tagline', 'Institute of Business Management • Korangi Creek, Karachi')")
        c.execute("INSERT OR IGNORE INTO app_settings (key, value) VALUES ('app_pfp_url', '')")

        # 3c. Admin Locations (pickup/destination points with admin-set fares)
        c.execute('''
        CREATE TABLE IF NOT EXISTS admin_locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            lat REAL NOT NULL,
            lng REAL NOT NULL,
            zone TEXT NOT NULL DEFAULT 'pickup',
            ac_fare_pkr REAL NOT NULL DEFAULT 0.0,
            nonac_fare_pkr REAL NOT NULL DEFAULT 0.0,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')

        # 4. Rides
        c.execute('''
        CREATE TABLE IF NOT EXISTS rides (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            driver_id INTEGER NOT NULL,
            vehicle_id INTEGER NOT NULL,
            origin_name TEXT NOT NULL,
            origin_lat REAL NOT NULL,
            origin_lng REAL NOT NULL,
            dest_name TEXT NOT NULL,
            dest_lat REAL NOT NULL,
            dest_lng REAL NOT NULL,
            departure_time TEXT NOT NULL,
            seats_total INTEGER NOT NULL,
            seats_available INTEGER NOT NULL,
            ride_type TEXT NOT NULL DEFAULT 'car_pool', -- car_pool, bike_pool, women_only
            status TEXT NOT NULL DEFAULT 'scheduled',
            route_polyline TEXT DEFAULT '[]',
            fixed_fare_pkr REAL DEFAULT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (driver_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (vehicle_id) REFERENCES vehicles(id) ON DELETE CASCADE
        )''')

        # 5. Ride Requests
        c.execute('''
        CREATE TABLE IF NOT EXISTS ride_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ride_id INTEGER NOT NULL,
            rider_id INTEGER NOT NULL,
            pickup_name TEXT NOT NULL,
            pickup_lat REAL NOT NULL,
            pickup_lng REAL NOT NULL,
            drop_name TEXT NOT NULL,
            drop_lat REAL NOT NULL,
            drop_lng REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (ride_id) REFERENCES rides(id) ON DELETE CASCADE,
            FOREIGN KEY (rider_id) REFERENCES users(id) ON DELETE CASCADE
        )''')

        # 6. Fares (Carpool is Admin-fixed; Bike pool is negotiable)
        c.execute('''
        CREATE TABLE IF NOT EXISTS fares (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id INTEGER UNIQUE NOT NULL,
            ride_type TEXT NOT NULL,
            is_admin_fixed INTEGER NOT NULL DEFAULT 0, -- 1 for car_pool/women_only, 0 for bike_pool
            suggested_fare REAL NOT NULL,
            pitched_fare REAL DEFAULT NULL,
            pitched_by TEXT DEFAULT '',
            final_fare REAL DEFAULT NULL,
            status TEXT NOT NULL DEFAULT 'suggested', -- suggested, pitched, agreed
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (request_id) REFERENCES ride_requests(id) ON DELETE CASCADE
        )''')

        # 7. Trips
        c.execute('''
        CREATE TABLE IF NOT EXISTS trips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ride_id INTEGER NOT NULL,
            request_id INTEGER NOT NULL,
            driver_id INTEGER NOT NULL,
            rider_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'in_progress',
            current_lat REAL NOT NULL,
            current_lng REAL NOT NULL,
            start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            end_time TIMESTAMP DEFAULT NULL,
            route_polyline TEXT DEFAULT '[]',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (ride_id) REFERENCES rides(id) ON DELETE CASCADE,
            FOREIGN KEY (request_id) REFERENCES ride_requests(id) ON DELETE CASCADE
        )''')

        # 8. In-Ride Chat Messages
        c.execute('''
        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trip_id INTEGER NOT NULL,
            sender_id INTEGER NOT NULL,
            sender_name TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (trip_id) REFERENCES trips(id) ON DELETE CASCADE,
            FOREIGN KEY (sender_id) REFERENCES users(id) ON DELETE CASCADE
        )''')

        # 9. Ratings
        c.execute('''
        CREATE TABLE IF NOT EXISTS ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trip_id INTEGER NOT NULL,
            from_user_id INTEGER NOT NULL,
            to_user_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            score INTEGER NOT NULL,
            comment TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (trip_id) REFERENCES trips(id) ON DELETE CASCADE
        )''')

        # 10. Safety Events
        c.execute('''
        CREATE TABLE IF NOT EXISTS safety_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trip_id INTEGER DEFAULT NULL,
            user_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            lat REAL NOT NULL,
            lng REAL NOT NULL,
            details TEXT DEFAULT '',
            is_resolved INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )''')

        # 11. Verification Reviews
        c.execute('''
        CREATE TABLE IF NOT EXISTS verification_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            id_card_filename TEXT DEFAULT '',
            selfie_filename TEXT DEFAULT '',
            liveness_passed INTEGER NOT NULL DEFAULT 1,
            face_similarity REAL NOT NULL DEFAULT 0.0,
            gender_estimate TEXT NOT NULL,
            gender_confidence REAL NOT NULL DEFAULT 0.0,
            flag_reason TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            admin_decision TEXT DEFAULT '',
            reviewed_by TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )''')

        print("IoBM Karachi Database Initialized Successfully!")

