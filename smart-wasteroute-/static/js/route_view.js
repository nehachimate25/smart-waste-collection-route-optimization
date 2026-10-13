/* ==========================================================
   static/js/route_view.js
   Shared rendering for a planned / saved route (used by Add Bins & Route,
   Requests, History and the Collector Dashboard).

   IMPORTANT: polylines are drawn ONLY from the road geometry returned by the
   routing engine (stored per step as segment_geometry). If a step has no
   geometry nothing is drawn for it - we never connect two coordinates with a
   straight line and call it a road.
   ========================================================== */

const RouteView = (() => {
    const TRIP_COLORS = ["#3b82f6", "#a855f7", "#14b8a6", "#f43f5e", "#f59e0b"];

    function depotIcon() {
        return L.divIcon({ className: "", html: '<div class="map-pin map-pin-depot" title="Depot">&#127981;</div>', iconSize: [34, 34], iconAnchor: [17, 17] });
    }

    function binIcon(label, priority, extraClass = "") {
        const color = PRIORITY_HEX[priority] || "#94a3b8";
        return L.divIcon({
            className: "",
            html: `<div class="map-pin map-pin-bin ${extraClass}" style="background:${color}">${escapeHtml(label)}</div>`,
            iconSize: [28, 28], iconAnchor: [14, 14],
        });
    }

    /* Draw every trip's road legs. Returns { bounds, missing } */
    function drawTrips(map, group, trips, activeTripNumber = null) {
        group.clearLayers();
        let bounds = null, missing = 0;
        trips.forEach((trip, i) => {
            const color = TRIP_COLORS[i % TRIP_COLORS.length];
            const dim = activeTripNumber !== null && trip.trip_number !== activeTripNumber;
            trip.steps.forEach(step => {
                if (step.step_type === "DEPOT_START") return;
                const geom = step.segment_geometry;
                if (!geom || geom.length < 2) { missing++; return; }
                const line = L.polyline(geom, { color, weight: dim ? 3 : 5, opacity: dim ? 0.35 : 0.9 });
                line.bindTooltip(`Trip ${trip.trip_number}: ${fmtKm(step.segment_distance_km)} · ${fmtMin(step.segment_time_min)} → ${step.location_name}`, { sticky: true });
                line.addTo(group);
                bounds = bounds ? bounds.extend(line.getBounds()) : line.getBounds();
            });
        });
        return { bounds, missing };
    }

    function stepStatusIcon(step) {
        if (step.status === "COLLECTED" || step.status === "DONE") return "&#9989;";
        if (step.status === "IN_PROGRESS") return "&#128666;";
        return "&#9675;";
    }

    /* Summary + collection order (+ return to depot) for a plan or saved route */
    function summaryHtml(plan, opts = {}) {
        const vehicle = plan.vehicle || {};
        const collector = plan.collector || {};
        const t = plan.totals || {
            trips: plan.total_trips, bins: plan.total_bins, waste_kg: plan.total_waste,
            distance_km: plan.total_distance, time_min: plan.total_time_min,
        };
        const trips = plan.trips || [];
        const code = plan.route_code ? `<span class="badge badge-medium">${escapeHtml(plan.route_code)}${plan.label ? " — " + escapeHtml(plan.label) : ""}</span>` : "";

        const tripBlocks = trips.map((trip, i) => {
            const color = TRIP_COLORS[i % TRIP_COLORS.length];
            const binSteps = trip.steps.filter(s => s.step_type === "BIN");
            const ret = trip.steps.find(s => s.step_type === "DEPOT_RETURN");
            return `
            <div class="trip-block" style="border-left-color:${color}">
                <div class="trip-head">
                    <strong>Trip ${trip.trip_number}</strong>
                    <span class="ds-meta">${binSteps.length} bin(s) · ${fmtKg(trip.planned_waste_kg)} of ${fmtKg(trip.capacity_kg)} · ${fmtKm(trip.total_distance_km)} · ${fmtMin(trip.total_time_min)}</span>
                </div>
                <ol class="order-list">
                    <li class="order-depot">Depot${trip.initial_unload_kg > 0 ? ` <span class="ds-meta">(unload existing ${fmtKg(trip.initial_unload_kg)} first)</span>` : ""}</li>
                    ${binSteps.map(s => `
                    <li>
                        ${opts.showStatus ? stepStatusIcon(s) : ""}
                        <strong>${escapeHtml(s.location_name)}</strong> — ${s.waste_level !== null ? Number(s.waste_level).toFixed(0) + "%" : ""}
                        <span class="badge ${priorityBadgeClass(s.priority)}">${escapeHtml(s.priority || "")}</span>
                        <span class="ds-meta">${fmtKg(s.planned_waste_kg)} · ${fmtKm(s.segment_distance_km)} · ${fmtMin(s.segment_time_min)} · load ${fmtKg(s.load_after_kg)}</span>
                    </li>`).join("")}
                    <li class="order-depot">
                        ${opts.showStatus ? stepStatusIcon(ret) : ""}
                        Return to Depot${trip.ended_by_capacity ? " — vehicle full, unload, then continue" : " — final return"}
                        <span class="ds-meta">${ret ? fmtKm(ret.segment_distance_km) + " · " + fmtMin(ret.segment_time_min) : ""}</span>
                    </li>
                </ol>
            </div>`;
        }).join("");

        const warnings = (plan.warnings || []).map(w => `<div class="form-error">${escapeHtml(w)}</div>`).join("");

        return `
        <div class="route-summary-card">
            <h3>${opts.title || "GENERATED COLLECTION ROUTE"} ${code}</h3>
            <div class="summary-grid">
                <div><span class="ds-meta">Vehicle</span><br><strong>${escapeHtml(vehicle.vehicle_number || plan.vehicle_id || "-")}</strong></div>
                <div><span class="ds-meta">Collector</span><br><strong>${escapeHtml(collector.name || "-")}</strong></div>
                <div><span class="ds-meta">Total bins</span><br><strong>${t.bins}</strong></div>
                <div><span class="ds-meta">Trips</span><br><strong>${t.trips}</strong></div>
                <div><span class="ds-meta">Total waste</span><br><strong>${fmtKg(t.waste_kg)}</strong></div>
                <div><span class="ds-meta">Total road distance</span><br><strong>${fmtKm(t.distance_km)}</strong></div>
                <div><span class="ds-meta">Estimated travel time</span><br><strong>${fmtMin(t.time_min)}</strong></div>
            </div>
            ${warnings}
            <h4>Collection order</h4>
            ${tripBlocks}
        </div>`;
    }

    return { TRIP_COLORS, depotIcon, binIcon, drawTrips, summaryHtml };
})();
