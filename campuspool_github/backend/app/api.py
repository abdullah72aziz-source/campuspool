import json
from datetime import datetime
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List

from .database import get_db, haversine_distance
from .services import MatchingService, FareService, VerificationService, SimulatorService
from .config import COARSE_ZONE_RADIUS_METERS

api_router = APIRouter(prefix='/api')

# --- Schemas ---
class SignupRequest(BaseModel):
    name: str
    email: str
    password: str
    university_id: str
    role: str = 'rider'
    gender_on_record: str
    emergency_contact_name: str = ''
    emergency_contact_phone: str = ''

class LoginRequest(BaseModel):
    email: str
    password: str

class AdminFareSettingsUpdate(BaseModel):
    carpool_base_pkr: float
    carpool_per_km_pkr: float
    carpool_pricing_mode: str = 'per_km' # 'per_km' or 'flat'
    carpool_flat_pkr: float = 350.0

class AppSettingsUpdate(BaseModel):
    app_name: str
    app_logo_emoji: str = '🎓'
    app_tagline: str
    app_pfp_url: str = ''

class AdminLocationCreate(BaseModel):
    name: str
    lat: float
    lng: float
    zone: str = 'pickup'
    ac_fare_pkr: float
    nonac_fare_pkr: float

class UpdateProfileRequest(BaseModel):
    user_id: int
    name: str = ''
    profile_pic_url: str = ''
    bio: str = ''

class VehicleCreate(BaseModel):
    owner_id: int
    vehicle_type: str # car, bike
    make: str         # Toyota, Honda, Suzuki, Yamaha
    model: str        # Corolla, Alto, YBR 125, CD70
    year: int         # 2022
    ac_type: str = 'AC' # 'AC' or 'Non-AC'
    color: str = 'White'
    license_plate: str
    seats_total: int

class RideCreate(BaseModel):
    driver_id: int
    vehicle_id: int
    origin_name: str
    origin_lat: float
    origin_lng: float
    dest_name: str
    dest_lat: float
    dest_lng: float
    departure_time: str
    seats_total: int
    ride_type: str = 'car_pool'

class MatchSearchRequest(BaseModel):
    rider_id: int
    pick_lat: float
    pick_lng: float
    drop_lat: float
    drop_lng: float
    ride_type_filter: str = 'all'

class RideRequestCreate(BaseModel):
    ride_id: int
    rider_id: int
    pickup_name: str
    pickup_lat: float
    pickup_lng: float
    drop_name: str
    drop_lat: float
    drop_lng: float

class RequestRespond(BaseModel):
    request_id: int
    action: str

class FarePitchRequest(BaseModel):
    request_id: int
    pitched_fare: float
    pitched_by: str

class FareRespondRequest(BaseModel):
    request_id: int
    action: str

class ChatMessageCreate(BaseModel):
    sender_id: int
    sender_name: str
    message: str

class VerificationRequest(BaseModel):
    user_id: int
    id_card_b64: str
    selfie_b64: str
    liveness_passed: bool
    gender_estimate: str
    gender_confidence: float

class AdminReviewRequest(BaseModel):
    review_id: int
    decision: str
    admin_notes: str = ''

class SOSRequest(BaseModel):
    user_id: int
    trip_id: Optional[int] = None
    lat: float
    lng: float
    details: str = 'Emergency assistance requested on IoBM route'

class RatingCreate(BaseModel):
    trip_id: int
    from_user_id: int
    to_user_id: int
    role: str
    score: int
    comment: str = ''

# --- Auth Endpoints ---
@api_router.post('/auth/signup')
def signup(req: SignupRequest):
    if not MatchingService.is_valid_iobm_email(req.email):
        raise HTTPException(
            status_code=400,
            detail="Access restricted to IoBM students only. Email must match pattern: std_*****@iobm.edu.pk (e.g. std_24011@iobm.edu.pk)"
        )
    
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT id FROM users WHERE email = ?', (req.email.lower().strip(),))
        if c.fetchone():
            raise HTTPException(status_code=400, detail='This IoBM student email is already registered.')

        c.execute('''
        INSERT INTO users (name, email, password_hash, university_id, role, gender_on_record,
                          emergency_contact_name, emergency_contact_phone)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (req.name, req.email.lower().strip(), req.password, req.university_id, req.role,
              req.gender_on_record, req.emergency_contact_name, req.emergency_contact_phone))
        user_id = c.lastrowid
        
        c.execute('SELECT * FROM users WHERE id = ?', (user_id,))
        user = dict(c.fetchone())
        del user['password_hash']
        return {'status': 'success', 'user': user}

@api_router.post('/auth/login')
def login(req: LoginRequest):
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM users WHERE email = ? AND password_hash = ?', (req.email.lower().strip(), req.password))
        user = c.fetchone()
        if not user:
            raise HTTPException(status_code=401, detail='Invalid IoBM email or password.')
        u_dict = dict(user)
        del u_dict['password_hash']
        return {'status': 'success', 'user': u_dict}

@api_router.get('/auth/me/{user_id}')
def get_user_profile(user_id: int):
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM users WHERE id = ?', (user_id,))
        user = c.fetchone()
        if not user:
            raise HTTPException(status_code=404, detail='User not found')
        u_dict = dict(user)
        del u_dict['password_hash']
        return u_dict

@api_router.post('/auth/update-profile')
def update_profile(req: UpdateProfileRequest):
    with get_db() as conn:
        c = conn.cursor()
        updates = []
        params = []
        if req.name:
            updates.append('name = ?')
            params.append(req.name)
        if req.profile_pic_url is not None:
            updates.append('profile_pic_url = ?')
            params.append(req.profile_pic_url)
        if req.bio is not None:
            updates.append('bio = ?')
            params.append(req.bio)
        if updates:
            params.append(req.user_id)
            c.execute(f'UPDATE users SET {", ".join(updates)} WHERE id = ?', params)
    return {'status': 'success'}

@api_router.get('/users')
def list_demo_users():
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT id, name, email, role, gender_on_record, verified_status, rating FROM users')
        return [dict(row) for row in c.fetchall()]

# --- Admin Carpool Fare Control ---
@api_router.get('/admin/fare-settings')
def get_admin_fare_settings():
    return FareService.get_admin_carpool_settings()

@api_router.post('/admin/fare-settings')
def update_admin_fare_settings(req: AdminFareSettingsUpdate):
    with get_db() as conn:
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO admin_settings (key, value) VALUES ('carpool_base_pkr', ?)", (str(req.carpool_base_pkr),))
        c.execute("INSERT OR REPLACE INTO admin_settings (key, value) VALUES ('carpool_per_km_pkr', ?)", (str(req.carpool_per_km_pkr),))
        c.execute("INSERT OR REPLACE INTO admin_settings (key, value) VALUES ('carpool_pricing_mode', ?)", (req.carpool_pricing_mode,))
        c.execute("INSERT OR REPLACE INTO admin_settings (key, value) VALUES ('carpool_flat_pkr', ?)", (str(req.carpool_flat_pkr),))
    return {'status': 'success', 'message': 'Admin fixed Carpool rates updated successfully.'}

# --- Admin App Settings ---
@api_router.get('/admin/app-settings')
def get_app_settings():
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT key, value FROM app_settings')
        return dict(c.fetchall())

@api_router.post('/admin/app-settings')
def update_app_settings(req: AppSettingsUpdate):
    with get_db() as conn:
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES ('app_name', ?)", (req.app_name,))
        c.execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES ('app_logo_emoji', ?)", (req.app_logo_emoji,))
        c.execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES ('app_tagline', ?)", (req.app_tagline,))
        c.execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES ('app_pfp_url', ?)", (req.app_pfp_url,))
    return {'status': 'success', 'message': 'App settings updated successfully.'}

# --- Admin Locations ---
@api_router.get('/admin/locations')
def list_admin_locations():
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM admin_locations WHERE is_active = 1 ORDER BY zone, name')
        return [dict(r) for r in c.fetchall()]

@api_router.post('/admin/locations')
def create_admin_location(req: AdminLocationCreate):
    with get_db() as conn:
        c = conn.cursor()
        c.execute('INSERT INTO admin_locations (name, lat, lng, zone, ac_fare_pkr, nonac_fare_pkr) VALUES (?,?,?,?,?,?)',
                  (req.name, req.lat, req.lng, req.zone, req.ac_fare_pkr, req.nonac_fare_pkr))
        return {'status': 'success', 'id': c.lastrowid}

@api_router.delete('/admin/locations/{loc_id}')
def delete_admin_location(loc_id: int):
    with get_db() as conn:
        c = conn.cursor()
        c.execute('UPDATE admin_locations SET is_active = 0 WHERE id = ?', (loc_id,))
    return {'status': 'deleted'}

@api_router.put('/admin/locations/{loc_id}')
def update_admin_location(loc_id: int, req: AdminLocationCreate):
    with get_db() as conn:
        c = conn.cursor()
        c.execute('UPDATE admin_locations SET name=?, lat=?, lng=?, zone=?, ac_fare_pkr=?, nonac_fare_pkr=? WHERE id=?',
                  (req.name, req.lat, req.lng, req.zone, req.ac_fare_pkr, req.nonac_fare_pkr, loc_id))
    return {'status': 'updated'}

@api_router.get('/vehicles/{owner_id}')
def get_vehicles(owner_id: int):
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM vehicles WHERE owner_id = ?', (owner_id,))
        return [dict(r) for r in c.fetchall()]

@api_router.post('/vehicles')
def add_vehicle(req: VehicleCreate):
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''
        INSERT INTO vehicles (owner_id, vehicle_type, make, model, year, ac_type, color, license_plate, seats_total)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (req.owner_id, req.vehicle_type, req.make, req.model, req.year, req.ac_type, req.color, req.license_plate, req.seats_total))
        return {'status': 'success', 'id': c.lastrowid}

# --- Rides (Driver) ---
@api_router.post('/rides')
def post_ride(req: RideCreate):
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM users WHERE id = ?', (req.driver_id,))
        driver = c.fetchone()
        if not driver:
            raise HTTPException(status_code=404, detail='Driver not found')

        if req.ride_type == 'women_only':
            if driver['gender_on_record'] != 'female' or driver['verified_status'] != 'verified':
                raise HTTPException(status_code=403, detail='Only verified female drivers can post women-only campus pools')

        # Fetch vehicle to get ac_type
        c.execute('SELECT * FROM vehicles WHERE id = ?', (req.vehicle_id,))
        vehicle = c.fetchone()
        ac_type = vehicle['ac_type'] if vehicle else 'AC'

        waypoints = SimulatorService.generate_waypoints(req.origin_lat, req.origin_lng, req.dest_lat, req.dest_lng, 12)
        dist_km = haversine_distance(req.origin_lat, req.origin_lng, req.dest_lat, req.dest_lng)
        fare_calc = FareService.calculate_fare(
            dist_km,
            'car' if req.ride_type in ['car_pool', 'women_only'] else 'bike',
            req.ride_type,
            ac_type=ac_type,
            pickup_name=req.origin_name
        )

        c.execute('''
        INSERT INTO rides (driver_id, vehicle_id, origin_name, origin_lat, origin_lng, dest_name, dest_lat, dest_lng,
                          departure_time, seats_total, seats_available, ride_type, status, route_polyline, fixed_fare_pkr)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'scheduled', ?, ?)
        ''', (req.driver_id, req.vehicle_id, req.origin_name, req.origin_lat, req.origin_lng,
              req.dest_name, req.dest_lat, req.dest_lng, req.departure_time, req.seats_total,
              req.seats_total, req.ride_type, json.dumps(waypoints), fare_calc['fare_pkr']))
        return {'status': 'success', 'ride_id': c.lastrowid}

@api_router.get('/rides')
def list_active_rides():
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''
        SELECT r.*, u.name as driver_name, u.rating as driver_rating,
               v.make, v.model, v.year, v.ac_type, v.color, v.license_plate, v.vehicle_type
        FROM rides r
        JOIN users u ON r.driver_id = u.id
        JOIN vehicles v ON r.vehicle_id = v.id
        WHERE r.status = 'scheduled'
        ORDER BY r.id DESC
        ''')
        return [dict(r) for r in c.fetchall()]

@api_router.get('/rides/driver/{driver_id}')
def get_driver_dashboard(driver_id: int):
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''
        SELECT r.*, v.make, v.model, v.year, v.ac_type, v.color, v.license_plate, v.vehicle_type
        FROM rides r
        JOIN vehicles v ON r.vehicle_id = v.id
        WHERE r.driver_id = ?
        ORDER BY r.id DESC
        ''', (driver_id,))
        rides = [dict(r) for r in c.fetchall()]

        ride_ids = [r['id'] for r in rides]
        requests = []
        if ride_ids:
            placeholders = ','.join('?' for _ in ride_ids)
            c.execute(f'''
            SELECT req.*, u.name as rider_name, u.rating as rider_rating, u.gender_on_record as rider_gender,
                   f.suggested_fare, f.pitched_fare, f.pitched_by, f.final_fare, f.status as fare_status,
                   f.is_admin_fixed, f.ride_type
            FROM ride_requests req
            JOIN users u ON req.rider_id = u.id
            LEFT JOIN fares f ON f.request_id = req.id
            WHERE req.ride_id IN ({placeholders})
            ORDER BY req.id DESC
            ''', ride_ids)
            requests = [dict(row) for row in c.fetchall()]

        return {'rides': rides, 'requests': requests}

# --- Ride Passengers ---
@api_router.get('/rides/{ride_id}/passengers')
def get_ride_passengers(ride_id: int):
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''
        SELECT u.name, u.gender_on_record, u.rating
        FROM ride_requests req
        JOIN users u ON req.rider_id = u.id
        WHERE req.ride_id = ? AND req.status = 'accepted'
        ''', (ride_id,))
        passengers = [dict(r) for r in c.fetchall()]
        male = sum(1 for p in passengers if p['gender_on_record'] == 'male')
        female = sum(1 for p in passengers if p['gender_on_record'] == 'female')
        other = len(passengers) - male - female
        return {'male': male, 'female': female, 'other': other, 'total': len(passengers), 'passengers': passengers}

# --- Matching Search (Rider) ---
@api_router.post('/matching/search')
def search_matching_rides(req: MatchSearchRequest):
    matches = MatchingService.search_rides(
        rider_id=req.rider_id,
        pick_lat=req.pick_lat,
        pick_lng=req.pick_lng,
        drop_lat=req.drop_lat,
        drop_lng=req.drop_lng,
        ride_type_filter=req.ride_type_filter
    )
    return {'matches': matches, 'count': len(matches)}

# --- Booking & Ride Requests ---
@api_router.post('/requests')
def create_ride_request(req: RideRequestCreate):
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM users WHERE id = ?', (req.rider_id,))
        rider = c.fetchone()
        c.execute('SELECT r.*, v.vehicle_type, v.ac_type FROM rides r JOIN vehicles v ON r.vehicle_id = v.id WHERE r.id = ?', (req.ride_id,))
        ride = c.fetchone()
        if not rider or not ride:
            raise HTTPException(status_code=404, detail='Rider or Ride not found')

        if ride['ride_type'] == 'women_only':
            if rider['gender_on_record'] != 'female' or rider['verified_status'] != 'verified':
                raise HTTPException(status_code=403, detail='Verified Women-Only Pool. Both driver and all riders must be verified female.')

        if ride['seats_available'] <= 0:
            raise HTTPException(status_code=400, detail='No seats available on this ride.')

        c.execute('''
        INSERT INTO ride_requests (ride_id, rider_id, pickup_name, pickup_lat, pickup_lng, drop_name, drop_lat, drop_lng, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')
        ''', (req.ride_id, req.rider_id, req.pickup_name, req.pickup_lat, req.pickup_lng, req.drop_name, req.drop_lat, req.drop_lng))
        request_id = c.lastrowid

        dist = round(haversine_distance(req.pickup_lat, req.pickup_lng, req.drop_lat, req.drop_lng), 2)
        fare_data = FareService.calculate_fare(
            dist,
            ride['vehicle_type'],
            ride['ride_type'],
            ac_type=ride['ac_type'],
            pickup_name=req.pickup_name
        )

        c.execute('''
        INSERT INTO fares (request_id, ride_type, is_admin_fixed, suggested_fare, final_fare, status)
        VALUES (?, ?, ?, ?, ?, 'suggested')
        ''', (request_id, ride['ride_type'], 1 if fare_data['is_admin_fixed'] else 0,
              fare_data['fare_pkr'], fare_data['fare_pkr'] if fare_data['is_admin_fixed'] else None))

        return {
            'status': 'success',
            'request_id': request_id,
            'fare': fare_data
        }

@api_router.get('/requests/rider/{rider_id}')
def get_rider_requests(rider_id: int):
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''
        SELECT req.*, r.origin_name, r.dest_name, r.departure_time, r.ride_type,
               u.name as driver_name, u.rating as driver_rating,
               f.suggested_fare, f.pitched_fare, f.pitched_by, f.final_fare, f.status as fare_status,
               f.is_admin_fixed,
               t.id as active_trip_id
        FROM ride_requests req
        JOIN rides r ON req.ride_id = r.id
        JOIN users u ON r.driver_id = u.id
        LEFT JOIN fares f ON f.request_id = req.id
        LEFT JOIN trips t ON t.request_id = req.id AND t.status = 'in_progress'
        WHERE req.rider_id = ?
        ORDER BY req.id DESC
        ''', (rider_id,))
        return [dict(row) for row in c.fetchall()]

@api_router.post('/requests/respond')
def respond_to_request(req: RequestRespond):
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM ride_requests WHERE id = ?', (req.request_id,))
        r = c.fetchone()
        if not r:
            raise HTTPException(status_code=404, detail='Request not found')

        new_status = 'accepted' if req.action == 'accept' else 'declined'
        c.execute('UPDATE ride_requests SET status = ? WHERE id = ?', (new_status, req.request_id))

        if new_status == 'accepted':
            c.execute('UPDATE rides SET seats_available = MAX(0, seats_available - 1) WHERE id = ?', (r['ride_id'],))
            c.execute('SELECT * FROM rides WHERE id = ?', (r['ride_id'],))
            ride = c.fetchone()
            
            c.execute('SELECT * FROM fares WHERE request_id = ?', (req.request_id,))
            fare = c.fetchone()
            final_amt = fare['pitched_fare'] if (fare and fare['pitched_fare'] and fare['status'] == 'agreed') else fare['suggested_fare']
            c.execute('UPDATE fares SET final_fare = ?, status = "agreed" WHERE request_id = ?', (final_amt, req.request_id))

            c.execute('''
            INSERT INTO trips (ride_id, request_id, driver_id, rider_id, status, current_lat, current_lng, route_polyline)
            VALUES (?, ?, ?, ?, 'in_progress', ?, ?, ?)
            ''', (r['ride_id'], req.request_id, ride['driver_id'], r['rider_id'],
                  ride['origin_lat'], ride['origin_lng'], ride['route_polyline']))
            trip_id = c.lastrowid
            return {'status': 'accepted', 'trip_id': trip_id}
        else:
            return {'status': 'declined'}

# --- Fare Pitching (Strictly Bike Pools Only) ---
@api_router.post('/fares/pitch')
def pitch_fare(req: FarePitchRequest):
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT f.*, r.ride_type FROM fares f JOIN ride_requests req ON f.request_id = req.id JOIN rides r ON req.ride_id = r.id WHERE f.request_id = ?', (req.request_id,))
        fare = c.fetchone()
        if not fare:
            raise HTTPException(status_code=404, detail='Fare record not found')

        is_valid, msg = FareService.validate_pitch(fare['ride_type'], req.pitched_fare, fare['suggested_fare'])
        if not is_valid:
            raise HTTPException(status_code=400, detail=msg)

        c.execute('''
        UPDATE fares 
        SET pitched_fare = ?, pitched_by = ?, status = 'pitched'
        WHERE request_id = ?
        ''', (round(req.pitched_fare, 2), req.pitched_by, req.request_id))
        return {'status': 'success', 'message': f'Bike fare pitch of Rs. {req.pitched_fare:.0f} sent to other party.'}

@api_router.post('/fares/respond')
def respond_pitch(req: FareRespondRequest):
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM fares WHERE request_id = ?', (req.request_id,))
        fare = c.fetchone()
        if not fare or not fare['pitched_fare']:
            raise HTTPException(status_code=404, detail='No active pitched fare')

        if req.action == 'accept':
            c.execute('UPDATE fares SET final_fare = pitched_fare, status = "agreed" WHERE request_id = ?', (req.request_id,))
            return {'status': 'success', 'message': f'Pitched bike fare of Rs. {fare["pitched_fare"]:.0f} accepted.'}
        else:
            c.execute('UPDATE fares SET status = "rejected" WHERE request_id = ?', (req.request_id,))
            return {'status': 'success', 'message': 'Pitched bike fare declined.'}

# --- Live Trip Tracking ---
@api_router.get('/trips/{trip_id}')
def get_trip_details(trip_id: int):
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''
        SELECT t.*, r.origin_name, r.dest_name, r.ride_type,
               u_d.name as driver_name, u_d.rating as driver_rating,
               u_r.name as rider_name, u_r.rating as rider_rating,
               v.make, v.model, v.year, v.ac_type, v.color, v.license_plate,
               req.pickup_lat, req.pickup_lng, req.pickup_name,
               req.drop_lat, req.drop_lng, req.drop_name,
               f.final_fare, f.suggested_fare, f.is_admin_fixed
        FROM trips t
        JOIN rides r ON t.ride_id = r.id
        JOIN vehicles v ON r.vehicle_id = v.id
        JOIN users u_d ON t.driver_id = u_d.id
        JOIN users u_r ON t.rider_id = u_r.id
        JOIN ride_requests req ON t.request_id = req.id
        LEFT JOIN fares f ON f.request_id = req.id
        WHERE t.id = ?
        ''', (trip_id,))
        trip = c.fetchone()
        if not trip:
            raise HTTPException(status_code=404, detail='Trip not found')
        
        t_dict = dict(trip)
        t_dict['route_waypoints'] = json.loads(t_dict['route_polyline'])
        t_dict['coarse_zone_radius_meters'] = COARSE_ZONE_RADIUS_METERS
        return t_dict

@api_router.post('/trips/{trip_id}/location')
def update_trip_location(trip_id: int, lat: float, lng: float):
    with get_db() as conn:
        c = conn.cursor()
        c.execute('UPDATE trips SET current_lat = ?, current_lng = ? WHERE id = ?', (lat, lng, trip_id))
        return {'status': 'success', 'lat': lat, 'lng': lng}

@api_router.post('/trips/{trip_id}/complete')
def complete_trip(trip_id: int):
    with get_db() as conn:
        c = conn.cursor()
        now_str = datetime.now().isoformat()
        c.execute('UPDATE trips SET status = "completed", end_time = ? WHERE id = ?', (now_str, trip_id))
        c.execute('SELECT request_id FROM trips WHERE id = ?', (trip_id,))
        t = c.fetchone()
        if t:
            c.execute('UPDATE ride_requests SET status = "completed" WHERE id = ?', (t['request_id'],))
        return {'status': 'success', 'message': 'Trip marked as completed'}

@api_router.get('/trips/active/{user_id}')
def get_user_active_trip(user_id: int):
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''
        SELECT id FROM trips 
        WHERE (driver_id = ? OR rider_id = ?) AND status = 'in_progress'
        ORDER BY id DESC LIMIT 1
        ''', (user_id, user_id))
        row = c.fetchone()
        return {'trip_id': row['id'] if row else None}

# --- In-Ride Live Chat (Between Rider and Driver) ---
@api_router.get('/chat/{trip_id}')
def get_chat_messages(trip_id: int):
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''
        SELECT * FROM chat_messages 
        WHERE trip_id = ? 
        ORDER BY id ASC
        ''', (trip_id,))
        return [dict(r) for r in c.fetchall()]

@api_router.post('/chat/{trip_id}')
def send_chat_message(trip_id: int, req: ChatMessageCreate):
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''
        INSERT INTO chat_messages (trip_id, sender_id, sender_name, message)
        VALUES (?, ?, ?, ?)
        ''', (trip_id, req.sender_id, req.sender_name, req.message))
        msg_id = c.lastrowid
        return {'status': 'success', 'message_id': msg_id, 'timestamp': datetime.now().strftime('%H:%M')}

# --- SOS & Safety Events ---
@api_router.post('/safety/sos')
def trigger_sos(req: SOSRequest):
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM users WHERE id = ?', (req.user_id,))
        user = c.fetchone()
        if not user:
            raise HTTPException(status_code=404, detail='User not found')

        c.execute('''
        INSERT INTO safety_events (trip_id, user_id, event_type, lat, lng, details, is_resolved)
        VALUES (?, ?, 'sos_triggered', ?, ?, ?, 0)
        ''', (req.trip_id, req.user_id, req.lat, req.lng, req.details))
        event_id = c.lastrowid

        return {
            'status': 'alert_dispatched',
            'event_id': event_id,
            'message': f"Emergency alert broadcast to IoBM Campus Security & Emergency Contact: {user['emergency_contact_name']} ({user['emergency_contact_phone']})",
            'emergency_contact': {
                'name': user['emergency_contact_name'],
                'phone': user['emergency_contact_phone']
            }
        }

@api_router.get('/safety/alerts')
def list_safety_alerts():
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''
        SELECT se.*, u.name as user_name, u.university_id, u.emergency_contact_name, u.emergency_contact_phone
        FROM safety_events se
        JOIN users u ON se.user_id = u.id
        WHERE se.is_resolved = 0
        ORDER BY se.id DESC
        ''')
        return [dict(r) for r in c.fetchall()]

@api_router.post('/safety/resolve/{event_id}')
def resolve_safety_alert(event_id: int):
    with get_db() as conn:
        c = conn.cursor()
        c.execute('UPDATE safety_events SET is_resolved = 1 WHERE id = ?', (event_id,))
        return {'status': 'resolved'}

# --- Verification & Soft Gender Signal ---
@api_router.post('/verification/submit')
def submit_verification(req: VerificationRequest):
    return VerificationService.process_verification(
        user_id=req.user_id,
        id_card_b64=req.id_card_b64,
        selfie_b64=req.selfie_b64,
        liveness_passed=req.liveness_passed,
        gender_estimate=req.gender_estimate,
        gender_confidence=req.gender_confidence
    )

@api_router.get('/admin/queue')
def get_admin_verification_queue():
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''
        SELECT vr.*, u.name, u.email, u.university_id, u.gender_on_record, u.role
        FROM verification_reviews vr
        JOIN users u ON vr.user_id = u.id
        WHERE vr.status = 'pending'
        ORDER BY vr.id DESC
        ''')
        return [dict(r) for r in c.fetchall()]

@api_router.post('/admin/review')
def process_admin_review(req: AdminReviewRequest):
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM verification_reviews WHERE id = ?', (req.review_id,))
        rev = c.fetchone()
        if not rev:
            raise HTTPException(status_code=404, detail='Review record not found')

        new_status = 'approved' if req.decision == 'approved' else 'rejected'
        user_status = 'verified' if req.decision == 'approved' else 'rejected'

        c.execute('''
        UPDATE verification_reviews 
        SET status = ?, admin_decision = ?, reviewed_by = 'IoBM Safety Admin'
        WHERE id = ?
        ''', (new_status, req.admin_notes or req.decision, req.review_id))

        c.execute('UPDATE users SET verified_status = ? WHERE id = ?', (user_status, rev['user_id']))
        return {'status': 'success', 'user_verified_status': user_status}

@api_router.get('/admin/metrics')
def get_admin_metrics():
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT COUNT(*) as total_users FROM users')
        tot_users = c.fetchone()['total_users']

        c.execute('SELECT COUNT(*) as verified_users FROM users WHERE verified_status = "verified"')
        ver_users = c.fetchone()['verified_users']

        c.execute('SELECT COUNT(*) as flagged_count FROM users WHERE verified_status = "flagged_review"')
        flagged = c.fetchone()['flagged_count']

        c.execute('SELECT COUNT(*) as active_rides FROM rides WHERE status = "scheduled"')
        act_rides = c.fetchone()['active_rides']

        c.execute('SELECT COUNT(*) as completed_trips FROM trips WHERE status = "completed"')
        comp_trips = c.fetchone()['completed_trips']

        c.execute('SELECT COUNT(*) as sos_active FROM safety_events WHERE is_resolved = 0')
        sos_count = c.fetchone()['sos_active']

        c.execute('SELECT gender_on_record, COUNT(*) as count FROM users GROUP BY gender_on_record')
        gender_dist = {r['gender_on_record']: r['count'] for r in c.fetchall()}

        c.execute('SELECT ride_type, COUNT(*) as count FROM rides GROUP BY ride_type')
        ride_type_dist = {r['ride_type']: r['count'] for r in c.fetchall()}

        return {
            'total_users': tot_users,
            'verified_users': ver_users,
            'flagged_reviews': flagged,
            'active_rides': act_rides,
            'completed_trips': comp_trips,
            'active_sos': sos_count,
            'fairness_gender_distribution': gender_dist,
            'ride_type_distribution': ride_type_dist
        }

# --- Ratings ---
@api_router.post('/ratings')
def submit_rating(req: RatingCreate):
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''
        INSERT INTO ratings (trip_id, from_user_id, to_user_id, role, score, comment)
        VALUES (?, ?, ?, ?, ?, ?)
        ''', (req.trip_id, req.from_user_id, req.to_user_id, req.role, req.score, req.comment))

        c.execute('SELECT AVG(score) as avg_score, COUNT(*) as count FROM ratings WHERE to_user_id = ?', (req.to_user_id,))
        res = c.fetchone()
        new_rating = round(res['avg_score'], 1) if res and res['avg_score'] else 5.0
        c.execute('UPDATE users SET rating = ?, rating_count = ? WHERE id = ?', (new_rating, res['count'], req.to_user_id))

        return {'status': 'success', 'new_rating': new_rating}

# --- Simulator Ticker ---
@api_router.post('/simulator/tick-trip/{trip_id}')
def tick_trip_simulator(trip_id: int):
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM trips WHERE id = ?', (trip_id,))
        t = c.fetchone()
        if not t:
            raise HTTPException(status_code=404, detail='Trip not found')

        waypoints = json.loads(t['route_polyline'])
        curr_lat, curr_lng = t['current_lat'], t['current_lng']

        next_point = None
        for i, pt in enumerate(waypoints):
            if abs(pt[0] - curr_lat) < 0.0001 and abs(pt[1] - curr_lng) < 0.0001:
                if i + 1 < len(waypoints):
                    next_point = waypoints[i + 1]
                break

        if not next_point and waypoints:
            next_point = waypoints[0]

        if next_point:
            c.execute('UPDATE trips SET current_lat = ?, current_lng = ? WHERE id = ?', (next_point[0], next_point[1], trip_id))
            return {'lat': next_point[0], 'lng': next_point[1], 'reached_end': (next_point == waypoints[-1])}
        return {'lat': curr_lat, 'lng': curr_lng, 'reached_end': True}

# --- Reset Demo Data (Admin only) ---
@api_router.post('/admin/reset-demo-data')
def reset_demo_data():
    """Wipes transient data (rides, requests, trips, fares, chat, ratings, safety_events)
    and re-seeds fresh demo rides. Keeps users, vehicles, locations, and settings intact."""
    with get_db() as conn:
        c = conn.cursor()
        # Wipe transient tables
        c.execute('DELETE FROM chat_messages')
        c.execute('DELETE FROM ratings')
        c.execute('DELETE FROM safety_events')
        c.execute('DELETE FROM trips')
        c.execute('DELETE FROM fares')
        c.execute('DELETE FROM ride_requests')
        c.execute('DELETE FROM rides')
        # Re-seed demo rides
        c.execute("SELECT id FROM users WHERE email = 'std_21098@iobm.edu.pk' LIMIT 1")
        d1 = c.fetchone()
        c.execute("SELECT id FROM users WHERE email = 'std_22045@iobm.edu.pk' LIMIT 1")
        d2 = c.fetchone()
        c.execute("SELECT id FROM users WHERE email = 'std_20114@iobm.edu.pk' LIMIT 1")
        d3 = c.fetchone()
        c.execute("SELECT id FROM vehicles WHERE owner_id = ? LIMIT 1", (d1['id'],))
        v1 = c.fetchone()
        c.execute("SELECT id FROM vehicles WHERE owner_id = ? LIMIT 1", (d2['id'],))
        v2 = c.fetchone()
        c.execute("SELECT id FROM vehicles WHERE owner_id = ? LIMIT 1", (d3['id'],))
        v3 = c.fetchone()
        if d1 and v1:
            c.execute('''INSERT INTO rides (driver_id, vehicle_id, origin_name, origin_lat, origin_lng, dest_name, dest_lat, dest_lng, departure_time, seats_total, seats_available, ride_type, status, route_polyline, fixed_fare_pkr)
            VALUES (?, ?, 'Clifton Teen Talwar', 24.8238, 67.0326, 'IoBM Main Campus Korangi Creek', 24.8270, 67.1142, '08:15', 3, 3, 'women_only', 'scheduled', ?, 350.0)''',
            (d1['id'], v1['id'], json.dumps(SimulatorService.generate_waypoints(24.8238, 67.0326, 24.8270, 67.1142, 12))))
        if d2 and v2:
            c.execute('''INSERT INTO rides (driver_id, vehicle_id, origin_name, origin_lat, origin_lng, dest_name, dest_lat, dest_lng, departure_time, seats_total, seats_available, ride_type, status, route_polyline, fixed_fare_pkr)
            VALUES (?, ?, 'DHA Phase 5 Khayaban-e-Shahbaz', 24.8140, 67.0680, 'IoBM Engineering Block Gate', 24.8270, 67.1142, '08:30', 1, 1, 'bike_pool', 'scheduled', ?, 120.0)''',
            (d2['id'], v2['id'], json.dumps(SimulatorService.generate_waypoints(24.8140, 67.0680, 24.8270, 67.1142, 12))))
        if d3 and v3:
            c.execute('''INSERT INTO rides (driver_id, vehicle_id, origin_name, origin_lat, origin_lng, dest_name, dest_lat, dest_lng, departure_time, seats_total, seats_available, ride_type, status, route_polyline, fixed_fare_pkr)
            VALUES (?, ?, 'Gulshan-e-Iqbal Block 13-D', 24.9180, 67.0970, 'IoBM Business School Gate', 24.8270, 67.1142, '08:00', 3, 3, 'car_pool', 'scheduled', ?, 400.0)''',
            (d3['id'], v3['id'], json.dumps(SimulatorService.generate_waypoints(24.9180, 67.0970, 24.8270, 67.1142, 12))))
    return {'status': 'success', 'message': 'Demo data reset successfully. 3 fresh campus rides available.'}
