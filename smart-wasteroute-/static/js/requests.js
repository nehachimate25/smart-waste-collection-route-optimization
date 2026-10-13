/* ==========================================================
   static/js/requests.js
   Add pending bins to an existing saved route. The result is ALWAYS a new
   route version (R001 -> R001-V2); the old route stays in History.
   ========================================================== */

let routes = [], pending = [], plan = null, map, routeLayer, binLayer;

document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("btn-refresh-requests").addEventListener("click", loadAll);
    document.getElementById("route-select").addEventListener("change", () => { clearPreview(); renderRouteInfo(); updateButtons(); });
    document.getElementById("btn-update-route").addEventListener("click", generate);
    document.getElementById("btn-regenerate").addEventListener("click", generate);
    document.getElementById("btn-save-version").addEventListener("click", saveVersion);
    document.getElementById("btn-cancel-route").addEventListener("click", cancelRoute);
    loadAll();
});

function selectedRoute() {
    const code = document.getElementById("route-select").value;
    return routes.find(r => r.route_code === code) || null;
}

async function loadAll() {
    clearPreview();
    const [r, p, q] = await Promise.all([api("/api/routes?status=ASSIGNED"), api("/api/requests/pending"), api("/api/requests/priority")]);
    routes = r.ok ? r.data : [];
    pending = p.ok ? p.data.filter(i => i.bin && i.bin.status === "ACTIVE") : [];

    const sel = document.getElementById("route-select");
    const keep = sel.value;
    sel.innerHTML = routes.length
        ? `<option value="">— select a route —</option>` + routes.map(x =>
            `<option value="${escapeHtml(x.route_code)}">${escapeHtml(x.route_code)} — ${escapeHtml(x.label)} · ${x.total_bins} bin(s) · ${escapeHtml(x.vehicle.vehicle_number)}</option>`).join("")
        : `<option value="">No saved route can be updated right now</option>`;
    if (routes.find(x => x.route_code === keep)) sel.value = keep;

    renderPending();
    renderPriority(q);
    renderRouteInfo();
    updateButtons();
}

function renderRouteInfo() {
    const el = document.getElementById("route-info");
    const r = selectedRoute();
    if (!r) { el.innerHTML = ""; return; }
    const names = r.trips.flatMap(t => t.steps.filter(s => s.step_type === "BIN").map(s => s.location_name));
    el.innerHTML = `<p><strong>${escapeHtml(r.route_code)} — ${escapeHtml(r.label)}</strong> · Collector ${escapeHtml(r.collector ? r.collector.name : "-")} ·
        ${r.total_trips} trip(s) · ${fmtKg(r.total_waste)} · ${fmtKm(r.total_distance)} · ${fmtMin(r.total_time_min)}<br>
        <span class="ds-meta">Bins: ${names.map(escapeHtml).join(" → ")}</span></p>`;
}

function renderPending() {
    const tbody = document.getElementById("pending-table-body");
    if (!pending.length) {
        tbody.innerHTML = `<tr><td colspan="6" class="empty-row">No pending bins. Add new bins on the Add Bins &amp; Route page.</td></tr>`;
        return;
    }
    tbody.innerHTML = pending.map((i, n) => `
        <tr><td><input type="checkbox" class="pick" value="${escapeHtml(i.bin_id)}"></td><td>${n + 1}</td>
        <td>${escapeHtml(i.bin.name)}</td><td>${Number(i.bin.waste_level).toFixed(0)}%</td><td>${fmtKg(i.bin.current_waste_kg)}</td>
        <td><span class="badge ${priorityBadgeClass(i.bin.priority)}">${i.bin.priority}</span></td></tr>`).join("");
    tbody.querySelectorAll(".pick").forEach(c => c.addEventListener("change", () => { clearPreview(); updateButtons(); }));
}

function renderPriority(res) {
    const tbody = document.getElementById("priority-table-body");
    const note = document.getElementById("stale-requests-note");
    if (!res.ok || !res.data.priority_order.length) {
        tbody.innerHTML = `<tr><td colspan="4" class="empty-row">Nothing pending.</td></tr>`;
        note.classList.add("hidden");
        return;
    }
    tbody.innerHTML = res.data.priority_order.map((i, n) => `
        <tr><td>${n + 1}</td><td>${escapeHtml(i.bin.name)}</td><td>${Number(i.bin.waste_level).toFixed(0)}%</td>
        <td><span class="badge ${priorityBadgeClass(i.bin.priority)}">${i.bin.priority}</span></td></tr>`).join("");
    const stale = res.data.stale_requests;
    note.classList.toggle("hidden", !stale.length);
    if (stale.length) note.textContent = `${stale.length} stale request(s) (bin collected or deleted) will be cleared on the next route.`;
}

function pickedIds() { return [...document.querySelectorAll(".pick:checked")].map(c => c.value); }

function updateButtons() {
    const r = selectedRoute();
    document.getElementById("btn-update-route").disabled = !r || !pickedIds().length;
    document.getElementById("btn-cancel-route").disabled = !r;
    document.getElementById("update-hint").textContent = !r ? "Select a route." : !pickedIds().length ? "Tick at least one pending bin." : "";
}

function ensureMap() {
    if (map) return;
    map = L.map("preview-map").setView([18.5204, 73.8567], 13);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { attribution: "&copy; OpenStreetMap contributors", maxZoom: 19 }).addTo(map);
    routeLayer = L.layerGroup().addTo(map);
    binLayer = L.layerGroup().addTo(map);
}

function clearPreview() {
    plan = null;
    document.getElementById("preview-section").style.display = "none";
}

async function generate() {
    const r = selectedRoute();
    if (!r) return;
    const btn = document.getElementById("btn-update-route");
    btn.disabled = true; btn.textContent = "Recalculating...";
    const res = await apiJson("/api/planning/generate", "POST", { base_route_code: r.route_code, bin_ids: pickedIds() });
    btn.textContent = "Update Route"; updateButtons();
    const section = document.getElementById("preview-section");
    section.style.display = "";
    ensureMap(); map.invalidateSize();
    const warn = document.getElementById("preview-warning");
    if (!res.ok) {
        plan = null; routeLayer.clearLayers(); binLayer.clearLayers();
        document.getElementById("preview-summary").innerHTML = "";
        document.getElementById("btn-save-version").disabled = true;
        warn.innerHTML = `<div class="warn-box">&#9888; ${escapeHtml(res.error)}${res.body && res.body.osrm_unavailable ? " No route is drawn - retry shortly." : ""}</div>`;
        return;
    }
    plan = res.data;
    warn.innerHTML = "";
    document.getElementById("btn-save-version").disabled = false;
    document.getElementById("preview-summary").innerHTML =
        `<p class="status-box">Preview of a NEW VERSION of <strong>${escapeHtml(r.route_code)}</strong> — the original ${escapeHtml(r.route_code)} stays untouched until you save.</p>` +
        RouteView.summaryHtml(plan, { title: "UPDATED COLLECTION ROUTE" });
    const { bounds } = RouteView.drawTrips(map, routeLayer, plan.trips);
    binLayer.clearLayers();
    L.marker([plan.depot.latitude, plan.depot.longitude], { icon: RouteView.depotIcon() }).addTo(binLayer);
    plan.trips.forEach(t => t.steps.filter(s => s.step_type === "BIN").forEach(s =>
        L.marker([s.latitude, s.longitude], { icon: RouteView.binIcon(s.sequence_number, s.priority) }).addTo(binLayer).bindTooltip(s.location_name)));
    if (bounds) map.fitBounds(bounds.pad(0.15));
    section.scrollIntoView({ behavior: "smooth" });
}

async function saveVersion() {
    if (!plan) return;
    const res = await apiJson("/api/planning/save", "POST", { draft_token: plan.draft_token });
    if (!res.ok) { showToast(res.error, "error"); return; }
    showToast(`Saved ${res.data.route_code}. The original route is kept in History.`, "success");
    document.getElementById("preview-summary").innerHTML = RouteView.summaryHtml(res.data, { title: "SAVED UPDATED ROUTE" });
    document.getElementById("btn-save-version").disabled = true;
    document.getElementById("btn-regenerate").disabled = true;
    loadAllKeepPreview();
}

async function loadAllKeepPreview() {
    const [r, p, q] = await Promise.all([api("/api/routes?status=ASSIGNED"), api("/api/requests/pending"), api("/api/requests/priority")]);
    routes = r.ok ? r.data : []; pending = p.ok ? p.data.filter(i => i.bin && i.bin.status === "ACTIVE") : [];
    document.getElementById("route-select").innerHTML = routes.map(x => `<option value="${escapeHtml(x.route_code)}">${escapeHtml(x.route_code)} — ${escapeHtml(x.label)}</option>`).join("");
    renderPending(); renderPriority(q); updateButtons();
}

async function cancelRoute() {
    const r = selectedRoute();
    if (!r || !confirm(`Cancel ${r.route_code}? Its bins go back to the pending queue and the vehicle is freed.`)) return;
    const res = await apiJson(`/api/routes/${r.route_code}/cancel`, "POST");
    if (!res.ok) { showToast(res.error, "error"); return; }
    showToast(`${r.route_code} cancelled.`, "success");
    loadAll();
}
