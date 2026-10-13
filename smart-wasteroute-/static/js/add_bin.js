/* ==========================================================
   static/js/add_bin.js
   ONE workflow:  depot -> click bins on the map -> waste details ->
   priority analysis -> vehicle -> generate (OSRM road route) -> save.

   Bins added in this session are real bins (created through /api/bins, so
   they join the pending-requests Queue); the session is just the list of
   their ids (kept in sessionStorage so a page refresh doesn't lose it).
   All distances/times/priorities come from the server - nothing is
   computed or hard-coded here (including minutes-per-km).
   ========================================================== */

const SESSION_KEY = "planBinIds";
const state = {
    config: null, depot: null, bins: [], mode: null, vehicleId: null, vehicles: [],
    analysis: null, plan: null, saved: null, settingDepot: false,
    tempMarker: null, editingBinId: null, pendingLatLng: null,
};
let map, depotMarker = null, binLayer, routeLayer, analysisTimer = null, analysisSeq = 0;
const binMarkers = {};

document.addEventListener("DOMContentLoaded", async () => {
    map = L.map("planner-map").setView([18.5204, 73.8567], 13);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { attribution: "&copy; OpenStreetMap contributors", maxZoom: 19 }).addTo(map);
    binLayer = L.layerGroup().addTo(map);
    routeLayer = L.layerGroup().addTo(map);
    map.on("click", onMapClick);

    document.getElementById("btn-add-bin").addEventListener("click", () => showToast("Click a location on the map to place the next bin.", "info"));
    document.getElementById("btn-new-session").addEventListener("click", newSession);
    document.getElementById("btn-generate").addEventListener("click", generateRoute);
    document.getElementById("btn-regenerate").addEventListener("click", generateRoute);
    document.getElementById("btn-save").addEventListener("click", saveRoute);
    wireBinModal();

    const cfg = await api("/api/planning/config");
    if (!cfg.ok) { showToast(cfg.error, "error"); return; }
    state.config = cfg.data;
    state.mode = cfg.data.default_mode;
    renderModes();
    renderThresholds();

    await loadDepot();
    await restoreSessionBins();
    await loadVehicles();
    renderAll();
    loadPendingBins();
    scheduleAnalysis();
});

/* ------------------------------------------------------------ depot ---- */

async function loadDepot() {
    const res = await api("/api/depot");
    state.depot = res.data || null;
    if (state.depot) map.setView([state.depot.latitude, state.depot.longitude], 14);
    drawDepot();
}

function drawDepot() {
    if (depotMarker) { map.removeLayer(depotMarker); depotMarker = null; }
    if (state.depot) {
        depotMarker = L.marker([state.depot.latitude, state.depot.longitude], { icon: RouteView.depotIcon(), zIndexOffset: 1000 })
            .addTo(map).bindTooltip(`DEPOT: ${state.depot.name}`);
    }
}

function renderDepotCard() {
    const el = document.getElementById("depot-card");
    if (!state.depot || state.settingDepot) {
        el.innerHTML = `
            <p><strong>Step 1 — Select the depot.</strong> ${state.settingDepot ? "Click the map to move it." : "Click the map where the collection depot is."}</p>
            <div class="form-row"><label for="depot-name">Depot name</label>
                <input type="text" id="depot-name" value="${escapeHtml(state.depot ? state.depot.name : "Pune Depot")}"></div>
            ${state.depot ? `<button class="btn btn-secondary btn-small" id="btn-cancel-depot">Cancel</button>` : ""}`;
        const c = document.getElementById("btn-cancel-depot");
        if (c) c.addEventListener("click", () => { state.settingDepot = false; renderAll(); });
        return;
    }
    el.innerHTML = `
        <p>Depot: <strong>${escapeHtml(state.depot.name)}</strong> <span class="ds-meta">(${state.depot.latitude.toFixed(5)}, ${state.depot.longitude.toFixed(5)})</span></p>
        <button class="btn btn-secondary btn-small" id="btn-change-depot">Change depot</button>`;
    document.getElementById("btn-change-depot").addEventListener("click", () => {
        if (state.saved === null && state.bins.length && !confirm("Moving the depot changes every distance. Continue?")) return;
        state.settingDepot = true; renderAll();
    });
}

async function saveDepot(latlng) {
    const nameEl = document.getElementById("depot-name");
    const name = (nameEl && nameEl.value.trim()) || "Depot";
    const res = await apiJson("/api/depot", "POST", { name, latitude: latlng.lat, longitude: latlng.lng });
    if (!res.ok) { showToast(res.error, "error"); return; }
    state.depot = res.data;
    state.settingDepot = false;
    drawDepot();
    invalidatePlan();
    renderAll();
    scheduleAnalysis();
    showToast("Depot saved.", "success");
}

/* ------------------------------------------------------------- bins ---- */

function sessionIds() { return state.bins.map(b => b.bin_id); }
function persistSession() { sessionStorage.setItem(SESSION_KEY, JSON.stringify(sessionIds())); }

async function restoreSessionBins() {
    let ids = [];
    try { ids = JSON.parse(sessionStorage.getItem(SESSION_KEY) || "[]"); } catch (e) { ids = []; }
    if (!ids.length) return;
    const res = await api("/api/bins");
    if (!res.ok) return;
    const byId = Object.fromEntries(res.data.map(b => [b.bin_id, b]));
    state.bins = ids.map(id => byId[id]).filter(b => b && b.status === "ACTIVE");
    persistSession();
}

function onMapClick(e) {
    if (state.saved) { showToast("This route is saved. Start a new planning session to add more bins.", "info"); return; }
    if (!state.depot || state.settingDepot) { saveDepot(e.latlng); return; }
    openBinModal(null, e.latlng);
}

function binAnalysis(binId) {
    return state.analysis ? state.analysis.bins.find(b => b.bin_id === binId) : null;
}

function orderedBins() {
    if (!state.analysis) return state.bins;
    const rank = Object.fromEntries(state.analysis.bins.map(b => [b.bin_id, b.rank]));
    return [...state.bins].sort((a, b) => (rank[a.bin_id] || 999) - (rank[b.bin_id] || 999));
}

function renderBins() {
    const list = document.getElementById("bin-list");
    document.getElementById("bin-count").textContent = state.bins.length ? `(${state.bins.length})` : "";
    binLayer.clearLayers();
    Object.keys(binMarkers).forEach(k => delete binMarkers[k]);

    if (!state.bins.length) {
        list.innerHTML = `<p class="empty-row">Click the map to add your first bin.</p>`;
        return;
    }
    list.innerHTML = orderedBins().map((b, idx) => {
        const a = binAnalysis(b.bin_id);
        const label = a ? a.rank : idx + 1;
        const cls = b.priority.toLowerCase();
        const marker = L.marker([b.latitude, b.longitude], { icon: RouteView.binIcon(label, b.priority) })
            .addTo(binLayer).bindTooltip(`${b.name} — ${b.waste_level}%`);
        marker.on("click", () => openBinModal(b.bin_id));
        binMarkers[b.bin_id] = marker;
        return `
        <div class="bin-row ${cls}" data-id="${escapeHtml(b.bin_id)}">
            <div class="bin-num">${label}</div>
            <div class="bin-name">${escapeHtml(b.name)}</div>
            <div class="bin-actions">
                <button class="btn btn-small" data-edit="${escapeHtml(b.bin_id)}">Edit</button>
                <button class="btn btn-small btn-danger" data-del="${escapeHtml(b.bin_id)}">&times;</button>
            </div>
            <div class="bin-meta">
                <strong>${Number(b.waste_level).toFixed(0)}% FULL</strong> · ${fmtKg(b.current_waste_kg)}
                <span class="badge ${priorityBadgeClass(b.priority)}">${b.priority}</span>
                ${a && a.distance_km !== null ? ` · ${fmtKm(a.distance_km)} · ${fmtMin(a.travel_minutes)}` : ""}
            </div>
        </div>`;
    }).join("");
    list.querySelectorAll("[data-edit]").forEach(btn => btn.addEventListener("click", ev => { ev.stopPropagation(); openBinModal(btn.dataset.edit); }));
    list.querySelectorAll("[data-del]").forEach(btn => btn.addEventListener("click", ev => { ev.stopPropagation(); removeBin(btn.dataset.del); }));
    list.querySelectorAll(".bin-row").forEach(row => row.addEventListener("click", () => {
        const b = state.bins.find(x => x.bin_id === row.dataset.id);
        if (b) map.panTo([b.latitude, b.longitude]);
    }));
}

async function removeBin(binId) {
    if (!confirm("Remove this bin?")) return;
    const res = await api(`/api/bins/${binId}`, { method: "DELETE" });
    if (!res.ok) { showToast(res.error, "error"); return; }
    state.bins = state.bins.filter(b => b.bin_id !== binId);
    persistSession();
    invalidatePlan();
    renderAll();
    scheduleAnalysis();
}

/* ------------------------------------------------------ bin modal ------ */

function wireBinModal() {
    const $ = id => document.getElementById(id);
    let lastEdited = "level";
    $("bm-level").addEventListener("input", () => { lastEdited = "level"; syncWaste(lastEdited); });
    $("bm-kg").addEventListener("input", () => { lastEdited = "kg"; syncWaste(lastEdited); });
    $("bm-cap").addEventListener("input", () => syncWaste(lastEdited));
    $("bm-boost").addEventListener("change", () => $("bm-boost-fields").classList.toggle("hidden", !$("bm-boost").checked));
    $("bm-cancel").addEventListener("click", closeBinModal);
    $("bm-save").addEventListener("click", saveBinFromModal);
}

function priorityFor(level) {
    for (const t of state.config.thresholds) if (level >= t.min && level <= t.max) return t.label;
    return level > 100 ? "CRITICAL" : "LOW";
}

function syncWaste(source) {
    const $ = id => document.getElementById(id);
    const cap = parseFloat($("bm-cap").value) || 0;
    if (source === "level") {
        const lvl = parseFloat($("bm-level").value) || 0;
        $("bm-kg").value = cap ? +(lvl * cap / 100).toFixed(1) : 0;
    } else if (cap > 0) {
        const kg = parseFloat($("bm-kg").value) || 0;
        $("bm-level").value = Math.max(0, Math.min(100, Math.round(kg / cap * 100)));
    }
    const lvl = parseFloat($("bm-level").value) || 0;
    $("bm-level-label").textContent = lvl + "%";
    $("bm-fill").style.width = lvl + "%";
    const p = priorityFor(lvl);
    $("bm-priority").textContent = p;
    $("bm-priority").className = `badge ${priorityBadgeClass(p)}`;
}

function openBinModal(binId, latlng) {
    const $ = id => document.getElementById(id);
    state.editingBinId = binId;
    state.pendingLatLng = latlng || null;
    $("bm-error").classList.add("hidden");
    $("bm-image").value = "";
    const editing = binId ? state.bins.find(b => b.bin_id === binId) : null;

    if (editing) {
        $("bin-modal-title").textContent = `Edit ${editing.name}`;
        $("bm-lat").value = editing.latitude.toFixed(6); $("bm-lng").value = editing.longitude.toFixed(6);
        $("bm-name").value = editing.name; $("bm-level").value = editing.waste_level;
        $("bm-kg").value = editing.current_waste_kg; $("bm-cap").value = editing.maximum_capacity_kg;
        $("bm-cat").value = editing.waste_category || ""; $("bm-notes").value = editing.notes || "";
    } else {
        $("bin-modal-title").textContent = "Bin Information";
        $("bm-lat").value = latlng.lat.toFixed(6); $("bm-lng").value = latlng.lng.toFixed(6);
        $("bm-name").value = `Bin ${String.fromCharCode(65 + (state.bins.length % 26))}`;
        $("bm-level").value = 50; $("bm-cap").value = 100; $("bm-kg").value = 50;
        $("bm-cat").value = ""; $("bm-notes").value = "";
        if (state.tempMarker) map.removeLayer(state.tempMarker);
        state.tempMarker = L.marker(latlng, { icon: RouteView.binIcon("?", "LOW", "map-pin-temp") }).addTo(map);
    }
    $("bm-image-row").classList.toggle("hidden", !!editing);
    $("bm-boost-row").classList.toggle("hidden", !!editing);
    $("bm-boost").checked = false; $("bm-boost-fields").classList.add("hidden");
    syncWaste("level");
    if (editing) syncWaste("kg"); // keep the stored kg, recompute label
    $("bin-modal").classList.remove("hidden");
}

function closeBinModal() {
    document.getElementById("bin-modal").classList.add("hidden");
    if (state.tempMarker) { map.removeLayer(state.tempMarker); state.tempMarker = null; }
    state.editingBinId = null; state.pendingLatLng = null;
}

async function saveBinFromModal() {
    const $ = id => document.getElementById(id);
    const err = $("bm-error");
    err.classList.add("hidden");
    const name = $("bm-name").value.trim();
    const kg = parseFloat($("bm-kg").value), cap = parseFloat($("bm-cap").value), level = parseFloat($("bm-level").value);
    const fail = m => { err.textContent = m; err.classList.remove("hidden"); };
    if (!name) return fail("Please enter a bin name.");
    if (!(cap > 0)) return fail("Maximum capacity must be greater than 0.");
    if (isNaN(kg) || kg < 0) return fail("Waste weight must be 0 or more.");

    if (state.editingBinId) {
        const res = await apiJson(`/api/bins/${state.editingBinId}`, "PUT", {
            name, waste_level: level, current_waste_kg: kg, maximum_capacity_kg: cap,
            waste_category: $("bm-cat").value.trim(), notes: $("bm-notes").value.trim(),
        });
        if (!res.ok) return fail(res.error);
        state.bins = state.bins.map(b => b.bin_id === res.data.bin_id ? res.data : b);
    } else {
        const fd = new FormData();
        fd.append("bin_id", "BIN" + Date.now().toString().slice(-8));
        fd.append("name", name);
        fd.append("latitude", state.pendingLatLng.lat); fd.append("longitude", state.pendingLatLng.lng);
        fd.append("waste_level", level); fd.append("current_waste_kg", kg); fd.append("maximum_capacity_kg", cap);
        fd.append("waste_category", $("bm-cat").value.trim()); fd.append("notes", $("bm-notes").value.trim());
        if ($("bm-image").files[0]) fd.append("image", $("bm-image").files[0]);
        const res = await api("/api/bins", { method: "POST", body: fd });
        if (!res.ok) return fail(res.error);
        let created = res.data;
        if ($("bm-boost").checked) {
            const boost = await apiJson(`/api/bins/${created.bin_id}/boost`, "POST",
                { requested_priority: $("bm-boost-priority").value, reason: $("bm-boost-reason").value });
            if (boost.ok) created = boost.data;
        }
        state.bins.push(created);
    }
    persistSession();
    closeBinModal();
    invalidatePlan();
    renderAll();
    scheduleAnalysis();
}

/* ------------------------------------------- other pending bins (Queue) -- */

async function loadPendingBins() {
    const res = await api("/api/requests/pending");
    const box = document.getElementById("pending-box");
    if (!res.ok) { box.style.display = "none"; return; }
    const inSession = new Set(sessionIds());
    const items = res.data.filter(r => r.bin && r.bin.status === "ACTIVE" && !inSession.has(r.bin_id));
    if (!items.length) { box.style.display = "none"; return; }
    box.style.display = "";
    document.getElementById("pending-list").innerHTML = items.map(r => `
        <div class="route-summary-row">
            <span>${escapeHtml(r.bin.name)} <span class="ds-meta">${r.bin.waste_level}% · ${fmtKg(r.bin.current_waste_kg)}</span></span>
            <button class="btn btn-small" data-add="${escapeHtml(r.bin_id)}">Add to this route</button>
        </div>`).join("");
    document.querySelectorAll("[data-add]").forEach(btn => btn.addEventListener("click", () => {
        const item = items.find(i => i.bin_id === btn.dataset.add);
        state.bins.push(item.bin);
        persistSession(); invalidatePlan(); renderAll(); scheduleAnalysis(); loadPendingBins();
    }));
}

/* --------------------------------------------------- modes & vehicles --- */

function renderModes() {
    const el = document.getElementById("mode-options");
    el.innerHTML = state.config.modes.map(m => `
        <label class="option-card ${m.key === state.mode ? "selected" : ""}">
            <input type="radio" name="mode" value="${m.key}" ${m.key === state.mode ? "checked" : ""}>
            <span><strong>${escapeHtml(m.label)}</strong>${m.key === state.config.default_mode ? " <span class='ds-meta'>(recommended)</span>" : ""}
            <small>${escapeHtml(m.description)}</small></span>
        </label>`).join("");
    el.querySelectorAll("input").forEach(i => i.addEventListener("change", () => {
        state.mode = i.value; invalidatePlan(); renderModes(); scheduleAnalysis(); updateStepper();
    }));
}

function renderThresholds() {
    document.getElementById("threshold-row").innerHTML = state.config.thresholds.map(t =>
        `<span class="badge ${priorityBadgeClass(t.label)}">${t.label}: ${t.min}–${t.max}%</span>`).join("");
}

async function loadVehicles() {
    const res = await api("/api/vehicles/available");
    state.vehicles = res.ok ? res.data : [];
    if (!state.vehicles.find(v => v.vehicle_id === state.vehicleId)) state.vehicleId = state.vehicles.length === 1 ? state.vehicles[0].vehicle_id : null;
    renderVehicles();
}

function renderVehicles() {
    const el = document.getElementById("vehicle-options");
    if (!state.vehicles.length) {
        el.innerHTML = `<p class="empty-row">No vehicle is available. A collector must register a vehicle (Collector Dashboard &rarr; My Vehicle) and it must not be on another route.</p>`;
        return;
    }
    el.innerHTML = state.vehicles.map(v => `
        <label class="option-card ${v.vehicle_id === state.vehicleId ? "selected" : ""}">
            <input type="radio" name="vehicle" value="${escapeHtml(v.vehicle_id)}" ${v.vehicle_id === state.vehicleId ? "checked" : ""}>
            <span><strong>${escapeHtml(v.vehicle_number)}</strong> <span class="badge badge-low">${escapeHtml(v.status)}</span>
            <small>Collector: ${escapeHtml(v.collector.name)} · Capacity ${fmtKg(v.maximum_capacity_kg)} · Available ${fmtKg(v.available_capacity_kg)}${v.vehicle_type ? " · " + escapeHtml(v.vehicle_type) : ""}</small></span>
        </label>`).join("");
    el.querySelectorAll("input").forEach(i => i.addEventListener("change", () => {
        state.vehicleId = i.value; invalidatePlan(); renderVehicles(); scheduleAnalysis(); updateStepper();
    }));
}

/* -------------------------------------------------------- analysis ------ */

function scheduleAnalysis() {
    clearTimeout(analysisTimer);
    analysisTimer = setTimeout(runAnalysis, 250);
}

async function runAnalysis() {
    const seq = ++analysisSeq;
    const wrap = document.getElementById("analysis-wrap");
    const warn = document.getElementById("analysis-warning");
    if (!state.bins.length || !state.depot) {
        state.analysis = null;
        warn.innerHTML = "";
        wrap.innerHTML = `<p class="empty-row">${!state.depot ? "Select the depot on the map first." : "Add at least one bin to see the priority analysis."}</p>`;
        renderBins(); updateGenerateButton(); updateStepper();
        return;
    }
    wrap.innerHTML = `<p class="empty-row">Calculating road distances...</p>`;
    const res = await apiJson("/api/planning/analyze", "POST", { bin_ids: sessionIds(), priority_mode: state.mode, vehicle_id: state.vehicleId });
    if (seq !== analysisSeq) return; // a newer request superseded this one
    if (!res.ok) {
        state.analysis = null;
        warn.innerHTML = `<div class="warn-box">${escapeHtml(res.error)}</div>`;
        wrap.innerHTML = "";
        renderBins(); updateGenerateButton(); updateStepper();
        return;
    }
    state.analysis = res.data;
    renderAnalysis();
    renderBins();
    updateGenerateButton();
    updateStepper();
}

function renderAnalysis() {
    const a = state.analysis;
    const warn = document.getElementById("analysis-warning");
    warn.innerHTML = a.warning ? `<div class="warn-box">&#9888; ${escapeHtml(a.warning)}<br><button class="btn btn-small" id="btn-retry-analysis">Retry road routing</button></div>` : "";
    const retry = document.getElementById("btn-retry-analysis");
    if (retry) retry.addEventListener("click", runAnalysis);

    document.getElementById("analysis-wrap").innerHTML = `
        <table class="data-table">
            <thead><tr><th>Rank</th><th>Bin</th><th>Waste level</th><th>Waste</th><th>Road distance from depot</th><th>Est. time (${a.minutes_per_km} min/km)</th><th>Priority</th><th>Score</th><th>Why this position</th></tr></thead>
            <tbody>${a.bins.map(b => `
                <tr>
                    <td><strong>${b.rank}</strong></td>
                    <td>${escapeHtml(b.name)}</td>
                    <td>${Number(b.waste_level).toFixed(0)}%</td>
                    <td>${fmtKg(b.current_waste_kg)}</td>
                    <td>${b.distance_km === null ? "&mdash;" : fmtKm(b.distance_km)}<br><span class="ds-meta" title="Straight-line (Haversine) - academic Graph only, never used as driving distance">straight-line ${fmtKm(b.straight_line_km)}</span></td>
                    <td>${b.travel_minutes === null ? "&mdash;" : fmtMin(b.travel_minutes)}</td>
                    <td><span class="badge ${priorityBadgeClass(b.priority)}">${b.priority}</span></td>
                    <td>${b.score}</td>
                    <td class="reason-cell">${escapeHtml(b.reason)}${b.warning ? `<br><span class="error-text">${escapeHtml(b.warning)}</span>` : ""}</td>
                </tr>`).join("")}
            </tbody>
        </table>
        <p class="ds-meta">Mode: <strong>${escapeHtml(a.mode_label)}</strong> · Total waste ${fmtKg(a.total_waste_kg)} ·
        Queue arrival: ${a.dsa.queue_arrival_order.map(escapeHtml).join(" → ")} ·
        Priority Queue pop order: ${a.dsa.priority_queue_pop_order.map(escapeHtml).join(" → ")}</p>`;
}

/* -------------------------------------------------- generate / save ----- */

function updateGenerateButton() {
    const btn = document.getElementById("btn-generate");
    const hint = document.getElementById("generate-hint");
    let reason = "";
    if (state.saved) reason = "Route saved. Start a new session to plan another.";
    else if (!state.depot) reason = "Select the depot first.";
    else if (!state.bins.length) reason = "Add at least one bin.";
    else if (!state.vehicleId) reason = "Select an available vehicle.";
    else if (!state.analysis || !state.analysis.road_ok) reason = "Road distances are not available yet.";
    btn.disabled = !!reason;
    hint.textContent = reason;
}

function invalidatePlan() {
    state.plan = null;
    routeLayer.clearLayers();
    document.getElementById("result-section").style.display = "none";
    updateStepper();
}

async function generateRoute() {
    const btn = document.getElementById("btn-generate");
    btn.disabled = true; btn.textContent = "Requesting road route...";
    const res = await apiJson("/api/planning/generate", "POST", { bin_ids: sessionIds(), vehicle_id: state.vehicleId, priority_mode: state.mode });
    btn.textContent = "GENERATE ROUTE ACCORDING TO PRIORITY";
    updateGenerateButton();
    const warn = document.getElementById("result-warning");
    const section = document.getElementById("result-section");
    if (!res.ok) {
        routeLayer.clearLayers();
        section.style.display = "";
        document.getElementById("result-summary").innerHTML = "";
        document.getElementById("btn-save").disabled = true;
        warn.innerHTML = `<div class="warn-box">&#9888; ${escapeHtml(res.error)}
            ${res.body && res.body.osrm_unavailable ? `<br>No route is drawn: a straight line is not a road. <button class="btn btn-small" id="btn-retry-gen">Retry</button>` : ""}</div>`;
        const r = document.getElementById("btn-retry-gen");
        if (r) r.addEventListener("click", generateRoute);
        return;
    }
    state.plan = res.data;
    warn.innerHTML = "";
    section.style.display = "";
    document.getElementById("btn-save").disabled = false;
    document.getElementById("result-summary").innerHTML = RouteView.summaryHtml(state.plan);
    const { bounds, missing } = RouteView.drawTrips(map, routeLayer, state.plan.trips);
    if (missing) warn.innerHTML = `<div class="warn-box">${missing} road segment(s) came back without geometry and are not drawn.</div>`;
    if (bounds) map.fitBounds(bounds.pad(0.15));
    renderDsa();
    updateStepper();
    section.scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderDsa() {
    const d = state.plan.dsa;
    document.getElementById("dsa-content").innerHTML = `
        <p><strong>Queue</strong> (arrival order): ${d.queue_arrival_order.map(escapeHtml).join(" → ")}</p>
        <p><strong>Priority Queue / Min Heap</strong> (pop order, mode ${escapeHtml(state.plan.mode_label)}): ${d.priority_queue_pop_order.map(escapeHtml).join(" → ")}</p>
        <p><strong>Graph</strong> (adjacency list): vertices ${d.graph_vertices.map(escapeHtml).join(", ")}; edge weight = ${escapeHtml(d.graph_edge_weight)}</p>
        ${d.stack_trace.map(t => `<p><strong>Stack, trip ${t.trip_number}</strong>: pushed ${t.pushed.map(escapeHtml).join(" → ")}<br>unwound (LIFO) ${t.unwound.map(escapeHtml).join(" → ")}</p>`).join("")}
        <p class="ds-meta">Academic layer decides the ORDER. The coloured road lines on the map come from the routing engine (OSRM), not from this logic.</p>`;
}

async function saveRoute() {
    if (!state.plan) return;
    const btn = document.getElementById("btn-save");
    btn.disabled = true;
    const res = await apiJson("/api/planning/save", "POST", { draft_token: state.plan.draft_token });
    if (!res.ok) { btn.disabled = false; showToast(res.error, "error"); return; }
    state.saved = res.data;
    sessionStorage.removeItem(SESSION_KEY);
    document.getElementById("result-summary").innerHTML =
        RouteView.summaryHtml(res.data, { title: "SAVED COLLECTION ROUTE" }) +
        `<div class="status-box" style="margin-top:1rem">Route <strong>${escapeHtml(res.data.route_code)}</strong> saved and assigned to
        ${escapeHtml(res.data.collector ? res.data.collector.name : "the collector")}. <a href="/history">View in History</a></div>`;
    document.querySelector("#result-section .form-actions").innerHTML =
        `<button class="btn btn-primary" id="btn-another">Plan another route</button>`;
    document.getElementById("btn-another").addEventListener("click", newSession);
    showToast(`Route ${res.data.route_code} saved.`, "success");
    updateGenerateButton(); updateStepper();
}

function newSession() {
    sessionStorage.removeItem(SESSION_KEY);
    window.location.reload();
}

/* ------------------------------------------------------------ chrome ---- */

function updateStepper() {
    const doneFlags = [
        !!state.depot && state.bins.length > 0,
        state.bins.length > 0,
        !!state.analysis && state.analysis.road_ok,
        !!state.plan || !!state.saved,
        !!state.saved,
    ];
    let active = doneFlags.findIndex(f => !f);
    document.querySelectorAll("#stepper .step-indicator").forEach((el, i) => {
        el.classList.toggle("done", doneFlags[i]);
        el.classList.toggle("active", i === active);
    });
    const hint = document.getElementById("map-hint");
    hint.textContent = state.settingDepot || !state.depot
        ? "Click the map to place the depot (blue square)."
        : state.saved ? "Route saved." : "Click anywhere on the map to add a bin. Route lines follow roads once generated.";
}

function renderAll() {
    renderDepotCard();
    renderBins();
    updateGenerateButton();
    updateStepper();
}
