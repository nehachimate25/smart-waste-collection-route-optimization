/* ==========================================================
   static/js/collector_dashboard.js
   Collector: today's assignment, bin-by-bin collection (Start Collection ->
   Mark Collected), return-to-depot per trip, own vehicle management, route
   list/history and profile. The backend enforces the sequence; this page only
   shows it clearly.
   ========================================================== */

let route = null, vehicle = null, map, routeLayer, markerLayer;

document.addEventListener("DOMContentLoaded", () => {
    map = L.map("collector-map").setView([18.5204, 73.8567], 12);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { attribution: "&copy; OpenStreetMap contributors", maxZoom: 19 }).addTo(map);
    routeLayer = L.layerGroup().addTo(map);
    markerLayer = L.layerGroup().addTo(map);
    document.getElementById("btn-refresh").addEventListener("click", loadAll);
    loadAll();
});

async function loadAll() {
    const me = await api("/api/auth/me");
    if (me.data && me.data.role === "collector") document.getElementById("collector-welcome").textContent = `Welcome, ${me.data.name}`;
    const [r, v] = await Promise.all([api("/api/collector/my-route"), api("/api/collector/vehicle")]);
    route = r.ok ? r.data : null;
    vehicle = v.ok ? v.data : null;
    renderAssignment(); renderSequence(); renderMap(); renderVehicle();
    loadRoutes(); loadProfile();
}

function currentTrip() { return route ? route.trips.find(t => t.status !== "COMPLETED") : null; }
function nextStep(trip) { return trip ? trip.steps.find(s => s.step_type === "BIN" && s.status !== "COLLECTED") : null; }

/* ------------------------------------------------------- assignment ---- */

function renderAssignment() {
    const el = document.getElementById("assignment-card");
    if (!route) {
        el.innerHTML = `<p class="empty-row">No route assigned right now. ${vehicle ? "" : "Register your vehicle below so users can assign routes to you."}</p>`;
        return;
    }
    const v = route.vehicle;
    el.innerHTML = `
        <h3>Route ${escapeHtml(route.route_code)} <span class="ds-meta">${escapeHtml(route.label)}</span></h3>
        <div class="summary-grid">
            <div><span class="ds-meta">Vehicle</span><br><strong>${escapeHtml(v.vehicle_number)}</strong></div>
            <div><span class="ds-meta">Capacity</span><br><strong>${fmtKg(v.maximum_capacity_kg)}</strong></div>
            <div><span class="ds-meta">Assigned waste</span><br><strong>${fmtKg(route.total_waste)}</strong></div>
            <div><span class="ds-meta">Bins</span><br><strong>${route.collected_count} / ${route.total_bins}</strong></div>
            <div><span class="ds-meta">Trips</span><br><strong>${route.total_trips}</strong></div>
            <div><span class="ds-meta">Estimated distance</span><br><strong>${fmtKm(route.total_distance)}</strong></div>
            <div><span class="ds-meta">Estimated time</span><br><strong>${fmtMin(route.total_time_min)}</strong></div>
            <div><span class="ds-meta">Status</span><br><strong>${escapeHtml(route.status.replace("_", " "))}</strong></div>
        </div>
        <p class="ds-meta">Current vehicle load</p>
        <div class="load-bar"><div style="width:${Math.min(100, 100 * v.current_load_kg / v.maximum_capacity_kg)}%"></div></div>
        <p class="ds-meta">${fmtKg(v.current_load_kg)} / ${fmtKg(v.maximum_capacity_kg)}</p>`;
}

function renderSequence() {
    const el = document.getElementById("sequence-card");
    if (!route) { el.style.display = "none"; return; }
    el.style.display = "";
    const cur = currentTrip();
    const next = nextStep(cur);
    el.innerHTML = `<h3>Collection Sequence</h3>` + route.trips.map(t => {
        const bins = t.steps.filter(s => s.step_type === "BIN");
        const isCur = cur && t.trip_number === cur.trip_number;
        const allDone = bins.every(s => s.status === "COLLECTED");
        const ret = t.steps.find(s => s.step_type === "DEPOT_RETURN");
        return `
        <h4 style="margin:.8rem 0 .4rem">Trip ${t.trip_number} <span class="ds-meta">${fmtKg(t.planned_waste_kg)} · ${fmtKm(t.total_distance_km)} · ${fmtMin(t.total_time_min)}</span>
            ${t.status === "COMPLETED" ? '<span class="badge badge-low">COMPLETED</span>' : isCur ? '<span class="badge badge-high">CURRENT</span>' : '<span class="badge badge-medium">WAITING</span>'}</h4>
        ${bins.map(s => stopRow(s, isCur && next && s.id === next.id)).join("")}
        ${isCur && allDone ? depotPanel(t, ret) : `<div class="stop-row ${t.status === "COMPLETED" ? "done" : "pending"}"><div class="grow">&#127981; Return to Depot <span class="ds-meta">${fmtKm(ret.segment_distance_km)} · ${fmtMin(ret.segment_time_min)}</span></div>
            ${t.status === "COMPLETED" && t.depot_event ? `<span class="ds-meta">unloaded ${fmtKg(t.depot_event.unloaded_kg)} at ${formatTime(t.depot_event.occurred_at)}</span>` : ""}</div>`}`;
    }).join("");
    el.querySelectorAll("[data-start]").forEach(b => b.addEventListener("click", () => action("start-collection", { bin_id: b.dataset.start })));
    el.querySelectorAll("[data-collect]").forEach(b => b.addEventListener("click", () => action("collect-stop", { bin_id: b.dataset.collect })));
    el.querySelectorAll("[data-depot]").forEach(b => b.addEventListener("click", () => action("return-to-depot", {})));
}

function stopRow(s, isNext) {
    const cls = s.status === "COLLECTED" ? "done" : isNext ? "next" : "pending";
    let right = "";
    if (s.status === "COLLECTED") right = `<span>&#9989; Collected ${formatTime(s.collected_at)}</span>`;
    else if (isNext && s.status === "IN_PROGRESS") right = `<button class="btn btn-primary" data-collect="${escapeHtml(s.bin_id)}">Mark Collected</button>`;
    else if (isNext) right = `<button class="btn btn-primary" data-start="${escapeHtml(s.bin_id)}">Start Collection</button>`;
    else right = `<span class="ds-meta">${s.status === "IN_PROGRESS" ? "in progress" : "waiting"}</span>`;
    return `
    <div class="stop-row ${cls}">
        <div class="grow"><strong>${s.sequence_number}. ${escapeHtml(s.location_name)}</strong>
            <span class="badge ${priorityBadgeClass(s.priority)}">${escapeHtml(s.priority || "")}</span>
            ${isNext ? '<span class="badge badge-high">NEXT</span>' : ""}<br>
            <span class="ds-meta">${fmtKg(s.planned_waste_kg)} · ${fmtKm(s.segment_distance_km)} from previous · ${fmtMin(s.segment_time_min)} · load after ${fmtKg(s.load_after_kg)}</span></div>
        ${right}
    </div>`;
}

function depotPanel(t, ret) {
    const more = route.trips.some(x => x.trip_number > t.trip_number);
    return `<div class="depot-panel"><strong>&#127981; Return to Depot</strong> — ${fmtKm(ret.segment_distance_km)} · ${fmtMin(ret.segment_time_min)}<br>
        ${more ? "Vehicle full - unload, then the next trip starts." : "All bins collected - final return."}
        Waste to unload: <strong>${fmtKg(vehicle ? vehicle.current_load_kg : t.planned_waste_kg)}</strong><br>
        <button class="btn btn-primary" style="margin-top:.5rem" data-depot="1">Arrived at Depot &mdash; Unload</button></div>`;
}

async function action(endpoint, extra) {
    const res = await apiJson(`/api/collector/${endpoint}`, "POST", { route_code: route.route_code, ...extra });
    if (!res.ok) { showToast(res.error, "error"); return; }
    if (endpoint === "collect-stop") showToast("Bin collected.", "success");
    if (endpoint === "return-to-depot") showToast(res.data.status === "COMPLETED" ? "Route completed. Well done!" : "Vehicle unloaded. Next trip is ready.", "success");
    loadAll();
}

/* -------------------------------------------------------------- map ---- */

function renderMap() {
    routeLayer.clearLayers(); markerLayer.clearLayers();
    if (!route) return;
    const cur = currentTrip();
    const { bounds } = RouteView.drawTrips(map, routeLayer, route.trips, cur ? cur.trip_number : null);
    L.marker([route.depot_latitude, route.depot_longitude], { icon: RouteView.depotIcon() }).addTo(markerLayer).bindTooltip(route.depot_name);
    const next = nextStep(cur);
    route.trips.forEach(t => t.steps.filter(s => s.step_type === "BIN").forEach(s => {
        const icon = RouteView.binIcon(s.status === "COLLECTED" ? "✓" : s.sequence_number, s.priority, next && next.id === s.id ? "map-pin-next" : "");
        L.marker([s.latitude, s.longitude], { icon }).addTo(markerLayer).bindTooltip(s.location_name);
    }));
    setTimeout(() => { map.invalidateSize(); if (bounds) map.fitBounds(bounds.pad(0.15)); }, 50);
}

/* ---------------------------------------------------------- vehicle ---- */

function renderVehicle() {
    const el = document.getElementById("vehicle-card");
    if (!vehicle) {
        el.innerHTML = `<p>You have no vehicle yet. Register the vehicle you drive:</p>
            <div class="inline-form">
                <div><label>Vehicle name / number</label><input id="v-number" placeholder="MH-12-AB-1234"></div>
                <div><label>Vehicle type</label><input id="v-type" placeholder="Waste Collector Van"></div>
                <div><label>Maximum capacity (kg)</label><input id="v-cap" type="number" min="1" step="any" value="500"></div>
            </div>
            <div class="form-actions" style="margin-top:.8rem"><button class="btn btn-primary" id="v-create">Register Vehicle</button></div>`;
        document.getElementById("v-create").addEventListener("click", async () => {
            const res = await apiJson("/api/collector/vehicle", "POST", {
                vehicle_number: v("v-number"), vehicle_type: v("v-type"), maximum_capacity_kg: v("v-cap") });
            if (!res.ok) showToast(res.error, "error"); else { showToast("Vehicle registered.", "success"); loadAll(); }
        });
        return;
    }
    const locked = vehicle.status === "ON ROUTE" || vehicle.status === "FULL";
    el.innerHTML = `
        <div class="summary-grid">
            <div><span class="ds-meta">Assigned collector</span><br><strong>${escapeHtml(vehicle.collector ? vehicle.collector.name : "-")}</strong></div>
            <div><span class="ds-meta">Current loaded waste</span><br><strong>${fmtKg(vehicle.current_load_kg)}</strong></div>
            <div><span class="ds-meta">Available capacity</span><br><strong>${fmtKg(vehicle.available_capacity_kg)}</strong></div>
            <div><span class="ds-meta">Status</span><br><strong>${escapeHtml(vehicle.status)}</strong></div>
        </div>
        <div class="inline-form">
            <div><label>Vehicle name / number</label><input id="v-number" value="${escapeHtml(vehicle.vehicle_number)}"></div>
            <div><label>Vehicle type</label><input id="v-type" value="${escapeHtml(vehicle.vehicle_type || "")}"></div>
            <div><label>Maximum capacity (kg)</label><input id="v-cap" type="number" min="1" step="any" value="${vehicle.maximum_capacity_kg}" ${locked ? "disabled" : ""}></div>
            <div><label>Current load (kg)</label><input id="v-load" type="number" min="0" step="any" value="${vehicle.current_load_kg}" ${locked ? "disabled" : ""}></div>
            <div><label>Status</label><select id="v-status" ${locked ? "disabled" : ""}>
                <option ${vehicle.status === "AVAILABLE" ? "selected" : ""}>AVAILABLE</option>
                <option ${vehicle.status === "MAINTENANCE" ? "selected" : ""}>MAINTENANCE</option>
                ${locked ? `<option selected>${escapeHtml(vehicle.status)}</option>` : ""}</select></div>
        </div>
        ${locked ? '<p class="ds-meta">Capacity, load and status are locked while the vehicle is on a route.</p>' : ""}
        <div class="form-actions" style="margin-top:.8rem"><button class="btn btn-primary" id="v-save">Save vehicle information</button></div>`;
    document.getElementById("v-save").addEventListener("click", async () => {
        const body = { vehicle_number: v("v-number"), vehicle_type: v("v-type") };
        if (!locked) { body.maximum_capacity_kg = v("v-cap"); body.current_load_kg = v("v-load"); body.status = v("v-status"); }
        const res = await apiJson("/api/collector/vehicle", "PUT", body);
        if (!res.ok) showToast(res.error, "error"); else { showToast("Vehicle updated.", "success"); loadAll(); }
    });
}

function v(id) { return document.getElementById(id).value; }

/* ------------------------------------------------ routes & history ------ */

async function loadRoutes() {
    const res = await api("/api/collector/routes");
    const assigned = document.getElementById("assigned-card"), hist = document.getElementById("history-card");
    if (!res.ok) { assigned.innerHTML = hist.innerHTML = `<p class="error-text">${escapeHtml(res.error)}</p>`; return; }
    const active = res.data.filter(r => ["ASSIGNED", "IN_PROGRESS"].includes(r.status));
    const past = res.data.filter(r => !["ASSIGNED", "IN_PROGRESS"].includes(r.status));
    assigned.innerHTML = active.length ? active.map(r => `
        <div class="route-summary-row"><span><strong>${escapeHtml(r.route_code)}</strong> ${escapeHtml(r.label)} · ${r.total_bins} bin(s) · ${r.total_trips} trip(s) · ${fmtKm(r.total_distance)} · ${fmtMin(r.total_time_min)}</span>
        <span class="badge badge-high">${escapeHtml(r.status.replace("_", " "))}</span></div>`).join("") : `<p class="empty-row">No active assignments.</p>`;
    hist.innerHTML = past.length ? `<table class="data-table"><thead><tr><th>Route</th><th>Status</th><th>Started</th><th>Completed</th><th>Trips</th><th>Bins</th><th>Waste</th><th>Distance</th></tr></thead><tbody>
        ${past.map(r => `<tr><td>${escapeHtml(r.route_code)} <span class="ds-meta">${escapeHtml(r.label)}</span></td><td>${escapeHtml(r.status)}</td><td>${formatDateTime(r.started_at)}</td><td>${formatDateTime(r.completed_at)}</td>
        <td>${r.total_trips}</td><td>${r.collected_count}/${r.total_bins}</td><td>${fmtKg(r.total_waste)}</td><td>${fmtKm(r.total_distance)}</td></tr>`).join("")}</tbody></table>`
        : `<p class="empty-row">No finished routes yet.</p>`;
}

async function loadProfile() {
    const res = await api("/api/collector/profile");
    const el = document.getElementById("profile-card");
    if (!res.ok) { el.innerHTML = `<p class="error-text">${escapeHtml(res.error)}</p>`; return; }
    const c = res.data;
    el.innerHTML = `<p>Collector ID: <strong>${escapeHtml(c.collector_code)}</strong></p>
        <div class="inline-form"><div><label>Name</label><input id="p-name" value="${escapeHtml(c.name)}"></div>
        <div><label>Mobile</label><input id="p-mobile" value="${escapeHtml(c.mobile)}"></div></div>
        <div class="form-actions" style="margin-top:.8rem"><button class="btn btn-primary" id="p-save">Save profile</button></div>`;
    document.getElementById("p-save").addEventListener("click", async () => {
        const r = await apiJson("/api/collector/profile", "PUT", { name: v("p-name"), mobile: v("p-mobile") });
        if (!r.ok) showToast(r.error, "error"); else { showToast("Profile updated.", "success"); loadAll(); }
    });
}
