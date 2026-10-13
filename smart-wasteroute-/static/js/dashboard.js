/* ==========================================================
   static/js/dashboard.js
   Renders the 9 stat cards (Section 22 of the spec), a simple
   priority breakdown chart, and a short recent-activity list.

   NOTE: the priority chart is built with plain HTML/CSS bars,
   not a charting library - matches the spec's "Include simple
   charts only where useful. Do not make the dashboard overly
   complicated" instruction, and needs zero extra dependencies.
   ========================================================== */

const CARD_DEFINITIONS = [
    { key: "total_bins", label: "Total Bins" },
    { key: "critical_bins", label: "Critical Bins", tone: "critical" },
    { key: "high_priority_bins", label: "High Priority Bins", tone: "high" },
    { key: "total_vehicles", label: "Total Vehicles" },
    { key: "available_vehicles", label: "Available Vehicles", tone: "low" },
    { key: "total_waste_kg", label: "Total Waste (kg)" },
    { key: "pending_requests", label: "Pending Requests" },
    { key: "completed_collections", label: "Completed Collections" },
    { key: "active_routes", label: "Active Routes" },
    { key: "total_distance_km", label: "Total Distance (km)" },
];

const PRIORITY_COLORS = {
    LOW: "var(--color-low)",
    MEDIUM: "var(--color-medium)",
    HIGH: "var(--color-high)",
    CRITICAL: "var(--color-critical)",
};

document.addEventListener("DOMContentLoaded", () => {
    loadDashboard();
    loadWelcome();
    loadActiveRoutes();
    loadBinsGrid(true);
    document.getElementById("btn-refresh-dashboard").addEventListener("click", loadDashboard);
    document.getElementById("btn-load-demo").addEventListener("click", loadDemoData);
    document.getElementById("btn-clear-demo").addEventListener("click", clearDemoData);
    document.getElementById("btn-filter-mine").addEventListener("click", () => setBinsFilter(true));
    document.getElementById("btn-filter-all").addEventListener("click", () => setBinsFilter(false));
});

async function loadWelcome() {
    try {
        const res = await fetch("/api/auth/me");
        const body = await res.json();
        if (body.data && body.data.role === "user") {
            document.getElementById("dashboard-welcome").textContent = `Welcome, ${body.data.full_name}`;
        }
    } catch (err) { /* non-critical */ }
}

function priorityBadgeClass(priority) {
    return { LOW: "badge-low", MEDIUM: "badge-medium", HIGH: "badge-high", CRITICAL: "badge-critical" }[priority] || "badge-low";
}

async function loadActiveRoutes() {
    const el = document.getElementById("active-routes-list");
    try {
        const res = await fetch("/api/routes");
        const body = await res.json();
        const active = body.data.filter(r => ["GENERATED", "ASSIGNED", "IN_PROGRESS"].includes(r.status));
        if (active.length === 0) {
            el.innerHTML = `<p class="empty-row">No active routes right now.</p>`;
            return;
        }
        el.innerHTML = active.map(r => `
            <div class="route-summary-row">
                <span><strong>${escapeHtml(r.route_code)}</strong> ${escapeHtml(r.label)} - ${r.total_bins} bin(s), ${r.total_trips} trip(s), ${fmtKm(r.total_distance)}</span>
                <span class="badge badge-high">${escapeHtml(r.status.replace("_", " "))}</span>
                <a href="/history" class="btn btn-small">View in History</a>
            </div>
        `).join("");
    } catch (err) {
        el.innerHTML = `<p class="empty-row error-text">${err.message}</p>`;
    }
}

let showingMine = true;
function setBinsFilter(mine) {
    showingMine = mine;
    document.getElementById("btn-filter-mine").classList.toggle("active-mode", mine);
    document.getElementById("btn-filter-all").classList.toggle("active-mode", !mine);
    loadBinsGrid(mine);
}

async function loadBinsGrid(mine) {
    const grid = document.getElementById("my-bins-grid");
    try {
        const res = await fetch(mine ? "/api/bins/mine" : "/api/bins");
        const body = await res.json();
        if (!body.success) {
            grid.innerHTML = `<p class="empty-row error-text">${body.error}</p>`;
            return;
        }
        if (body.data.length === 0) {
            grid.innerHTML = `<p class="empty-row">${mine ? "You haven't reported any bins yet." : "No bins yet."}</p>`;
            return;
        }
        grid.innerHTML = body.data.map(b => `
            <div class="bin-card">
                ${b.image_filename ? `<img src="/uploads/bins/${escapeHtml(b.image_filename)}" alt="${escapeHtml(b.name)}">` : `<div class="bin-card-noimage">No image</div>`}
                <div class="bin-card-body">
                    <strong>${escapeHtml(b.bin_id)}</strong> - ${escapeHtml(b.name)}<br>
                    <span class="badge ${priorityBadgeClass(b.priority)}">${b.priority}</span>
                    <span class="badge badge-medium">${escapeHtml(b.status)}</span><br>
                    <span class="ds-meta">${b.waste_level}% &middot; ${b.current_waste_kg}/${b.maximum_capacity_kg} kg</span>
                </div>
            </div>
        `).join("");
    } catch (err) {
        grid.innerHTML = `<p class="empty-row error-text">${err.message}</p>`;
    }
}

function showDemoMessage(message, isError) {
    const el = document.getElementById("demo-data-message");
    el.textContent = message;
    el.classList.remove("hidden");
    el.style.background = isError ? "#fdecea" : "#e8f5e9";
    el.style.color = isError ? "var(--color-critical)" : "var(--color-primary-dark)";
    el.style.borderColor = isError ? "var(--color-critical)" : "var(--color-primary)";
}

async function loadDemoData() {
    try {
        const res = await fetch("/api/demo/load", { method: "POST" });
        const body = await res.json();
        if (!body.success) {
            showDemoMessage(body.error, true);
            return;
        }
        showDemoMessage(
            `Loaded: ${body.data.bins_created.length} bins, ${body.data.vehicles_created.length} vehicles, depot "${body.data.depot.name}". ` +
            `Collector logins: ${body.data.collectors_created.map(c => c.collector_code).join(", ")} (password ${body.data.collector_password}).`,
            false
        );
        loadDashboard();
    } catch (err) {
        showDemoMessage("Network error: " + err.message, true);
    }
}

async function clearDemoData() {
    if (!confirm("Clear all demo data? This only removes data flagged as demo - your own bins and vehicles are never affected.")) return;
    try {
        const res = await fetch("/api/demo/clear", { method: "DELETE" });
        const body = await res.json();
        if (!body.success) {
            showDemoMessage(body.error, true);
            return;
        }
        showDemoMessage(`Cleared ${body.data.bins_deleted} demo bin(s) and associated demo vehicles/depot.`, false);
        loadDashboard();
    } catch (err) {
        showDemoMessage("Network error: " + err.message, true);
    }
}

async function loadDashboard() {
    await Promise.all([loadStats(), loadRecentCollections()]);
}

async function loadStats() {
    const grid = document.getElementById("stat-cards-grid");
    try {
        const res = await fetch("/api/dashboard");
        const body = await res.json();
        if (!body.success) throw new Error(body.error);

        renderStatCards(body.data);
        renderPriorityChart(body.data.priority_breakdown);
    } catch (err) {
        grid.innerHTML = `<div class="empty-row error-text">Error loading dashboard: ${err.message}</div>`;
    }
}

function renderStatCards(stats) {
    const grid = document.getElementById("stat-cards-grid");
    grid.innerHTML = CARD_DEFINITIONS.map(def => `
        <div class="stat-card ${def.tone ? 'stat-card-' + def.tone : ''}">
            <div class="stat-value">${stats[def.key]}</div>
            <div class="stat-label">${def.label}</div>
        </div>
    `).join("");
}

function renderPriorityChart(breakdown) {
    const container = document.getElementById("priority-chart");
    const levels = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]; // most urgent first
    const maxCount = Math.max(1, ...levels.map(l => breakdown[l] || 0)); // avoid divide-by-zero

    container.innerHTML = levels.map(level => {
        const count = breakdown[level] || 0;
        const widthPct = (count / maxCount) * 100;
        return `
            <div class="priority-bar-row">
                <span class="priority-bar-label">${level}</span>
                <div class="priority-bar-track">
                    <div class="priority-bar-fill" style="width: ${widthPct}%; background: ${PRIORITY_COLORS[level]};"></div>
                </div>
                <span class="priority-bar-count">${count}</span>
            </div>
        `;
    }).join("");
}

async function loadRecentCollections() {
    const container = document.getElementById("recent-collections");
    try {
        const res = await fetch("/api/history");
        const body = await res.json();
        if (!body.success) throw new Error(body.error);

        const recent = body.data.slice(0, 5); // history is already ordered newest-first
        if (recent.length === 0) {
            container.innerHTML = `<p class="empty-row">No collections yet.</p>`;
            return;
        }

        container.innerHTML = `
            <ul class="recent-list">
                ${recent.map(h => `
                    <li>
                        <strong>${escapeHtml(h.vehicle_id)}</strong>
                        &middot; ${h.collected_bins.length} bin(s)
                        &middot; ${h.total_waste}kg
                        &middot; ${h.total_distance}km
                        <span class="recent-date">${escapeHtml(h.date)}</span>
                    </li>
                `).join("")}
            </ul>
        `;
    } catch (err) {
        container.innerHTML = `<p class="empty-row error-text">Error loading recent collections: ${err.message}</p>`;
    }
}

function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}
