/* ==========================================================
   static/js/common.js
   Small helpers shared by every page (loaded from base.html).
   ========================================================== */

function escapeHtml(value) {
    const div = document.createElement("div");
    div.textContent = value === null || value === undefined ? "" : String(value);
    return div.innerHTML;
}

function priorityBadgeClass(priority) {
    return { LOW: "badge-low", MEDIUM: "badge-medium", HIGH: "badge-high", CRITICAL: "badge-critical" }[priority] || "badge-low";
}

const PRIORITY_HEX = { LOW: "#22c55e", MEDIUM: "#eab308", HIGH: "#f97316", CRITICAL: "#ef4444" };

/* fetch + JSON with one consistent shape: { ok, status, data, error, body } */
async function api(url, options = {}) {
    try {
        const res = await fetch(url, options);
        let body = null;
        try { body = await res.json(); } catch (e) { /* non-JSON error page */ }
        return {
            ok: !!(body && body.success), status: res.status, body,
            data: body ? body.data : null,
            error: body && body.error ? body.error : (res.ok ? null : `Request failed (${res.status})`),
        };
    } catch (err) {
        return { ok: false, status: 0, body: null, data: null, error: "Network error: " + err.message };
    }
}

function apiJson(url, method, payload) {
    return api(url, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload || {}) });
}

/* "2026-10-11T10:12:00" -> "10:12 AM" */
function formatTime(iso) {
    if (!iso) return "-";
    const d = new Date(iso);
    return isNaN(d) ? iso : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function formatDateTime(iso) {
    if (!iso) return "-";
    const d = new Date(iso);
    return isNaN(d) ? iso : d.toLocaleString([], { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

function fmtKm(v) { return v === null || v === undefined ? "-" : `${Number(v).toFixed(2)} km`; }
function fmtMin(v) { return v === null || v === undefined ? "-" : `${Number(v).toFixed(0)} min`; }
function fmtKg(v) { return v === null || v === undefined ? "-" : `${Number(v).toFixed(1).replace(/\.0$/, "")} kg`; }
