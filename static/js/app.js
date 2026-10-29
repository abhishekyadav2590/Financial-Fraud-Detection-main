document.querySelectorAll("form[data-submit-once]").forEach((form) => {
    form.addEventListener("submit", () => {
        const submitButton = form.querySelector("button[type='submit'], input[type='submit']");
        if (!submitButton || !form.checkValidity()) {
            return;
        }
        submitButton.disabled = true;
        if (submitButton.tagName === "INPUT") {
            submitButton.value = submitButton.dataset.loadingText || "Processing...";
        } else {
            submitButton.textContent = submitButton.dataset.loadingText || "Processing...";
        }
    });
});

document.querySelectorAll("[data-password-toggle]").forEach((button) => {
    button.addEventListener("click", () => {
        const input = document.getElementById(button.dataset.passwordToggle);
        if (!input) return;
        const showing = input.type === "text";
        input.type = showing ? "password" : "text";
        button.setAttribute("aria-label", showing ? "Show password" : "Hide password");
        button.querySelector("i")?.classList.toggle("bi-eye", showing);
        button.querySelector("i")?.classList.toggle("bi-eye-slash", !showing);
    });
});

document.querySelectorAll("input[type='file']").forEach((input) => {
    input.addEventListener("change", () => {
        const target = input.closest(".upload-zone")?.querySelector("[data-file-name]");
        if (target) target.textContent = input.files?.[0]?.name || "No file selected";
    });
});

document.querySelectorAll("[data-table-search]").forEach((input) => {
    input.addEventListener("input", () => {
        const body = document.getElementById(input.dataset.tableSearch);
        const query = input.value.trim().toLowerCase();
        body?.querySelectorAll("tr").forEach((row) => {
            row.hidden = query.length > 0 && !row.textContent.toLowerCase().includes(query);
        });
    });
});
