import json
import re
import uuid
import base64
from datetime import datetime
from .config import (
    EMAIL_REGEX, GENDER_CONFIDENCE_THRESHOLD, MAX_DETOUR_MINUTES,
    SPEED_KM_PER_HOUR, BIKE_BASE_PKR, BIKE_PER_KM_PKR, UPLOAD_DIR
)
from .database import get_db, haversine_distance, calculate_detour

class FareService:
    @staticmethod
    def get_admin_carpool_settings():
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT key, value FROM admin_settings")
            rows = dict(c.fetchall())
            return {
                'carpool_base_pkr': float(rows.get('carpool_base_pkr', 150.0)),
                'carpool_per_km_pkr': float(rows.get('carpool_per_km_pkr', 35.0)),
                'carpool_pricing_mode': rows.get('carpool_pricing_mode', 'per_km'),
                'carpool_flat_pkr': float(rows.get('carpool_flat_pkr', 350.0))
            }

    @staticmethod
    def calculate_fare(distance_km: float, vehicle_type: str, ride_type: str = 'car_pool', ac_type: str = 'AC', pickup_name: str = '') -> dict:
        # First try to find a location-based fare set by admin
        if pickup_name:
            with get_db() as conn:
                c = conn.cursor()
                c.execute('SELECT ac_fare_pkr, nonac_fare_pkr FROM admin_locations WHERE name = ? AND is_active = 1 LIMIT 1', (pickup_name,))
                loc = c.fetchone()
                if loc:
                    fare = loc['ac_fare_pkr'] if ac_type == 'AC' else loc['nonac_fare_pkr']
                    if fare > 0:
                        return {
                            'fare_pkr': fare,
                            'suggested_fare': fare,
                            'is_admin_fixed': True,
                            'min_allowed_fare': fare,
                            'max_allowed_fare': fare,
                            'mode_label': f"Admin Location Fare ({'AC' if ac_type == 'AC' else 'Non-AC'}) Rs. {fare:.0f}"
                        }

        # Fall back to existing formula logic
        settings = FareService.get_admin_carpool_settings()

        # 1. Carpool (Fixed by Admin - Non-negotiable)
        if vehicle_type == 'car' or ride_type in ['car_pool', 'women_only']:
            if settings['carpool_pricing_mode'] == 'flat':
                fare = round(settings['carpool_flat_pkr'], 2)
            else:
                fare = round(settings['carpool_base_pkr'] + (distance_km * settings['carpool_per_km_pkr']), 2)
            return {
                'fare_pkr': fare,
                'suggested_fare': fare,
                'is_admin_fixed': True,
                'min_allowed_fare': fare,
                'max_allowed_fare': fare,
                'mode_label': f"Admin Fixed Rate (Rs. {fare:.0f})"
            }

        # 2. Bike Pool (Negotiable between Rider & Driver)
        bike_sugg = round(BIKE_BASE_PKR + (distance_km * BIKE_PER_KM_PKR), 2)
        return {
            'fare_pkr': bike_sugg,
            'suggested_fare': bike_sugg,
            'is_admin_fixed': False,
            'min_allowed_fare': round(bike_sugg * 0.40, 2),
            'max_allowed_fare': round(bike_sugg * 2.50, 2),
            'mode_label': "Negotiable by Rider & Driver"
        }

    @staticmethod
    def validate_pitch(ride_type: str, pitched_fare: float, suggested_fare: float) -> tuple[bool, str]:
        if ride_type in ['car_pool', 'women_only']:
            return False, "Carpool rate is strictly fixed by Admin and cannot be negotiated."
        
        # Bike pool allows open negotiation between rider and driver
        if pitched_fare <= 0:
            return False, "Pitched fare must be greater than Rs. 0."
        return True, "Valid bike pool pitch."

class MatchingService:
    @staticmethod
    def is_valid_iobm_email(email: str) -> bool:
        email = email.strip().lower()
        return bool(re.match(EMAIL_REGEX, email))

    @staticmethod
    def search_rides(rider_id: int, pick_lat: float, pick_lng: float, drop_lat: float, drop_lng: float,
                     ride_type_filter: str = 'all', max_detour: float = MAX_DETOUR_MINUTES):
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT * FROM users WHERE id = ?", (rider_id,))
            rider = c.fetchone()
            if not rider:
                return []

            query = '''
            SELECT r.*, u.name as driver_name, u.gender_on_record as driver_gender,
                   u.verified_status as driver_verified, u.rating as driver_rating,
                   v.vehicle_type, v.make, v.model, v.year, v.ac_type, v.color, v.license_plate
            FROM rides r
            JOIN users u ON r.driver_id = u.id
            JOIN vehicles v ON r.vehicle_id = v.id
            WHERE r.status = 'scheduled' AND r.seats_available > 0
            '''
            c.execute(query)
            rides = c.fetchall()

        matched_results = []
        rider_gender = rider['gender_on_record']
        rider_verified = (rider['verified_status'] == 'verified')

        for r in rides:
            r_dict = dict(r)
            ride_type = r_dict['ride_type']
            driver_gender = r_dict['driver_gender']
            driver_verified = (r_dict['driver_verified'] == 'verified')

            # Hard Constraint: Women-Only Pool
            if ride_type == 'women_only' or ride_type_filter == 'women_only':
                if not (driver_gender == 'female' and driver_verified):
                    continue
                if not (rider_gender == 'female' and rider_verified):
                    continue

            # Ride Type Filter
            if ride_type_filter in ['car_pool', 'bike_pool'] and ride_type != ride_type_filter:
                continue

            # Detour Calculation across Karachi route
            detour_km, detour_mins = calculate_detour(
                r_dict['origin_lat'], r_dict['origin_lng'],
                r_dict['dest_lat'], r_dict['dest_lng'],
                pick_lat, pick_lng, drop_lat, drop_lng
            )

            if detour_mins > max_detour:
                continue

            rider_dist_km = round(haversine_distance(pick_lat, pick_lng, drop_lat, drop_lng), 2)
            fare_info = FareService.calculate_fare(rider_dist_km, r_dict['vehicle_type'], ride_type, ac_type=r_dict['ac_type'])

            # Score: detour penalty, rating bonus
            score = 100.0 - (detour_mins * 3.0) + (r_dict['driver_rating'] * 5.0)

            # Explanation string
            vehicle_summary = f"{r_dict['make']} {r_dict['model']} ({r_dict['year']}, {r_dict['ac_type']})"
            pricing_text = f"Rs. {fare_info['fare_pkr']:.0f} (Admin Fixed)" if fare_info['is_admin_fixed'] else f"Rs. {fare_info['fare_pkr']:.0f} (Negotiable)"

            explanations = [
                f"{detour_mins:.1f} min detour",
                vehicle_summary,
                f"{r_dict['driver_rating']:.1f}★ Driver ({r_dict['driver_name']})",
                pricing_text
            ]

            match_card = {
                'ride': r_dict,
                'detour_km': detour_km,
                'detour_mins': detour_mins,
                'rider_dist_km': rider_dist_km,
                'fare': fare_info,
                'ranking_score': round(score, 1),
                'explanation': ' • '.join(explanations)
            }
            matched_results.append(match_card)

        matched_results.sort(key=lambda x: x['ranking_score'], reverse=True)
        return matched_results

class VerificationService:
    @staticmethod
    def process_verification(user_id: int, id_card_b64: str, selfie_b64: str,
                             liveness_passed: bool, gender_estimate: str, gender_confidence: float):
        id_filename = f"id_{user_id}_{uuid.uuid4().hex[:8]}.jpg"
        selfie_filename = f"selfie_{user_id}_{uuid.uuid4().hex[:8]}.jpg"

        try:
            if ',' in id_card_b64:
                id_card_b64 = id_card_b64.split(',', 1)[1]
            if ',' in selfie_b64:
                selfie_b64 = selfie_b64.split(',', 1)[1]
            with open(UPLOAD_DIR / id_filename, 'wb') as f:
                f.write(base64.b64decode(id_card_b64))
            with open(UPLOAD_DIR / selfie_filename, 'wb') as f:
                f.write(base64.b64decode(selfie_b64))
        except Exception:
            pass

        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT * FROM users WHERE id = ?", (user_id,))
            user = c.fetchone()
            if not user:
                return {'status': 'error', 'message': 'User not found'}

            gender_on_record = user['gender_on_record']
            face_sim = 0.95 if liveness_passed else 0.40

            flag_reason = ""
            new_status = 'verified'

            if not liveness_passed:
                new_status = 'flagged_review'
                flag_reason = "Liveness check unconfirmed."
            elif gender_estimate == 'uncertain' or gender_confidence < GENDER_CONFIDENCE_THRESHOLD:
                new_status = 'flagged_review'
                flag_reason = f"Low gender confidence ({gender_confidence*100:.0f}%). Soft signal routed to admin."
            elif gender_estimate != gender_on_record:
                new_status = 'flagged_review'
                flag_reason = f"Soft gender check ({gender_estimate}) differs from record ({gender_on_record}). Routed to admin."

            c.execute('''
            INSERT INTO verification_reviews 
            (user_id, id_card_filename, selfie_filename, liveness_passed, face_similarity, 
             gender_estimate, gender_confidence, flag_reason, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, id_filename, selfie_filename, 1 if liveness_passed else 0,
                  face_sim, gender_estimate, gender_confidence, flag_reason,
                  'approved' if new_status == 'verified' else 'pending'))

            c.execute("UPDATE users SET verified_status = ? WHERE id = ?", (new_status, user_id))

        return {
            'status': new_status,
            'flag_reason': flag_reason,
            'face_similarity': face_sim,
            'gender_estimate': gender_estimate,
            'message': 'Account verified instantly' if new_status == 'verified' else 'Sent to Admin Review Queue'
        }

class SimulatorService:
    @staticmethod
    def generate_waypoints(lat1, lon1, lat2, lon2, steps=10):
        points = []
        for i in range(steps + 1):
            t = i / steps
            points.append([round(lat1 + (lat2 - lat1) * t, 6), round(lon1 + (lon2 - lon1) * t, 6)])
        return points

    @staticmethod
    def seed_data():
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT count(*) as count FROM users")
            if c.fetchone()['count'] > 0:
                return {"message": "IoBM Karachi data already present"}

            # 1. Admin
            c.execute('''
            INSERT INTO users (name, email, password_hash, university_id, role, gender_on_record, verified_status, emergency_contact_name, emergency_contact_phone)
            VALUES ('IoBM Safety Admin', 'admin@iobm.edu.pk', 'admin123', 'IOBM-ADM-01', 'admin', 'other', 'verified', 'Campus Security Hotline', '021-111-002-004')
            ''')

            # 2. Driver 1: Verified Female Driver (Car - Toyota Aqua Hybrid 2021 AC)
            c.execute('''
            INSERT INTO users (name, email, password_hash, university_id, role, gender_on_record, verified_status, rating, rating_count, emergency_contact_name, emergency_contact_phone)
            VALUES ('Amina Tariq', 'std_21098@iobm.edu.pk', 'pass123', 'std_21098', 'driver', 'female', 'verified', 4.9, 34, 'Father (Tariq)', '0300-1234567')
            ''')
            d1_id = c.lastrowid
            c.execute('''
            INSERT INTO vehicles (owner_id, vehicle_type, make, model, year, ac_type, color, license_plate, seats_total, is_verified)
            VALUES (?, 'car', 'Toyota', 'Aqua Hybrid', 2021, 'AC', 'Pearl White', 'BDN-492', 4, 1)
            ''', (d1_id,))
            v1_id = c.lastrowid

            # 3. Driver 2: Verified Male Driver (Bike - Yamaha YBR 125G 2023 Non-AC)
            c.execute('''
            INSERT INTO users (name, email, password_hash, university_id, role, gender_on_record, verified_status, rating, rating_count, emergency_contact_name, emergency_contact_phone)
            VALUES ('Bilal Ahmed', 'std_22045@iobm.edu.pk', 'pass123', 'std_22045', 'driver', 'male', 'verified', 4.8, 22, 'Brother (Usman)', '0333-7654321')
            ''')
            d2_id = c.lastrowid
            c.execute('''
            INSERT INTO vehicles (owner_id, vehicle_type, make, model, year, ac_type, color, license_plate, seats_total, is_verified)
            VALUES (?, 'bike', 'Yamaha', 'YBR 125G', 2023, 'Non-AC', 'Racing Blue', 'KHI-8891', 1, 1)
            ''', (d2_id,))
            v2_id = c.lastrowid

            # 4. Driver 3: Male Driver (Car - Honda Civic Oriel 2022 AC)
            c.execute('''
            INSERT INTO users (name, email, password_hash, university_id, role, gender_on_record, verified_status, rating, rating_count, emergency_contact_name, emergency_contact_phone)
            VALUES ('Zain Malik', 'std_20114@iobm.edu.pk', 'pass123', 'std_20114', 'driver', 'male', 'verified', 4.7, 18, 'Guardian', '0321-9988776')
            ''')
            d3_id = c.lastrowid
            c.execute('''
            INSERT INTO vehicles (owner_id, vehicle_type, make, model, year, ac_type, color, license_plate, seats_total, is_verified)
            VALUES (?, 'car', 'Honda', 'Civic Oriel', 2022, 'AC', 'Gun Metallic', 'AEN-102', 3, 1)
            ''', (d3_id,))
            v3_id = c.lastrowid

            # 5. Riders
            c.execute('''
            INSERT INTO users (name, email, password_hash, university_id, role, gender_on_record, verified_status, rating, rating_count, emergency_contact_name, emergency_contact_phone)
            VALUES ('Fatima Zahra', 'std_24011@iobm.edu.pk', 'pass123', 'std_24011', 'rider', 'female', 'verified', 5.0, 15, 'Mother', '0345-1122334')
            ''')
            r1_id = c.lastrowid

            c.execute('''
            INSERT INTO users (name, email, password_hash, university_id, role, gender_on_record, verified_status, rating, rating_count, emergency_contact_name, emergency_contact_phone)
            VALUES ('Hamza Ali', 'std_24012@iobm.edu.pk', 'pass123', 'std_24012', 'rider', 'male', 'verified', 4.9, 9, 'Father', '0312-3344556')
            ''')
            r2_id = c.lastrowid

            # 6. Flagged user for admin queue demonstration
            c.execute('''
            INSERT INTO users (name, email, password_hash, university_id, role, gender_on_record, verified_status, rating, rating_count, emergency_contact_name, emergency_contact_phone)
            VALUES ('Sara Khan', 'std_23089@iobm.edu.pk', 'pass123', 'std_23089', 'rider', 'female', 'flagged_review', 5.0, 0, 'Guardian', '0301-4455667')
            ''')
            flagged_id = c.lastrowid
            c.execute('''
            INSERT INTO verification_reviews (user_id, id_card_filename, selfie_filename, liveness_passed, face_similarity, gender_estimate, gender_confidence, flag_reason, status)
            VALUES (?, 'iobm_card_sample.jpg', 'selfie_sample.jpg', 1, 0.88, 'uncertain', 0.63, 'Soft gender check confidence 63% below 75% threshold', 'pending')
            ''', (flagged_id,))

            # 7. Scheduled Karachi Campus Rides to IoBM Korangi Creek (24.8270, 67.1142)
            # Route 1: Clifton Teen Talwar (24.8238, 67.0326) ➔ IoBM
            c.execute('''
            INSERT INTO rides (driver_id, vehicle_id, origin_name, origin_lat, origin_lng, dest_name, dest_lat, dest_lng, departure_time, seats_total, seats_available, ride_type, status, route_polyline, fixed_fare_pkr)
            VALUES (?, ?, 'Clifton Teen Talwar', 24.8238, 67.0326, 'IoBM Main Campus Korangi Creek', 24.8270, 67.1142, '08:15', 3, 3, 'women_only', 'scheduled', ?, 320.0)
            ''', (d1_id, v1_id, json.dumps(SimulatorService.generate_waypoints(24.8238, 67.0326, 24.8270, 67.1142, 12))))

            # Route 2: DHA Phase 5 / 6 Khayaban-e-Shahbaz (24.8140, 67.0680) ➔ IoBM
            c.execute('''
            INSERT INTO rides (driver_id, vehicle_id, origin_name, origin_lat, origin_lng, dest_name, dest_lat, dest_lng, departure_time, seats_total, seats_available, ride_type, status, route_polyline, fixed_fare_pkr)
            VALUES (?, ?, 'DHA Phase 5 Khayaban-e-Shahbaz', 24.8140, 67.0680, 'IoBM Engineering Gate', 24.8270, 67.1142, '08:30', 1, 1, 'bike_pool', 'scheduled', ?, 120.0)
            ''', (d2_id, v2_id, json.dumps(SimulatorService.generate_waypoints(24.8140, 67.0680, 24.8270, 67.1142, 12))))

            # Route 3: Gulshan-e-Iqbal Disco Bakery (24.9180, 67.0970) ➔ IoBM
            c.execute('''
            INSERT INTO rides (driver_id, vehicle_id, origin_name, origin_lat, origin_lng, dest_name, dest_lat, dest_lng, departure_time, seats_total, seats_available, ride_type, status, route_polyline, fixed_fare_pkr)
            VALUES (?, ?, 'Gulshan-e-Iqbal Disco Bakery', 24.9180, 67.0970, 'IoBM Business School Gate', 24.8270, 67.1142, '08:00', 3, 3, 'car_pool', 'scheduled', ?, 450.0)
            ''', (d3_id, v3_id, json.dumps(SimulatorService.generate_waypoints(24.9180, 67.0970, 24.8270, 67.1142, 12))))

            # 8. Seed admin_locations (only if none exist)
            c.execute('SELECT count(*) as cnt FROM admin_locations')
            if c.fetchone()['cnt'] == 0:
                locations = [
                    ('Clifton Teen Talwar', 24.8238, 67.0326, 'pickup', 350.0, 250.0),
                    ('DHA Phase 5 Khayaban-e-Shahbaz', 24.8140, 67.0680, 'pickup', 300.0, 200.0),
                    ('Gulshan-e-Iqbal Block 13-D', 24.9180, 67.0970, 'pickup', 400.0, 280.0),
                    ('PECHS Tariq Road', 24.8690, 67.0630, 'pickup', 320.0, 220.0),
                    ('North Nazimabad Five Star Chowrangi', 24.9350, 67.0420, 'pickup', 420.0, 300.0),
                    ('Malir Cantt Gate 1', 24.8870, 67.1850, 'pickup', 280.0, 180.0),
                    ('Korangi Industrial Area', 24.8380, 67.1220, 'pickup', 200.0, 150.0),
                    ('IoBM Main Campus Korangi Creek', 24.8270, 67.1142, 'destination', 0.0, 0.0),
                    ('IoBM Engineering Block Gate', 24.8285, 67.1160, 'destination', 0.0, 0.0),
                    ('IoBM Business School Gate', 24.8255, 67.1125, 'destination', 0.0, 0.0),
                ]
                for loc in locations:
                    c.execute('INSERT INTO admin_locations (name, lat, lng, zone, ac_fare_pkr, nonac_fare_pkr) VALUES (?,?,?,?,?,?)', loc)

        return {"message": "IoBM Karachi demo community, verified vehicles, and rides seeded successfully!"}
