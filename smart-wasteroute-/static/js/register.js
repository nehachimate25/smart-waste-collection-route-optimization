document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("date_of_birth").addEventListener("change", updateAgePreview);
    document.getElementById("register-form").addEventListener("submit", handleRegister);
});

function updateAgePreview() {
    const dobStr = document.getElementById("date_of_birth").value;
    const ageField = document.getElementById("computed_age");
    if (!dobStr) {
        ageField.value = "";
        return;
    }
    const dob = new Date(dobStr);
    const today = new Date();
    let age = today.getFullYear() - dob.getFullYear();
    const hasHadBirthdayThisYear = (today.getMonth() > dob.getMonth()) ||
        (today.getMonth() === dob.getMonth() && today.getDate() >= dob.getDate());
    if (!hasHadBirthdayThisYear) age -= 1;
    // This is a client-side PREVIEW only, for the user's convenience -
    // the server always recalculates age itself from date_of_birth and
    // never trusts anything the client sends for age.
    ageField.value = age >= 0 ? `${age} years` : "";
}

async function handleRegister(event) {
    event.preventDefault();
    const errorEl = document.getElementById("register-error");
    const successEl = document.getElementById("register-success");
    errorEl.classList.add("hidden");
    successEl.classList.add("hidden");

    const payload = {
        full_name: document.getElementById("full_name").value.trim(),
        date_of_birth: document.getElementById("date_of_birth").value,
        email: document.getElementById("email").value.trim(),
        mobile: document.getElementById("mobile").value.trim(),
        password: document.getElementById("password").value,
        confirm_password: document.getElementById("confirm_password").value,
    };

    try {
        const res = await fetch("/api/auth/register", {
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

        successEl.innerHTML = `Registration successful!<br>Your User ID is <strong>${body.data.user_code}</strong> - use it (or your email) to log in.`;
        successEl.classList.remove("hidden");
        document.getElementById("register-form").reset();
        showToast("Registration successful.", "success");
    } catch (err) {
        errorEl.textContent = "Network error: " + err.message;
        errorEl.classList.remove("hidden");
    }
}
