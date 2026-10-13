/* ==========================================================
   static/js/auth-nav.js
   Shared logout helpers, called from the navbar links in base.html.
   ========================================================== */

async function logoutUser() {
    await fetch("/api/auth/logout", { method: "POST" });
    window.location.href = "/login";
}

async function logoutCollector() {
    await fetch("/api/auth/logout", { method: "POST" });
    window.location.href = "/collector/login";
}
