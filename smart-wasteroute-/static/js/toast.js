/* ==========================================================
   static/js/toast.js
   A small, dependency-free toast notification system, used
   throughout the app instead of browser alert() calls, per the
   project's "modern toast notifications instead of excessive
   alert() calls" requirement.

   Usage: showToast("Bin successfully added.", "success");
   Types: "success" (green), "error" (red), "info" (blue/cyan).
   ========================================================== */

function showToast(message, type = "info", durationMs = 4000) {
    const container = document.getElementById("toast-container");
    if (!container) {
        console.warn("No #toast-container on this page; falling back to alert().");
        alert(message);
        return;
    }

    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    container.appendChild(toast);

    // Force a reflow so the CSS transition below actually animates in.
    void toast.offsetWidth;
    toast.classList.add("toast-visible");

    setTimeout(() => {
        toast.classList.remove("toast-visible");
        setTimeout(() => toast.remove(), 300);
    }, durationMs);
}
