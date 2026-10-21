# CampusPool 🎓
> University-Only Ride-Sharing System for Students & Staff

CampusPool is a university-only ride-sharing web application built for university campuses. It supports **Car Pools**, **Bike Pools** (1 pillion seat), and **Verified Women-Only Pools**. It matches riders to drivers using **route overlap and lecture timetables**, auto-generates fair suggested cost-sharing fares with a **fare pitching/counter-offer engine**, and enforces **identity verification** (University Email + ID Card + Face Liveness + Browser Soft Gender Signal routed to human review).

---

## 🚀 Key Features

1. **Sign-up & University Verification**
   - University email verification (`.edu`, `.ac.uk`, etc.)
   - ID card upload + live selfie capture
   - Browser-based liveness test (blink & head turn challenge)
   - Soft gender-estimate signal: flags doubtful/mismatched cases for human review, never auto-approves or auto-rejects
   - Admin approval queue for edge cases

2. **Matching Engine with Explainability**
   - Haversine route detour calculation
   - Lecture timetable synchronization (arrival windows prior to class)
   - Plain-language explanation cards:
     * *"5.2 min detour • Arrives 18 mins before CS301 • 4.9★ Driver • $4.50 suggested fare"*

3. **Fare Negotiation Engine**
   - Algorithmic suggested fare = `f(distance, vehicle_type, fuel_cost_share)`
   - Capped negotiation: parties can pitch adjusted fares strictly within ±30% of the suggested fare
   - Mutual acceptance required before ride confirmation

4. **Strict Women-Only Mode**
   - Hard eligibility constraint: driver and all riders must be `verified` and `female`
   - Hard-blocked in matching logic for unverified or male accounts

5. **Live Trip Tracking & Coarse Privacy**
   - Interactive Leaflet.js / OpenStreetMap display
   - Privacy Shield: Shows riders a 350m coarse radius zone until the ride is confirmed, then unlocks exact pickup coordinates
   - GPS simulator ticker to demonstrate real-time vehicle movement

6. **Instant SOS Emergency System**
   - One-click emergency trigger broadcasting GPS coordinates to Campus Police and user emergency contacts
   - Live incident moderation console on Admin Dashboard

7. **Admin Moderation & Fairness Dashboard**
   - User verification queue (ID card vs selfie vs soft gender estimate)
   - Safety event logs with instant incident resolution
   - Fairness metrics: ride distributions by gender and vehicle type

---

## 🛠️ Tech Stack

- **Backend**: Python 3.12, FastAPI, Uvicorn, SQLite (WAL mode, PostGIS-compatible spatial math)
- **Frontend**: Responsive Single-Page Application (HTML5, Tailwind CSS, Leaflet.js, OpenStreetMap, WebRTC/Canvas)
- **API & Docs**: Auto-generated interactive OpenAPI/Swagger at `/docs`
- **Testing**: Python `unittest` suite testing matching, detours, fare pitch bounds, and women-only constraints

---

## ⚡ Quick Start

### 1. Launch CampusPool
From the project root:
```bash
python run.py
```
Open your browser at:
- **Web Application**: `http://127.0.0.1:8000`
- **Swagger API Docs**: `http://127.0.0.1:8000/docs`

### 2. Run Automated Unit Tests
```bash
python -m unittest discover -s backend/tests -p "test_*.py"
```

---

## 👥 Demo Pre-Seeded Accounts

CampusPool comes with pre-configured campus accounts for instant demonstration via the top role switcher:

| Name | Role | Profile / Pool Type | Status |
|---|---|---|---|
| **Fatima Zahra** | Rider | Female student, enrolled in CS-401 Machine Learning | Verified |
| **Hamza Ali** | Rider | Male student, enrolled in SE-302 Cloud Systems | Verified |
| **Amina Tariq** | Driver | Toyota Aqua Hybrid (Car Pool & Women-Only Pool) | Verified (4.9★) |
| **Bilal Ahmed** | Driver | Yamaha YBR 125G (Bike Pool, 1 seat) | Verified (4.8★) |
| **Zain Malik** | Driver | Honda Civic (Mixed Car Pool) | Verified (4.7★) |
| **Sara Khan** | Rider | Female student with soft gender confidence 62% | Flagged for Admin Review |
| **Campus Admin** | Admin | University Safety Officer & Verification Reviewer | Moderator |

---

## 🔒 Security Architecture & STRIDE Threat Model

| Threat Category | Mitigation Implemented |
|---|---|
| **Spoofing (Identity)** | University email domain enforcement (`.edu`), ID photo match, and interactive liveness challenge (blinking/head turn). |
| **Tampering (Fares & Roles)** | Server-side pitch validation enforces strict ±30% bounds; RBAC ensures riders cannot publish rides or approve accounts. |
| **Repudiation** | Detailed audit logs for every ride request, fare negotiation step, and safety event. |
| **Information Disclosure** | Coarse zone privacy masks exact pickup coordinates with a 350m radius until ride is mutually confirmed. No raw camera frames stored permanently. |
| **Denial of Service** | Efficient SQLite indexing and bounded detour calculations avoid exponential search overhead. |
| **Elevation of Privilege** | Admin endpoints strictly separated and validated against user role records. |
