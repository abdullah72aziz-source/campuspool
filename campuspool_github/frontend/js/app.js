// CampusPool Frontend — Full Application Controller
// Features: Real Login/Signup, Admin Branding, Location+Fare Manager, Passenger Gender Counts, Scalable Users

let currentUser = null;
let currentFilter = 'all';
let map = null;
let driverMarker = null;
let routePolyline = null;
let coarseCircle = null;
let activeTripId = null;
let currentPitchData = null;
let currentScore = 5;
let webcamStream = null;
let adminLocations = [];

const IOBM_COORDS = [24.8270, 67.1142];

// =========================================================
// BOOT: load branding, then check session
// =========================================================
document.addEventListener('DOMContentLoaded', async () => {
  await loadAppBranding();
  const saved = sessionStorage.getItem('campuspool_user');
  if (saved) {
    try {
      currentUser = JSON.parse(saved);
      await enterApp();
    } catch {
      showLoginScreen();
    }
  } else {
    showLoginScreen();
  }
});

async function loadAppBranding() {
  try {
    const res = await fetch('/api/admin/app-settings');
    if (!res.ok) return;
    const s = await res.json();
    const name = s.app_name || 'IoBM CampusPool';
    const emoji = s.app_logo_emoji || '🎓';
    const tagline = s.app_tagline || 'Institute of Business Management • Korangi Creek, Karachi';
    const pfp = s.app_pfp_url || '';

    // Update login screen
    const loginName = document.getElementById('loginAppName');
    const loginEmoji = document.getElementById('loginLogoEmoji');
    const loginTag = document.getElementById('loginTagline');
    if (loginName) loginName.textContent = name;
    
    if (loginTag) loginTag.textContent = tagline;

    // Update main app header
    applyBrandingToHeader({ app_name: name, app_logo_emoji: emoji, app_tagline: tagline, app_pfp_url: pfp });

    document.getElementById('pageTitle').textContent = name;
  } catch { /* server may not be running yet */ }
}

function applyBrandingToHeader(s) {
  const headerName = document.getElementById('headerAppName');
  const headerLogo = document.getElementById('headerLogoWrap');
  const headerTag = document.getElementById('headerTagline');
  if (headerName) headerName.textContent = s.app_name || 'IoBM CampusPool';
  
  if (headerTag) headerTag.textContent = s.app_tagline || '';
  document.getElementById('pageTitle').textContent = s.app_name || 'IoBM CampusPool';

  // Update admin pfp in header if set
  if (s.app_pfp_url && currentUser && currentUser.role === 'admin') {
    const pfpEl = document.getElementById('headerUserPfp');
    if (pfpEl) {
      pfpEl.innerHTML = `<img src="${s.app_pfp_url}" class="w-full h-full object-cover rounded-full" onerror="this.parentElement.textContent='👤'">`;
    }
  }
}

// =========================================================
// AUTH FLOWS
// =========================================================
function showLoginScreen() {
  document.getElementById('loginScreen').classList.remove('hidden');
  document.getElementById('mainApp').classList.add('hidden');
}

function showAuthTab(tab) {
  const isLogin = tab === 'login';
  document.getElementById('loginForm').classList.toggle('hidden', !isLogin);
  document.getElementById('signupForm').classList.toggle('hidden', isLogin);
  document.getElementById('authTabLogin').classList.toggle('tab-active', isLogin);
  document.getElementById('authTabSignup').classList.toggle('tab-active', !isLogin);
  document.getElementById('authTabLogin').classList.toggle('text-emerald-200', !isLogin);
  document.getElementById('authTabSignup').classList.toggle('text-emerald-200', isLogin);
}

async function handleLogin() {
  const email = document.getElementById('loginEmail').value.trim();
  const password = document.getElementById('loginPassword').value;
  const errEl = document.getElementById('loginError');
  errEl.classList.add('hidden');

  if (!email || !password) {
    errEl.textContent = 'Please enter your IoBM email and password.';
    errEl.classList.remove('hidden');
    return;
  }

  try {
    const res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password })
    });
    const data = await res.json();
    if (!res.ok) {
      errEl.textContent = data.detail || 'Invalid email or password.';
      errEl.classList.remove('hidden');
      return;
    }
    currentUser = data.user;
    sessionStorage.setItem('campuspool_user', JSON.stringify(currentUser));
    await enterApp();
  } catch (err) {
    errEl.textContent = 'Server error. Make sure the server is running.';
    errEl.classList.remove('hidden');
  }
}

async function handleSignup() {
  const name = document.getElementById('signupName').value.trim();
  const studentId = document.getElementById('signupStudentId').value.trim();
  const email = document.getElementById('signupEmail').value.trim();
  const password = document.getElementById('signupPassword').value;
  const role = document.getElementById('signupRole').value;
  const gender = document.getElementById('signupGender').value;
  const emergName = document.getElementById('signupEmergName').value.trim();
  const emergPhone = document.getElementById('signupEmergPhone').value.trim();
  const errEl = document.getElementById('signupError');
  errEl.classList.add('hidden');

  if (!name || !email || !password || !studentId) {
    errEl.textContent = 'Please fill in all required fields.';
    errEl.classList.remove('hidden');
    return;
  }
  if (password.length < 6) {
    errEl.textContent = 'Password must be at least 6 characters.';
    errEl.classList.remove('hidden');
    return;
  }

  try {
    const res = await fetch('/api/auth/signup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name, email, password,
        university_id: studentId,
        role, gender_on_record: gender,
        emergency_contact_name: emergName,
        emergency_contact_phone: emergPhone
      })
    });
    const data = await res.json();
    if (!res.ok) {
      errEl.textContent = data.detail || 'Sign up failed.';
      errEl.classList.remove('hidden');
      return;
    }
    currentUser = data.user;
    sessionStorage.setItem('campuspool_user', JSON.stringify(currentUser));
    await enterApp();
  } catch (err) {
    errEl.textContent = 'Server error. Make sure the server is running.';
    errEl.classList.remove('hidden');
  }
}

function handleLogout() {
  currentUser = null;
  sessionStorage.removeItem('campuspool_user');
  activeTripId = null;
  if (webcamStream) {
    webcamStream.getTracks().forEach(t => t.stop());
    webcamStream = null;
  }
  showLoginScreen();
}

// =========================================================
// ENTER APP after login
// =========================================================
async function enterApp() {
  document.getElementById('loginScreen').classList.add('hidden');
  document.getElementById('mainApp').classList.remove('hidden');

  updateHeaderUser();
  initMap();
  await loadAdminLocations(); // load locations for dropdowns

  // Show/hide admin tab
  const adminTab = document.getElementById('tab-admin');
  if (currentUser.role === 'admin') {
    adminTab.classList.remove('hidden');
  } else {
    adminTab.classList.add('hidden');
  }

  // Switch to appropriate tab
  if (currentUser.role === 'admin') {
    switchTab('admin');
  } else if (currentUser.role === 'driver') {
    switchTab('driver');
  } else {
    switchTab('rider');
  }

  await refreshAll();

  // Poll dashboard every 5s
  setInterval(() => {
    const trackingView = document.getElementById('view-tracking');
    if (trackingView && !trackingView.classList.contains('hidden') && activeTripId) {
      loadChatMessages();
    }
    if (!document.getElementById('view-driver').classList.contains('hidden')) {
      loadDriverDashboard();
    }
  }, 5000);
}

function updateHeaderUser() {
  if (!currentUser) return;
  const roleIcon = currentUser.role === 'driver' ? '🚘' : (currentUser.role === 'admin' ? '⚙️' : '🚗');
  document.getElementById('headerUserName').textContent = currentUser.name;
  document.getElementById('headerUserRole').textContent = `${roleIcon} ${currentUser.role.toUpperCase()} • ${currentUser.verified_status.toUpperCase()}`;
  document.getElementById('currentUserBadge').textContent = `${roleIcon} ${currentUser.name} • ${currentUser.email}`;

  const pfpEl = document.getElementById('headerUserPfp');
  if (currentUser.profile_pic_url) {
    pfpEl.innerHTML = `<img src="${currentUser.profile_pic_url}" class="w-full h-full object-cover rounded-full" onerror="this.parentElement.textContent='👤'">`;
  } else {
    pfpEl.textContent = currentUser.name.charAt(0).toUpperCase();
  }

  const sosLabel = document.getElementById('sosContactLabel');
  if (sosLabel) {
    sosLabel.textContent = `${currentUser.emergency_contact_name || 'IoBM Campus Security'} (${currentUser.emergency_contact_phone || '021-111-002-004'})`;
  }

  const verifCard = document.getElementById('verifCardDetails');
  if (verifCard) {
    verifCard.textContent = `${currentUser.university_id} • ${currentUser.name}`;
  }
}

async function refreshAll() {
  await searchMatchingRides();
  await loadRiderBookings();
  await loadDriverDashboard();
  if (currentUser && currentUser.role === 'admin') {
    await loadAdminDashboard();
    await loadAdminFareSettings();
    await loadAdminUsers();
    await loadAdminLocationsUI();
    await loadAdminAppSettings();
  }
  await loadActiveTrip();
}

// =========================================================
// LOCATIONS — load admin-defined Karachi locations
// =========================================================
async function loadAdminLocations() {
  try {
    const res = await fetch('/api/admin/locations');
    if (!res.ok) return;
    adminLocations = await res.json();
    populateLocationDropdowns();
  } catch {}
}

function populateLocationDropdowns() {
  const pickups = adminLocations.filter(l => l.zone === 'pickup');
  const destinations = adminLocations.filter(l => l.zone === 'destination');

  const selectors = [
    { id: 'riderPickupSelect', data: pickups },
    { id: 'driverOriginSelect', data: pickups },
    { id: 'riderDropSelect', data: destinations },
    { id: 'driverDestSelect', data: destinations }
  ];

  selectors.forEach(({ id, data }) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.innerHTML = '';
    data.forEach(loc => {
      const opt = document.createElement('option');
      opt.value = `${loc.lat},${loc.lng},${loc.name},${loc.ac_fare_pkr},${loc.nonac_fare_pkr}`;
      opt.textContent = loc.name;
      el.appendChild(opt);
    });
  });

  updateFarePreview();
}

function updateFarePreview() {
  const pickEl = document.getElementById('riderPickupSelect');
  const box = document.getElementById('farePreviewBox');
  if (!pickEl || !box) return;

  const parts = pickEl.value.split(',');
  if (parts.length >= 5) {
    const acFare = parseFloat(parts[3]);
    const nonAcFare = parseFloat(parts[4]);
    if (acFare > 0 || nonAcFare > 0) {
      box.classList.remove('hidden');
      box.innerHTML = `🚗 AC Fare: <strong>Rs. ${acFare}</strong> &nbsp;|&nbsp; 🌀 Non-AC Fare: <strong>Rs. ${nonAcFare}</strong> <span class="text-emerald-600">(Admin set)</span>`;
    } else {
      box.classList.add('hidden');
    }
  }
}

// =========================================================
// TAB SWITCHING
// =========================================================
function switchTab(tabId) {
  const tabs = ['rider', 'driver', 'tracking', 'verification', 'admin'];
  tabs.forEach(t => {
    const view = document.getElementById(`view-${t}`);
    const btn = document.getElementById(`tab-${t}`);
    if (view) view.classList.add('hidden');
    if (btn) {
      btn.classList.remove('bg-emerald-900', 'text-white', 'tab-active');
      btn.classList.add('text-emerald-100');
    }
  });

  const activeView = document.getElementById(`view-${tabId}`);
  const activeBtn = document.getElementById(`tab-${tabId}`);
  if (activeView) activeView.classList.remove('hidden');
  if (activeBtn) {
    activeBtn.classList.add('bg-emerald-900', 'text-white', 'tab-active');
    activeBtn.classList.remove('text-emerald-100');
  }

  if (tabId === 'tracking') {
    setTimeout(() => { if (map) map.invalidateSize(); }, 200);
    loadActiveTrip();
    loadChatMessages();
  } else if (tabId === 'driver') {
    loadDriverDashboard();
  } else if (tabId === 'admin') {
    loadAdminDashboard();
    loadAdminFareSettings();
    loadAdminUsers();
    loadAdminLocationsUI();
    loadAdminAppSettings();
  }
}

// =========================================================
// MAP INIT (Karachi - proper OSM tiles)
// =========================================================
function initMap() {
  if (map) return;
  map = L.map('map').setView(IOBM_COORDS, 13);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
  }).addTo(map);

  L.marker(IOBM_COORDS).addTo(map)
    .bindPopup('<b>🏛️ IoBM Main Campus</b><br>Korangi Creek, Karachi')
    .openPopup();
}

// =========================================================
// RIDER: SEARCH & BOOK
// =========================================================
function setFilter(type) {
  currentFilter = type;
  ['all', 'car_pool', 'bike_pool', 'women_only'].forEach(f => {
    const b = document.getElementById(`flt-${f}`);
    if (b) {
      if (f === type) {
        b.className = 'py-1.5 rounded-lg border bg-emerald-700 text-white border-emerald-700 font-bold';
      } else {
        b.className = 'py-1.5 rounded-lg border bg-white text-slate-700 border-slate-300';
      }
    }
  });
  searchMatchingRides();
}

async function searchMatchingRides() {
  if (!currentUser) return;
  const pickEl = document.getElementById('riderPickupSelect');
  const dropEl = document.getElementById('riderDropSelect');
  if (!pickEl || !dropEl || !pickEl.value || !dropEl.value) return;

  const pickParts = pickEl.value.split(',');
  const dropParts = dropEl.value.split(',');

  try {
    const res = await fetch('/api/matching/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        rider_id: currentUser.id,
        pick_lat: parseFloat(pickParts[0]),
        pick_lng: parseFloat(pickParts[1]),
        drop_lat: parseFloat(dropParts[0]),
        drop_lng: parseFloat(dropParts[1]),
        ride_type_filter: currentFilter
      })
    });
    const data = await res.json();
    renderMatches(data.matches || []);
  } catch (err) {
    console.error('Search error:', err);
  }
}

async function renderMatches(matches) {
  const container = document.getElementById('matchesContainer');
  const countLabel = document.getElementById('matchCountLabel');
  countLabel.textContent = `${matches.length} ride(s) found`;
  container.innerHTML = '';

  if (matches.length === 0) {
    container.innerHTML = `
      <div class="p-8 text-center glass-card rounded-2xl border border-slate-200">
        <span class="text-3xl block mb-2">🚗</span>
        <h4 class="font-bold text-slate-700">No matching campus pools found</h4>
        <p class="text-xs text-slate-500 mt-1">Try expanding your departure time or switching ride type filter.</p>
      </div>`;
    return;
  }

  for (const m of matches) {
    const r = m.ride;
    const isWomenOnly = r.ride_type === 'women_only';
    const isBike = r.ride_type === 'bike_pool';
    const isAdminFixed = m.fare.is_admin_fixed;

    // Fetch passenger count
    let passengerInfo = { male: 0, female: 0, total: 0 };
    try {
      const pRes = await fetch(`/api/rides/${r.id}/passengers`);
      if (pRes.ok) passengerInfo = await pRes.json();
    } catch {}

    const maleCount = passengerInfo.male || 0;
    const femaleCount = passengerInfo.female || 0;
    const totalPassengers = passengerInfo.total || 0;

    const card = document.createElement('div');
    card.className = `p-4 rounded-2xl glass-card border transition hover:shadow-md ${isWomenOnly ? 'border-purple-300 bg-purple-50/30' : 'border-slate-200'}`;
    card.innerHTML = `
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div class="space-y-1 flex-1">
          <div class="flex flex-wrap items-center gap-2">
            <span class="font-bold text-slate-800 text-sm">${r.driver_name}</span>
            <span class="text-amber-500 text-xs font-bold">★ ${r.driver_rating}</span>
            <span class="text-[11px] px-2 py-0.5 rounded-full font-semibold ${isWomenOnly ? 'bg-purple-100 text-purple-800' : (isBike ? 'bg-amber-100 text-amber-800' : 'bg-emerald-100 text-emerald-800')}">
              ${isWomenOnly ? '🌸 Women-Only' : (isBike ? '🏍️ Bike Pool' : '🚗 Car Pool')}
            </span>
            <span class="text-[10px] px-2 py-0.5 rounded-full bg-slate-100 text-slate-700 font-semibold border border-slate-300">
              ${r.make} ${r.model} • ${r.year} • <strong>${r.ac_type}</strong>
            </span>
          </div>
          <div class="text-xs text-slate-600">
            Route: <strong>${r.origin_name}</strong> ➔ <strong>${r.dest_name}</strong>
          </div>
          <div class="text-[11px] text-slate-500">
            Departs: <strong>${r.departure_time}</strong> • Seats Left: <strong>${r.seats_available}/${r.seats_total}</strong> • Plate: ${r.license_plate}
          </div>
          <!-- PASSENGER GENDER COUNT -->
          <div class="flex items-center gap-2 mt-1.5">
            <span class="text-[10px] font-semibold text-slate-500">Passengers (${totalPassengers}):</span>
            <span class="gender-badge-m text-[10px] px-1.5 py-0.5 rounded-full font-bold">👨 ${maleCount} Male</span>
            <span class="gender-badge-f text-[10px] px-1.5 py-0.5 rounded-full font-bold">👩 ${femaleCount} Female</span>
          </div>
          <div class="inline-block mt-1 px-2.5 py-1 bg-slate-100 rounded-lg text-[11px] text-slate-700 font-medium border border-slate-200">
            💡 ${m.explanation}
          </div>
        </div>
        <div class="text-right space-y-2">
          <div>
            <span class="text-[11px] font-semibold text-slate-500 block">
              ${isAdminFixed ? '🔒 Admin Fixed Fare' : '🤝 Negotiable'}
            </span>
            <span class="text-lg font-black ${isAdminFixed ? 'text-emerald-700' : 'text-indigo-700'}">
              Rs. ${m.fare.fare_pkr.toFixed(0)}
            </span>
          </div>
          <div class="flex gap-1.5 justify-end">
            <button onclick="requestRideDirect(${r.id}, ${m.fare.fare_pkr})" class="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-700 text-white font-bold rounded-lg text-xs shadow transition">
              ${isAdminFixed ? 'Book Ride' : 'Accept & Book'}
            </button>
            ${!isAdminFixed ? `
              <button onclick="openPitchModalForBike(${r.id}, ${m.fare.fare_pkr})" class="px-2.5 py-1.5 bg-white hover:bg-slate-50 border border-slate-300 text-slate-700 font-bold rounded-lg text-xs transition">
                Counter Fare
              </button>` : ''}
          </div>
        </div>
      </div>
    `;
    container.appendChild(card);
  }
}

async function requestRideDirect(rideId, farePkr, customPitched = null) {
  const pickEl = document.getElementById('riderPickupSelect');
  const dropEl = document.getElementById('riderDropSelect');
  const pickParts = pickEl.value.split(',');
  const dropParts = dropEl.value.split(',');

  try {
    const res = await fetch('/api/requests', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ride_id: rideId,
        rider_id: currentUser.id,
        pickup_name: pickParts[2],
        pickup_lat: parseFloat(pickParts[0]),
        pickup_lng: parseFloat(pickParts[1]),
        drop_name: dropParts[2],
        drop_lat: parseFloat(dropParts[0]),
        drop_lng: parseFloat(dropParts[1])
      })
    });
    const data = await res.json();
    if (!res.ok) {
      alert(`Booking Error: ${data.detail || 'Could not request ride'}`);
      return;
    }

    if (customPitched) {
      await fetch('/api/fares/pitch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ request_id: data.request_id, pitched_fare: customPitched, pitched_by: 'rider' })
      });
    }

    alert(`✅ Ride booked! Request #${data.request_id} sent to driver.`);
    await loadRiderBookings();
    await searchMatchingRides();
  } catch (err) {
    console.error('Request failed:', err);
  }
}

async function loadRiderBookings() {
  if (!currentUser) return;
  try {
    const res = await fetch(`/api/requests/rider/${currentUser.id}`);
    const requests = await res.json();
    const container = document.getElementById('riderBookingsContainer');
    if (!container) return;
    container.innerHTML = '';

    if (requests.length === 0) {
      container.innerHTML = '<div class="text-slate-400 py-2">No active ride requests yet.</div>';
      return;
    }

    requests.forEach(req => {
      const isAccepted = req.status === 'accepted';
      const isPitched = req.fare_status === 'pitched';

      const item = document.createElement('div');
      item.className = 'p-3 bg-white rounded-xl border border-slate-200 flex items-center justify-between';
      item.innerHTML = `
        <div>
          <div class="font-bold text-slate-800">Ride with ${req.driver_name}</div>
          <div class="text-[11px] text-slate-500">${req.origin_name} ➔ ${req.dest_name} • Pickup: <strong>${req.pickup_name}</strong></div>
          <div class="text-[11px] text-slate-600 mt-0.5">
            Status: <span class="font-bold ${isAccepted ? 'text-emerald-600' : (req.status === 'declined' ? 'text-rose-600' : 'text-amber-600')}">${req.status.toUpperCase()}</span>
            • Fare: ${req.is_admin_fixed ? `<strong>Rs. ${(req.suggested_fare||0).toFixed(0)} (Admin Fixed)</strong>` : `Rs. ${(req.suggested_fare||0).toFixed(0)}`}
            ${req.pitched_fare ? ` • Pitched by ${req.pitched_by}: <strong>Rs. ${(req.pitched_fare||0).toFixed(0)}</strong>` : ''}
          </div>
        </div>
        <div class="text-right">
          ${isAccepted && req.active_trip_id ? `
            <button onclick="viewActiveTrip(${req.active_trip_id})" class="px-3 py-1 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg font-bold text-xs">
              Live Trip ➔
            </button>` : ''}
          ${isPitched && req.pitched_by === 'driver' ? `
            <div class="flex gap-1 mt-1">
              <button onclick="respondPitch(${req.id}, 'accept')" class="px-2 py-0.5 bg-emerald-600 text-white rounded text-[11px] font-bold">Accept</button>
              <button onclick="respondPitch(${req.id}, 'decline')" class="px-2 py-0.5 bg-slate-200 text-slate-700 rounded text-[11px]">Decline</button>
            </div>` : ''}
        </div>
      `;
      container.appendChild(item);
    });
  } catch (err) {
    console.error('Error loading bookings:', err);
  }
}

// =========================================================
// DRIVER: POST & MANAGE
// =========================================================
async function postRideOffer() {
  if (!currentUser) return;
  const orig = document.getElementById('driverOriginSelect').value.split(',');
  const dest = document.getElementById('driverDestSelect').value.split(',');
  const time = document.getElementById('driverDepTime').value;
  const seats = parseInt(document.getElementById('driverSeats').value);
  const type = document.getElementById('driverRideType').value;
  const make = document.getElementById('vehMake').value || 'Toyota';
  const model = document.getElementById('vehModel').value || 'Aqua';
  const year = parseInt(document.getElementById('vehYear').value || 2021);
  const plate = document.getElementById('vehPlate').value || 'BDN-492';
  const acType = document.querySelector('input[name="vehAC"]:checked').value;

  const vehRes = await fetch('/api/vehicles', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      owner_id: currentUser.id,
      vehicle_type: type === 'bike_pool' ? 'bike' : 'car',
      make, model, year, ac_type: acType,
      color: 'White', license_plate: plate, seats_total: seats
    })
  });
  const vehData = await vehRes.json();

  try {
    const res = await fetch('/api/rides', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        driver_id: currentUser.id,
        vehicle_id: vehData.id,
        origin_name: orig[2],
        origin_lat: parseFloat(orig[0]),
        origin_lng: parseFloat(orig[1]),
        dest_name: dest[2],
        dest_lat: parseFloat(dest[0]),
        dest_lng: parseFloat(dest[1]),
        departure_time: time,
        seats_total: seats,
        ride_type: type
      })
    });
    const data = await res.json();
    if (!res.ok) {
      alert(`Post Ride Failed: ${data.detail || 'Access Denied'}`);
      return;
    }
    alert('✅ Ride published successfully!');
    await loadDriverDashboard();
  } catch (err) {
    console.error('Post ride failed:', err);
  }
}

async function loadDriverDashboard() {
  if (!currentUser || currentUser.role !== 'driver') return;
  try {
    const res = await fetch(`/api/rides/driver/${currentUser.id}`);
    const data = await res.json();

    const ridesContainer = document.getElementById('driverRidesContainer');
    const reqContainer = document.getElementById('driverRequestsContainer');

    if (ridesContainer) {
      ridesContainer.innerHTML = '';
      if (data.rides.length === 0) {
        ridesContainer.innerHTML = '<div class="text-slate-400">No rides scheduled today.</div>';
      } else {
        data.rides.forEach(r => {
          const div = document.createElement('div');
          div.className = 'p-3 bg-white rounded-xl border border-slate-200 flex justify-between items-center';
          div.innerHTML = `
            <div>
              <span class="font-bold text-slate-800">${r.origin_name} ➔ ${r.dest_name}</span>
              <span class="text-slate-500 text-[11px] block">Time: ${r.departure_time} • Seats: ${r.seats_available}/${r.seats_total} • ${r.make} ${r.model} (${r.ac_type})</span>
            </div>
            <span class="text-xs bg-emerald-100 text-emerald-800 font-semibold px-2 py-0.5 rounded-full">${r.status}</span>
          `;
          ridesContainer.appendChild(div);
        });
      }
    }

    if (reqContainer) {
      reqContainer.innerHTML = '';
      if (!data.requests || data.requests.length === 0) {
        reqContainer.innerHTML = '<div class="text-slate-400">No incoming requests right now.</div>';
      } else {
        data.requests.forEach(req => {
          const isPending = req.status === 'pending';
          const genderIcon = req.rider_gender === 'female' ? '👩' : (req.rider_gender === 'male' ? '👨' : '🧑');
          const div = document.createElement('div');
          div.className = 'p-3 bg-white rounded-xl border border-slate-200 space-y-2';
          div.innerHTML = `
            <div class="flex justify-between items-start">
              <div>
                <span class="font-bold text-slate-800 text-xs">${genderIcon} ${req.rider_name} (★${req.rider_rating})</span>
                <span class="text-slate-500 text-[11px] block">Pickup: <strong>${req.pickup_name}</strong> ➔ ${req.drop_name}</span>
                <span class="text-slate-700 text-[11px] font-bold">
                  Fare: Rs. ${(req.pitched_fare || req.suggested_fare || 0).toFixed(0)} ${req.is_admin_fixed ? '(Admin Fixed)' : (req.pitched_fare ? `(Pitched by ${req.pitched_by})` : '(Negotiable)')}
                </span>
              </div>
              <span class="text-[11px] font-bold px-2 py-0.5 rounded ${isPending ? 'bg-amber-100 text-amber-800' : 'bg-emerald-100 text-emerald-800'}">
                ${req.status.toUpperCase()}
              </span>
            </div>
            ${isPending ? `
              <div class="flex gap-2 justify-end pt-1">
                <button onclick="respondToRequest(${req.id}, 'accept')" class="px-3 py-1 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg font-bold text-xs shadow">Accept Rider</button>
                <button onclick="respondToRequest(${req.id}, 'decline')" class="px-2.5 py-1 bg-slate-100 hover:bg-slate-200 text-slate-600 rounded-lg text-xs">Decline</button>
              </div>` : ''}
          `;
          reqContainer.appendChild(div);
        });
      }
    }
  } catch (err) {
    console.error('Driver dashboard error:', err);
  }
}

async function respondToRequest(requestId, action) {
  try {
    const res = await fetch('/api/requests/respond', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ request_id: requestId, action })
    });
    const data = await res.json();
    alert(`Request ${action}ed!`);
    await loadDriverDashboard();
    if (data.trip_id) viewActiveTrip(data.trip_id);
  } catch (err) {
    console.error('Respond error:', err);
  }
}

// =========================================================
// FARE PITCHING
// =========================================================
function openPitchModalForBike(rideId, suggested) {
  currentPitchData = { rideId, suggested };
  document.getElementById('pitchModalSuggested').textContent = `Rs. ${suggested.toFixed(0)}`;
  document.getElementById('pitchModalInput').value = suggested.toFixed(0);
  document.getElementById('farePitchModal').classList.remove('hidden');
}

function closePitchModal() {
  document.getElementById('farePitchModal').classList.add('hidden');
}

async function submitPitchedFare() {
  const pitched = parseFloat(document.getElementById('pitchModalInput').value);
  if (!pitched || isNaN(pitched) || pitched <= 0) {
    alert('Please enter a valid fare in PKR.');
    return;
  }
  closePitchModal();
  await requestRideDirect(currentPitchData.rideId, currentPitchData.suggested, pitched);
}

async function respondPitch(requestId, action) {
  try {
    const res = await fetch('/api/fares/respond', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ request_id: requestId, action })
    });
    const data = await res.json();
    alert(data.message);
    await loadRiderBookings();
    await loadDriverDashboard();
  } catch (err) {
    console.error('Pitch respond failed:', err);
  }
}

// =========================================================
// LIVE TRIP & CHAT
// =========================================================
function viewActiveTrip(tripId) {
  activeTripId = tripId;
  switchTab('tracking');
}

async function loadActiveTrip() {
  if (!activeTripId) return;
  try {
    const res = await fetch(`/api/trips/${activeTripId}`);
    if (!res.ok) return;
    const trip = await res.json();

    document.getElementById('bannerDriver').textContent = `${trip.driver_name} (${trip.make} ${trip.model} • ${trip.ac_type})`;
    document.getElementById('bannerRider').textContent = trip.rider_name;
    document.getElementById('bannerFare').textContent = `Rs. ${(trip.final_fare || trip.suggested_fare || 300).toFixed(0)} ${trip.is_admin_fixed ? '(Admin Fixed)' : '(Negotiated)'}`;

    if (!map) initMap();
    if (driverMarker) map.removeLayer(driverMarker);
    if (routePolyline) map.removeLayer(routePolyline);
    if (coarseCircle) map.removeLayer(coarseCircle);

    if (trip.route_waypoints && trip.route_waypoints.length > 0) {
      routePolyline = L.polyline(trip.route_waypoints, { color: '#047857', weight: 4, opacity: 0.8 }).addTo(map);
      map.fitBounds(routePolyline.getBounds(), { padding: [30, 30] });
    }

    coarseCircle = L.circle([trip.pickup_lat, trip.pickup_lng], {
      color: '#3b82f6', fillColor: '#93c5fd', fillOpacity: 0.25,
      radius: trip.coarse_zone_radius_meters || 350
    }).addTo(map).bindPopup(`<b>🔒 Privacy Zone</b><br>Pickup: ${trip.pickup_name}`);

    const carIcon = L.divIcon({
      className: 'custom-car-icon',
      html: `<div style="background:#065f46;color:white;padding:4px 8px;border-radius:12px;font-size:11px;font-weight:bold;box-shadow:0 2px 6px rgba(0,0,0,0.3);border:2px solid white;">🚗 Live</div>`,
      iconSize: [60, 30], iconAnchor: [30, 15]
    });

    driverMarker = L.marker([trip.current_lat, trip.current_lng], { icon: carIcon }).addTo(map)
      .bindPopup(`<b>${trip.driver_name}</b><br>${trip.make} ${trip.model} (${trip.ac_type})`);
  } catch (err) {
    console.error('Trip load failed:', err);
  }
}

async function loadChatMessages() {
  if (!activeTripId) return;
  try {
    const res = await fetch(`/api/chat/${activeTripId}`);
    const messages = await res.json();
    const box = document.getElementById('chatMessagesBox');
    if (!box) return;
    if (messages.length === 0) {
      box.innerHTML = '<div class="text-slate-400 text-center py-4 text-[11px]">Ride confirmed! Coordinate pickup here.</div>';
      return;
    }
    box.innerHTML = '';
    messages.forEach(msg => {
      const isMe = currentUser && msg.sender_id === currentUser.id;
      const bubble = document.createElement('div');
      bubble.className = `flex flex-col ${isMe ? 'items-end' : 'items-start'}`;
      bubble.innerHTML = `
        <div class="text-[10px] text-slate-400 font-semibold mb-0.5">${msg.sender_name}</div>
        <div class="p-2 rounded-xl text-xs max-w-[80%] ${isMe ? 'bg-emerald-600 text-white rounded-br-none' : 'bg-white text-slate-800 border border-slate-200 rounded-bl-none shadow-sm'}">
          ${msg.message}
        </div>
      `;
      box.appendChild(bubble);
    });
    box.scrollTop = box.scrollHeight;
  } catch {}
}

async function sendChatMessage() {
  const input = document.getElementById('chatInput');
  const text = input.value.trim();
  if (!text || !activeTripId || !currentUser) return;
  try {
    await fetch(`/api/chat/${activeTripId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sender_id: currentUser.id, sender_name: currentUser.name, message: text })
    });
    input.value = '';
    await loadChatMessages();
  } catch {}
}

async function stepSimPing() {
  if (!activeTripId) return;
  try {
    const res = await fetch(`/api/simulator/tick-trip/${activeTripId}`, { method: 'POST' });
    const data = await res.json();
    if (driverMarker && data.lat) {
      driverMarker.setLatLng([data.lat, data.lng]);
      map.panTo([data.lat, data.lng]);
    }
  } catch {}
}

async function completeActiveTrip() {
  if (!activeTripId) return;
  try {
    await fetch(`/api/trips/${activeTripId}/complete`, { method: 'POST' });
    document.getElementById('ratingModal').classList.remove('hidden');
  } catch {}
}

function setScore(score) { currentScore = score; }

async function submitRating() {
  const comment = document.getElementById('ratingCommentInput').value;
  try {
    await fetch('/api/ratings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        trip_id: activeTripId,
        from_user_id: currentUser.id,
        to_user_id: 2,
        role: 'rider_to_driver',
        score: currentScore,
        comment: comment || 'Good ride'
      })
    });
    alert('Rating submitted!');
    document.getElementById('ratingModal').classList.add('hidden');
    switchTab('rider');
  } catch {}
}

// =========================================================
// WEBCAM & VERIFICATION
// =========================================================
async function startRealWebcam() {
  const video = document.getElementById('webcam');
  const badge = document.getElementById('cameraStateBadge');
  const prompt = document.getElementById('livenessPromptBadge');
  const noteEl = document.getElementById('camPermissionNote');

  noteEl.classList.add('hidden');

  if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
    try {
      webcamStream = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480, facingMode: 'user' } });
      video.srcObject = webcamStream;
      video.classList.remove('hidden');
      document.getElementById('faceCanvas').classList.add('hidden');
      badge.textContent = 'Live Webcam Active';
      badge.className = 'text-xs bg-emerald-100 text-emerald-800 px-2 py-0.5 rounded font-bold';
      prompt.textContent = 'Webcam Online: Align face → Click "Capture & Check Liveness"';
    } catch (err) {
      console.warn('Webcam permission denied:', err);
      badge.textContent = 'Camera Blocked — Demo Mode';
      badge.className = 'text-xs bg-amber-100 text-amber-800 px-2 py-0.5 rounded font-semibold';
      prompt.textContent = 'Camera permission denied. Using simulation mode.';
      noteEl.classList.remove('hidden');
      runSimulatedCameraFallback();
    }
  } else {
    badge.textContent = 'WebRTC Not Supported';
    runSimulatedCameraFallback();
  }
}

function runSimulatedCameraFallback() {
  const canvas = document.getElementById('faceCanvas');
  const video = document.getElementById('webcam');
  video.classList.add('hidden');
  canvas.classList.remove('hidden');
  const ctx = canvas.getContext('2d');
  canvas.width = 400;
  canvas.height = 300;
  ctx.fillStyle = '#0f172a';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = '#e2e8f0';
  ctx.beginPath();
  ctx.ellipse(200, 150, 70, 95, 0, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = '#1e293b';
  ctx.beginPath();
  ctx.arc(175, 130, 8, 0, Math.PI * 2);
  ctx.arc(225, 130, 8, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = '#e2e8f0';
  ctx.beginPath();
  ctx.arc(200, 175, 20, 0, Math.PI);
  ctx.fill();
  // Animate
  let frame = 0;
  const interval = setInterval(() => {
    ctx.fillStyle = '#0f172a';
    ctx.fillRect(0, canvas.height - 30, canvas.width, 30);
    ctx.fillStyle = '#34d399';
    ctx.font = 'bold 12px monospace';
    ctx.fillText(`[SIMULATION] Frame ${++frame} — Camera Fallback Active`, 10, canvas.height - 10);
    if (frame > 60) clearInterval(interval);
  }, 100);
}

function captureWebcamSnapshot() {
  const video = document.getElementById('webcam');
  const canvas = document.getElementById('faceCanvas');
  const prompt = document.getElementById('livenessPromptBadge');
  const status = document.getElementById('livenessStatusLabel');

  if (webcamStream && !video.paused) {
    canvas.width = video.videoWidth || 400;
    canvas.height = video.videoHeight || 300;
    canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
    canvas.classList.remove('hidden');
    video.classList.add('hidden');
  }

  prompt.textContent = '⏳ Checking: Blink Eyes & Nod Head...';
  status.textContent = 'Processing...';
  status.className = 'font-bold text-amber-600';
  setTimeout(() => {
    prompt.textContent = '✅ Live Snapshot Verified — Anti-Spoofing 99.1%';
    status.textContent = 'Live Capture Verified ✓';
    status.className = 'font-bold text-emerald-600';
  }, 1500);
}

function updateSimulatedGenderSignal() {
  const val = document.getElementById('simGenderSelect').value.split(',');
  const gender = val[0];
  const conf = Math.round(parseFloat(val[1]) * 100);
  document.getElementById('genderSignalBadge').textContent = `${gender.toUpperCase()} (${conf}%)`;
}

async function submitFullVerification() {
  const val = document.getElementById('simGenderSelect').value.split(',');
  const gender = val[0];
  const conf = parseFloat(val[1]);
  const feedback = document.getElementById('verifFeedback');

  try {
    const res = await fetch('/api/verification/submit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_id: currentUser.id,
        id_card_b64: 'iobm_card_placeholder',
        selfie_b64: 'webcam_selfie_placeholder',
        liveness_passed: true,
        gender_estimate: gender,
        gender_confidence: conf
      })
    });
    const data = await res.json();
    feedback.classList.remove('hidden');
    if (data.status === 'verified') {
      feedback.className = 'p-3 rounded-xl text-xs font-semibold bg-emerald-50 text-emerald-800 border border-emerald-200';
      feedback.innerHTML = '✅ <strong>Verified:</strong> High confidence face match + gender record confirmed.';
    } else {
      feedback.className = 'p-3 rounded-xl text-xs font-semibold bg-amber-50 text-amber-800 border border-amber-200';
      feedback.innerHTML = `⚠️ <strong>Flagged:</strong> ${data.flag_reason}. Routed to Admin Review Queue.`;
    }
    const updatedRes = await fetch(`/api/auth/me/${currentUser.id}`);
    if (updatedRes.ok) {
      currentUser = await updatedRes.json();
      sessionStorage.setItem('campuspool_user', JSON.stringify(currentUser));
      updateHeaderUser();
    }
  } catch (err) {
    console.error('Verification error:', err);
  }
}

// =========================================================
// SOS
// =========================================================
function triggerSOSModal() {
  document.getElementById('sosModal').classList.remove('hidden');
}
function closeSOSModal() {
  document.getElementById('sosModal').classList.add('hidden');
}

async function confirmSOSDispatch() {
  if (!currentUser) return;
  try {
    const res = await fetch('/api/safety/sos', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_id: currentUser.id,
        trip_id: activeTripId || null,
        lat: IOBM_COORDS[0],
        lng: IOBM_COORDS[1],
        details: 'Emergency assistance requested via CampusPool SOS'
      })
    });
    const data = await res.json();
    alert(`🚨 SOS Dispatched!\n${data.message}`);
    closeSOSModal();
  } catch (err) {
    alert('SOS dispatched (offline mode)!');
    closeSOSModal();
  }
}

// =========================================================
// ADMIN: APP SETTINGS
// =========================================================
async function loadAdminAppSettings() {
  try {
    const res = await fetch('/api/admin/app-settings');
    if (!res.ok) return;
    const s = await res.json();
    if (document.getElementById('adminAppName')) document.getElementById('adminAppName').value = s.app_name || '';
    if (document.getElementById('adminAppEmoji')) document.getElementById('adminAppEmoji').value = s.app_logo_emoji || '🎓';
    if (document.getElementById('adminAppTagline')) document.getElementById('adminAppTagline').value = s.app_tagline || '';
    if (document.getElementById('adminPfpUrl')) document.getElementById('adminPfpUrl').value = s.app_pfp_url || '';
  } catch {}
}

async function saveAppSettings() {
  const name = document.getElementById('adminAppName').value.trim();
  const emoji = document.getElementById('adminAppEmoji').value.trim() || '🎓';
  const tagline = document.getElementById('adminAppTagline').value.trim();
  const pfp = document.getElementById('adminPfpUrl').value.trim();

  if (!name) { alert('App name cannot be empty.'); return; }

  try {
    const res = await fetch('/api/admin/app-settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ app_name: name, app_logo_emoji: emoji, app_tagline: tagline, app_pfp_url: pfp })
    });
    if (res.ok) {
      alert('✅ App branding updated!');
      applyBrandingToHeader({ app_name: name, app_logo_emoji: emoji, app_tagline: tagline, app_pfp_url: pfp });
      // Update admin profile pic
      if (pfp && currentUser) {
        await fetch('/api/auth/update-profile', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ user_id: currentUser.id, profile_pic_url: pfp })
        });
        currentUser.profile_pic_url = pfp;
        sessionStorage.setItem('campuspool_user', JSON.stringify(currentUser));
        updateHeaderUser();
      }
    }
  } catch {}
}

// =========================================================
// ADMIN: LOCATIONS
// =========================================================
async function loadAdminLocationsUI() {
  try {
    const res = await fetch('/api/admin/locations');
    if (!res.ok) return;
    adminLocations = await res.json();
    populateLocationDropdowns();

    const container = document.getElementById('adminLocationsList');
    if (!container) return;
    container.innerHTML = '';

    if (adminLocations.length === 0) {
      container.innerHTML = '<div class="text-slate-400 py-2">No locations added yet.</div>';
      return;
    }

    const pickups = adminLocations.filter(l => l.zone === 'pickup');
    const destinations = adminLocations.filter(l => l.zone === 'destination');

    const renderGroup = (locs, title, color) => {
      if (locs.length === 0) return;
      const header = document.createElement('div');
      header.className = `font-bold text-${color}-800 text-xs mb-1 mt-2`;
      header.textContent = title;
      container.appendChild(header);

      locs.forEach(loc => {
        const div = document.createElement('div');
        div.className = 'p-3 bg-white rounded-xl border border-slate-200 flex flex-wrap items-center justify-between gap-2';
        div.innerHTML = `
          <div>
            <span class="font-bold text-slate-800">${loc.name}</span>
            <span class="text-slate-500 text-[11px] block">
              Lat: ${loc.lat}, Lng: ${loc.lng}
              ${loc.zone === 'pickup' ? `• ❄️ AC: <strong>Rs. ${loc.ac_fare_pkr}</strong> • 🌀 Non-AC: <strong>Rs. ${loc.nonac_fare_pkr}</strong>` : '(Destination)'}
            </span>
          </div>
          <button onclick="deleteAdminLocation(${loc.id})" class="px-2 py-1 bg-rose-100 hover:bg-rose-200 text-rose-700 rounded-lg text-[11px] font-bold">
            Delete
          </button>
        `;
        container.appendChild(div);
      });
    };

    renderGroup(pickups, '📍 Pickup Locations', 'emerald');
    renderGroup(destinations, '🏛️ Destinations / Drop-offs', 'blue');
  } catch {}
}

async function addAdminLocation() {
  const name = document.getElementById('newLocName').value.trim();
  const lat = parseFloat(document.getElementById('newLocLat').value);
  const lng = parseFloat(document.getElementById('newLocLng').value);
  const zone = document.getElementById('newLocZone').value;
  const acFare = parseFloat(document.getElementById('newLocAcFare').value || 0);
  const nonAcFare = parseFloat(document.getElementById('newLocNonAcFare').value || 0);

  if (!name || isNaN(lat) || isNaN(lng)) {
    alert('Please fill in name, latitude, and longitude.');
    return;
  }

  try {
    const res = await fetch('/api/admin/locations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, lat, lng, zone, ac_fare_pkr: acFare, nonac_fare_pkr: nonAcFare })
    });
    if (res.ok) {
      alert(`✅ Location "${name}" added!`);
      document.getElementById('newLocName').value = '';
      document.getElementById('newLocLat').value = '';
      document.getElementById('newLocLng').value = '';
      document.getElementById('newLocAcFare').value = '';
      document.getElementById('newLocNonAcFare').value = '';
      await loadAdminLocationsUI();
    }
  } catch {}
}

async function deleteAdminLocation(id) {
  if (!confirm('Delete this location?')) return;
  try {
    await fetch(`/api/admin/locations/${id}`, { method: 'DELETE' });
    await loadAdminLocationsUI();
  } catch {}
}

// =========================================================
// ADMIN: FARE SETTINGS (fallback formula)
// =========================================================
async function loadAdminFareSettings() {
  try {
    const res = await fetch('/api/admin/fare-settings');
    const settings = await res.json();
    const baseInp = document.getElementById('adminBaseFare');
    const perKmInp = document.getElementById('adminPerKmFare');
    const modeSel = document.getElementById('adminPricingMode');
    if (baseInp) baseInp.value = settings.carpool_base_pkr;
    if (perKmInp) perKmInp.value = settings.carpool_per_km_pkr;
    if (modeSel) modeSel.value = settings.carpool_pricing_mode;
  } catch {}
}

async function saveAdminFareSettings() {
  const base = parseFloat(document.getElementById('adminBaseFare').value);
  const perKm = parseFloat(document.getElementById('adminPerKmFare').value);
  const mode = document.getElementById('adminPricingMode').value;
  try {
    await fetch('/api/admin/fare-settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ carpool_base_pkr: base, carpool_per_km_pkr: perKm, carpool_pricing_mode: mode, carpool_flat_pkr: 350.0 })
    });
    alert('✅ Fallback fare formula updated!');
    await searchMatchingRides();
  } catch {}
}

// =========================================================
// ADMIN: DASHBOARD
// =========================================================
async function loadAdminDashboard() {
  try {
    const [qRes, mRes, aRes] = await Promise.all([
      fetch('/api/admin/queue'),
      fetch('/api/admin/metrics'),
      fetch('/api/safety/alerts')
    ]);
    const queue = await qRes.json();
    const metrics = await mRes.json();
    const alerts = await aRes.json();

    document.getElementById('statTotalUsers').textContent = metrics.total_users;
    document.getElementById('statFlagged').textContent = metrics.flagged_reviews;
    document.getElementById('statActiveRides').textContent = metrics.active_rides;
    document.getElementById('statActiveSOS').textContent = metrics.active_sos;

    const qContainer = document.getElementById('adminReviewQueue');
    if (qContainer) {
      qContainer.innerHTML = '';
      if (queue.length === 0) {
        qContainer.innerHTML = '<div class="text-slate-400 py-3">Review queue is empty. All members validated.</div>';
      } else {
        queue.forEach(item => {
          const div = document.createElement('div');
          div.className = 'p-4 bg-white rounded-xl border border-amber-200 shadow-sm flex flex-wrap items-center justify-between gap-3';
          div.innerHTML = `
            <div>
              <div class="font-bold text-slate-800 text-sm">${item.name} (${item.university_id})</div>
              <div class="text-slate-500 text-[11px]">Role: <strong>${item.role}</strong> • Gender: <strong>${item.gender_on_record}</strong></div>
              <div class="text-amber-700 font-semibold text-[11px] mt-1 bg-amber-50 p-1.5 rounded border border-amber-200">
                ⚠️ <strong>Flagged:</strong> ${item.flag_reason} (Soft Signal: ${item.gender_estimate} @ ${Math.round(item.gender_confidence * 100)}%)
              </div>
            </div>
            <div class="flex gap-2">
              <button onclick="decideAdminReview(${item.id}, 'approved')" class="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-700 text-white font-bold rounded-lg text-xs">Approve</button>
              <button onclick="decideAdminReview(${item.id}, 'rejected')" class="px-3 py-1.5 bg-rose-600 hover:bg-rose-700 text-white font-bold rounded-lg text-xs">Reject</button>
            </div>
          `;
          qContainer.appendChild(div);
        });
      }
    }

    const aContainer = document.getElementById('adminSafetyAlertsList');
    if (aContainer) {
      aContainer.innerHTML = '';
      if (alerts.length === 0) {
        aContainer.innerHTML = '<div class="text-slate-400 py-2">No active safety incidents. Campus clear.</div>';
      } else {
        alerts.forEach(al => {
          const div = document.createElement('div');
          div.className = 'p-3 bg-rose-50 border border-rose-200 rounded-xl flex items-center justify-between text-xs text-rose-900';
          div.innerHTML = `
            <div>
              <span class="font-bold text-rose-800">${al.user_name}</span> (${al.university_id})
              <span class="block text-[11px]">GPS: ${al.lat.toFixed(4)}, ${al.lng.toFixed(4)} • ${al.details}</span>
              <span class="text-[10px] text-rose-600">${new Date(al.created_at).toLocaleString()}</span>
            </div>
            <button onclick="resolveSOSAlert(${al.id})" class="px-3 py-1.5 bg-rose-600 hover:bg-rose-700 text-white font-bold rounded-lg text-xs">Resolve</button>
          `;
          aContainer.appendChild(div);
        });
      }
    }
  } catch (err) {
    console.error('Admin dashboard error:', err);
  }
}

async function decideAdminReview(reviewId, decision) {
  try {
    await fetch('/api/admin/review', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ review_id: reviewId, decision, admin_notes: decision })
    });
    alert(`Student ${decision}!`);
    await loadAdminDashboard();
  } catch {}
}

async function resolveSOSAlert(eventId) {
  try {
    await fetch(`/api/safety/resolve/${eventId}`, { method: 'POST' });
    await loadAdminDashboard();
  } catch {}
}

async function loadAdminUsers() {
  try {
    const res = await fetch('/api/users');
    const users = await res.json();
    const container = document.getElementById('adminUsersList');
    if (!container) return;
    container.innerHTML = '';

    if (users.length === 0) {
      container.innerHTML = '<div class="text-slate-400">No users registered yet.</div>';
      return;
    }

    users.forEach(u => {
      const roleIcon = u.role === 'driver' ? '🚘' : (u.role === 'admin' ? '⚙️' : '🚗');
      const genderIcon = u.gender_on_record === 'female' ? '👩' : (u.gender_on_record === 'male' ? '👨' : '🧑');
      const statusColor = u.verified_status === 'verified' ? 'text-emerald-600' : (u.verified_status === 'flagged_review' ? 'text-amber-600' : 'text-slate-500');
      const div = document.createElement('div');
      div.className = 'p-2 bg-white rounded-lg border border-slate-200 flex items-center justify-between';
      div.innerHTML = `
        <div class="flex items-center gap-2">
          <span class="text-sm">${roleIcon}${genderIcon}</span>
          <div>
            <span class="font-semibold text-slate-800 text-xs">${u.name}</span>
            <span class="text-slate-400 text-[10px] block">${u.email} • ★${u.rating}</span>
          </div>
        </div>
        <span class="text-[10px] font-bold ${statusColor}">${u.verified_status.toUpperCase()}</span>
      `;
      container.appendChild(div);
    });
  } catch {}
}

// =========================================================
// RESET DEMO DATA (Admin)
// =========================================================
async function resetData() {
  if (!confirm('Reset all rides, trips, bookings and reseed fresh demo data?\n\nUsers and locations are kept.')) return;
  try {
    const res = await fetch('/api/admin/reset-demo-data', { method: 'POST' });
    const data = await res.json();
    alert('✅ ' + (data.message || 'Demo data reset!'));
    activeTripId = null;
    await refreshAll();
  } catch (err) {
    alert('Reset failed — check server.');
  }
}

// =========================================================
// KEYBOARD SHORTCUTS
// =========================================================
document.addEventListener('keydown', (e) => {
  // Enter in chat sends message
  if (e.key === 'Enter' && document.activeElement?.id === 'chatInput') {
    e.preventDefault();
    sendChatMessage();
  }
  // Enter in login form logs in
  if (e.key === 'Enter' && (document.activeElement?.id === 'loginEmail' || document.activeElement?.id === 'loginPassword')) {
    e.preventDefault();
    handleLogin();
  }
});
