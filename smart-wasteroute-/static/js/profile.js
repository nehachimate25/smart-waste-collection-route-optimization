document.addEventListener("DOMContentLoaded", loadProfile);

async function loadProfile() {
    const card = document.getElementById("profile-card");
    try {
        const res = await fetch("/api/auth/me");
        const body = await res.json();
        if (!body.success || !body.data || body.data.role !== "user") {
            window.location.href = "/login";
            return;
        }
        const meRes = await fetch(`/api/users/me`);
        const meBody = await meRes.json();
        if (!meBody.success) {
            showToast(meBody.error, "error");
            return;
        }
        const user = meBody.data;

        card.innerHTML = `
            <div class="form-row"><label>User ID</label><input type="text" value="${escapeHtml(user.user_code)}" disabled></div>
            <div class="form-row"><label>Full Name</label><input type="text" id="edit_full_name" value="${escapeHtml(user.full_name)}"></div>
            <div class="form-row form-row-split">
                <div><label>Date of Birth</label><input type="text" value="${escapeHtml(user.date_of_birth)}" disabled></div>
                <div><label>Age</label><input type="text" value="${user.age} years" disabled></div>
            </div>
            <div class="form-row"><label>Email</label><input type="text" value="${escapeHtml(user.email)}" disabled></div>
            <div class="form-row"><label>Mobile</label><input type="tel" id="edit_mobile" value="${escapeHtml(user.mobile)}"></div>
            <div class="form-row"><label>Registered On</label><input type="text" value="${escapeHtml(user.created_at)}" disabled></div>
            <div class="form-actions">
                <button class="btn btn-primary" onclick="saveProfile()">Save Changes</button>
            </div>
        `;
    } catch (err) {
        card.innerHTML = `<p class="empty-row error-text">Error loading profile: ${err.message}</p>`;
    }
}

async function saveProfile() {
    const payload = {
        full_name: document.getElementById("edit_full_name").value.trim(),
        mobile: document.getElementById("edit_mobile").value.trim(),
    };
    try {
        const res = await fetch("/api/users/me", {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        const body = await res.json();
        if (!body.success) {
            showToast(body.error, "error");
            return;
        }
        showToast("Profile updated.", "success");
    } catch (err) {
        showToast("Network error: " + err.message, "error");
    }
}

function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}
