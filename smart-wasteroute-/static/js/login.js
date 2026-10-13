document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("login-form").addEventListener("submit", handleLogin);
});

async function handleLogin(event) {
    event.preventDefault();
    const errorEl = document.getElementById("login-error");
    errorEl.classList.add("hidden");

    const payload = {
        identifier: document.getElementById("identifier").value.trim(),
        password: document.getElementById("password").value,
    };

    try {
        const res = await fetch("/api/auth/login", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        const body = await res.json();
        if (!body.success) {
            errorEl.textContent = body.error;
            errorEl.classList.remove("hidden");
            return;
        }
        window.location.href = "/dashboard";
    } catch (err) {
        errorEl.textContent = "Network error: " + err.message;
        errorEl.classList.remove("hidden");
    }
}
