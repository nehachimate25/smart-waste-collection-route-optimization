/* ==========================================================
   static/js/history.js
   Route -> Trip -> per-bin collection history, vehicle/route maps (stored
   road geometry) and compact chart cards.
   ========================================================== */

let history = { routes: [], legacy: [] };
const openMaps = {};

document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("btn-refresh-history").addEventListener("click", loadHistory);
    document.getElementById("chart-route").addEventListener("change", renderCharts);
    document.getElementById("chart-modal-close").addEventListener("click", () => document.getElementById("chart-modal").classList.add("hidden"));
    document.querySelectorAll(".chart-card").forEach(c => c.addEventListener("click", () => expandChart(c.dataset.chart)));
    loadHistory();
});

async function loadHistory() {
    const res = await api("/api/history");
    const list = document.getElementById("routes-list");
    if (!res.ok) { list.innerHTML = `<p class="empty-row error-text">${escapeHtml(res.error)}</p>`; return; }
    history = res.data;
    renderRoutes();
    renderLegacy();
    const done = history.routes.filter(r => r.status === "COMPLETED");
    const sel = document.getElementById("chart-route");
    const keep = sel.value;
    sel.innerHTML = history.routes.filter(r => r.collected_count > 0).map(r => `<option value="${escapeHtml(r.route_code)}">${escapeHtml(r.route_code)} (${escapeHtml(r.status)})</option>`).join("")
        || `<option value="">No route with collections yet</option>`;
    if ([...sel.options].some(o => o.value === keep)) sel.value = keep;
    else if (done.length) sel.value = done[0].route_code;
    renderCharts();
}

/* ------------------------------------------------------------- list ---- */

function statusBadge(status) {
    const cls = { COMPLETED: "badge-low", IN_PROGRESS: "badge-high", ASSIGNED: "badge-medium", CANCELLED: "badge-critical", SUPERSEDED: "badge-critical" }[status] || "badge-medium";
    return `<span class="badge ${cls}">${escapeHtml(status.replace("_", " "))}</span>`;
}

function renderRoutes() {
    const list = document.getElementById("routes-list");
    if (!history.routes.length) { list.innerHTML = `<div class="card"><p class="empty-row">No routes yet. Create one on the Add Bins &amp; Route page.</p></div>`; return; }
    list.innerHTML = history.routes.map(r => `
        <div class="card route-acc" id="acc-${escapeHtml(r.route_code)}">
            <div class="route-acc-head" data-code="${escapeHtml(r.route_code)}">
                <strong style="font-size:1.05rem">Route #${escapeHtml(r.route_code)}</strong>
                <span class="ds-meta">${escapeHtml(r.label)}</span>
                ${statusBadge(r.status)}
                <span class="grow ds-meta">${formatDateTime(r.created_at)} · ${escapeHtml(r.vehicle.vehicle_number || r.vehicle_id)} · ${escapeHtml(r.collector ? r.collector.name : "-")}</span>
                <span>${r.total_trips} trip(s) · ${r.total_bins} bin(s) · ${fmtKg(r.total_waste)} · ${fmtKm(r.total_distance)} · ${fmtMin(r.total_time_min)}</span>
                <span>&#9662;</span>
            </div>
            <div class="route-acc-body">${routeBody(r)}</div>
        </div>`).join("");
    document.querySelectorAll(".route-acc-head").forEach(h => h.addEventListener("click", () => toggleRoute(h.dataset.code)));
    document.querySelectorAll("[data-map]").forEach(b => b.addEventListener("click", () => showMap(b.dataset.map)));
}

function routeBody(r) {
    const versions = r.versions.length > 1
        ? `<p class="ds-meta">Versions: ${r.versions.map(v => `${escapeHtml(v.route_code)} (${v.version === 1 ? "Original" : "Updated"}, ${escapeHtml(v.status)})`).join(" → ")}</p>` : "";
    return `${versions}
        <p><button class="btn btn-small" data-map="${escapeHtml(r.route_code)}">Show road route on map</button>
        <span class="ds-meta">Priority mode: ${escapeHtml(r.priority_mode || "-")}</span></p>
        <div id="map-wrap-${escapeHtml(r.route_code)}"></div>
        ${r.trips.map(tripBlock).join("")}`;
}

function tripBlock(t) {
    const bins = t.steps.filter(s => s.step_type === "BIN");
    const chain = ["Depot", ...bins.map(b => b.location_name), "Depot"].map(escapeHtml).join(" &rarr; ");
    const ev = t.depot_event;
    return `
    <div class="trip-block">
        <div class="trip-head"><strong>Trip ${t.trip_number}</strong> ${statusBadge(t.status)}
            <span class="ds-meta">${fmtKg(t.planned_waste_kg)} of ${fmtKg(t.capacity_kg)} · ${fmtKm(t.total_distance_km)} · ${fmtMin(t.total_time_min)}</span></div>
        <p class="ds-meta">${chain}</p>
        <table class="data-table step-table">
            <thead><tr><th>#</th><th>Bin</th><th>Priority</th><th>Collected at</th><th>Waste</th><th>Distance travelled</th><th>Segment</th><th>Est. time</th><th>Actual time</th><th>Load after</th></tr></thead>
            <tbody>${bins.map(s => `
                <tr><td>${s.sequence_number}</td><td>${escapeHtml(s.location_name)}</td>
                <td><span class="badge ${priorityBadgeClass(s.priority)}">${escapeHtml(s.priority || "")}</span></td>
                <td>${s.collected_at ? formatTime(s.collected_at) : `<span class="ds-meta">${escapeHtml(s.status.toLowerCase())}</span>`}</td>
                <td>${fmtKg(s.waste_collected_kg !== undefined ? s.waste_collected_kg : s.planned_waste_kg)}</td>
                <td>${fmtKm(s.cumulative_distance_km)}</td><td>${fmtKm(s.segment_distance_km)}</td>
                <td>${fmtMin(s.segment_time_min)}</td><td>${s.actual_time_min !== null && s.actual_time_min !== undefined ? s.actual_time_min + " min" : "-"}</td>
                <td>${fmtKg(s.actual_load_after_kg !== null && s.actual_load_after_kg !== undefined ? s.actual_load_after_kg : s.load_after_kg)}</td></tr>`).join("")}
            </tbody>
        </table>
        ${ev ? `<p class="depot-panel"><strong>Return to Depot</strong> — ${fmtKm(ev.return_distance_km)} · ${fmtMin(ev.return_time_min)} ·
            waste unloaded ${fmtKg(ev.unloaded_kg)} · vehicle load ${fmtKg(ev.vehicle_load_after_kg)} · ${formatTime(ev.occurred_at)}
            <span class="ds-meta">(${ev.reason === "CAPACITY" ? "vehicle full, continued with next trip" : "final return"})</span></p>`
            : `<p class="ds-meta">Return to depot: ${fmtKm(t.steps[t.steps.length - 1].segment_distance_km)} · ${fmtMin(t.steps[t.steps.length - 1].segment_time_min)} (planned)</p>`}
    </div>`;
}

function toggleRoute(code) {
    document.getElementById(`acc-${code}`).classList.toggle("open");
}

async function showMap(code) {
    const wrap = document.getElementById(`map-wrap-${code}`);
    if (openMaps[code]) { openMaps[code].remove(); delete openMaps[code]; wrap.innerHTML = ""; return; }
    const res = await api(`/api/routes/${code}`);
    if (!res.ok) { showToast(res.error, "error"); return; }
    wrap.innerHTML = `<div class="history-map" id="map-${code}"></div>`;
    const map = L.map(`map-${code}`);
    openMaps[code] = map;
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { attribution: "&copy; OpenStreetMap contributors", maxZoom: 19 }).addTo(map);
    const group = L.layerGroup().addTo(map);
    const r = res.data;
    const { bounds, missing } = RouteView.drawTrips(map, group, r.trips);
    L.marker([r.depot_latitude, r.depot_longitude], { icon: RouteView.depotIcon() }).addTo(map).bindTooltip(r.depot_name);
    r.trips.forEach(t => t.steps.filter(s => s.step_type === "BIN").forEach(s =>
        L.marker([s.latitude, s.longitude], { icon: RouteView.binIcon(s.sequence_number, s.priority) }).addTo(map).bindTooltip(s.location_name)));
    if (bounds) map.fitBounds(bounds.pad(0.15)); else map.setView([r.depot_latitude, r.depot_longitude], 14);
    if (missing) showToast(`${missing} segment(s) have no stored road geometry.`, "info");
}

function renderLegacy() {
    const el = document.getElementById("legacy-section");
    if (!history.legacy.length) { el.innerHTML = ""; return; }
    el.innerHTML = `<div class="card"><h3>Earlier collections (original one-shot pipeline)</h3>
        <table class="data-table"><thead><tr><th>Date</th><th>Vehicle</th><th>Bins</th><th>Waste</th><th>Distance (straight-line, legacy)</th></tr></thead><tbody>
        ${history.legacy.map(h => `<tr><td>${escapeHtml(h.date)}</td><td><code>${escapeHtml(h.vehicle_id)}</code></td><td>${h.collected_bins.length}</td><td>${fmtKg(h.total_waste)}</td><td>${fmtKm(h.total_distance)}</td></tr>`).join("")}
        </tbody></table></div>`;
}

/* ----------------------------------------------------------- charts ---- */

function chartHtml(kind) {
    const done = history.routes.filter(r => r.status === "COMPLETED").slice().reverse().slice(-10);
    const selected = history.routes.find(r => r.route_code === document.getElementById("chart-route").value);
    const steps = selected ? selected.trips.flatMap(t => t.steps) : [];
    switch (kind) {
        case "distance": return Charts.bar({ labels: done.map(r => r.route_code), values: done.map(r => r.total_distance), unit: "km", color: "#3b82f6" });
        case "waste": return Charts.bar({ labels: done.map(r => r.route_code), values: done.map(r => r.total_waste), unit: "kg", color: "#22c55e" });
        case "time": return Charts.bar({ labels: done.map(r => r.route_code), values: done.map(r => r.total_time_min), unit: "min", color: "#f59e0b" });
        case "trips": {
            const per = {};
            history.routes.forEach(r => r.trips.filter(t => t.status === "COMPLETED").forEach(() => {
                const k = r.vehicle.vehicle_number || r.vehicle_id; per[k] = (per[k] || 0) + 1;
            }));
            return Charts.bar({ labels: Object.keys(per), values: Object.values(per), unit: "trips", color: "#a855f7" });
        }
        case "sequence": {
            const items = steps.filter(s => s.step_type === "BIN" && s.status === "COLLECTED").sort((a, b) => (a.collected_at || "").localeCompare(b.collected_at || ""))
                .map(s => ({ label: s.location_name, time: formatTime(s.collected_at), sub: `${fmtKg(s.waste_collected_kg)} · ${fmtKm(s.cumulative_distance_km)} travelled`, color: PRIORITY_HEX[s.priority] }));
            return Charts.timeline(items);
        }
        case "load": {
            const labels = [], values = [];
            (selected ? selected.trips : []).forEach(t => t.steps.forEach(s => {
                if (s.step_type === "DEPOT_START") { labels.push("Start"); values.push(s.load_after_kg); }
                else if (s.step_type === "BIN" && s.status === "COLLECTED") { labels.push(s.location_name); values.push(s.actual_load_after_kg !== null && s.actual_load_after_kg !== undefined ? s.actual_load_after_kg : s.load_after_kg); }
                else if (s.step_type === "DEPOT_RETURN" && s.status === "DONE") { labels.push("Depot"); values.push(0); }
            }));
            return Charts.line({ labels, values, unit: "kg", color: "#22d3ee" });
        }
    }
    return "";
}

function renderCharts() {
    document.querySelectorAll(".chart-card").forEach(c => { c.querySelector(".chart-body").innerHTML = chartHtml(c.dataset.chart); });
}

function expandChart(kind) {
    const card = document.querySelector(`.chart-card[data-chart="${kind}"]`);
    document.getElementById("chart-modal-title").textContent = card.querySelector("h4").firstChild.textContent.trim();
    document.getElementById("chart-modal-body").innerHTML = chartHtml(kind);
    document.getElementById("chart-modal").classList.remove("hidden");
}
