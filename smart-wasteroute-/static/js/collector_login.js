document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("collector-login-form").addEventListener("submit", handleCollectorLogin);
    document.getElementById("collector-register-form").addEventListener("submit", handleCollectorRegister);
});

async function handleCollectorLogin(event) {
    event.preventDefault();
    const errorEl = document.getElementById("collector-login-error");
    errorEl.classList.add("hidden");

    const payload = {
        collector_code: document.getElementById("collector_code").value.trim(),
        password: document.getElementById("password").value,
    };

    try {
        const res = await fetch("/api/auth/collector/login", {
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
        window.location.href = "/collector/dashboard";
    } catch (err) {
        errorEl.textContent = "Network error: " + err.message;
        errorEl.classList.remove("hidden");
    }
}

async function handleCollectorRegister(event) {
    event.preventDefault();
    const errorEl = document.getElementById("collector-register-error");
    const successEl = document.getElementById("collector-register-success");
    errorEl.classList.add("hidden");
    successEl.classList.add("hidden");

    const payload = {
        name: document.getElementById("reg_name").value.trim(),
        mobile: document.getElementById("reg_mobile").value.trim(),
        password: document.getElementById("reg_password").value,
    };

    try {
        const res = await fetch("/api/auth/collector/register", {
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
        successEl.innerHTML = `Collector account created! ID: <strong>${body.data.collector_code}</strong>`;
        successEl.classList.remove("hidden");
        document.getElementById("collector-register-form").reset();
    } catch (err) {
        errorEl.textContent = "Network error: " + err.message;
        errorEl.classList.remove("hidden");
    }
}
