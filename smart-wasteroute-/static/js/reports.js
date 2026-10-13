/* static/js/reports.js - summary cards + per-vehicle performance (all from /api/reports/summary) */

document.addEventListener("DOMContentLoaded", () => {
    loadReports();
    document.getElementById("btn-refresh-reports").addEventListener("click", loadReports);
});

async function loadReports() {
    const res = await api("/api/reports/summary");
    if (!res.ok) { document.getElementById("report-cards-grid").innerHTML = `<div class="empty-row error-text">${escapeHtml(res.error)}</div>`; return; }
    const d = res.data;
    const cards = [
        ["Total Waste Collected", fmtKg(d.total_waste_kg)],
        ["Total Routes", d.total_routes],
        ["Total Trips", d.total_trips],
        ["Total Bins Collected", d.total_bins_collected],
        ["Total Road Distance", fmtKm(d.total_distance_km)],
        ["Avg Distance / Trip", fmtKm(d.avg_distance_per_trip_km)],
        ["Avg Waste / Trip", fmtKg(d.avg_waste_per_trip_kg)],
        ["Vehicle Utilization", d.vehicle_utilization_percent === null ? "-" : d.vehicle_utilization_percent + "%"],
    ];
    document.getElementById("report-cards-grid").innerHTML = cards.map(([label, value]) =>
        `<div class="stat-card"><div class="stat-value">${value}</div><div class="stat-label">${label}</div></div>`).join("");

    document.getElementById("per-vehicle-table-body").innerHTML = d.per_vehicle.length
        ? d.per_vehicle.map(v => `<tr><td>${escapeHtml(v.vehicle_name)}</td><td>${v.trips}</td><td>${v.waste_filled_times}</td>
            <td>${fmtKm(v.distance_km)}</td><td>${fmtKg(v.total_waste_kg)}</td><td>${v.utilization_percent === null ? "-" : v.utilization_percent + "%"}</td></tr>`).join("")
        : `<tr><td colspan="6" class="empty-row">No completed trips yet.</td></tr>`;

    document.getElementById("top-bins-table-body").innerHTML = d.top_collected_bins.length
        ? d.top_collected_bins.map(b => `<tr><td>${escapeHtml(b.bin_id)}</td><td>${b.times_collected}</td></tr>`).join("")
        : `<tr><td colspan="2" class="empty-row">No collections yet.</td></tr>`;
}
