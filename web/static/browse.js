document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".browse-btn").forEach((button) => {
    button.addEventListener("click", async () => {
      const targetInput = document.getElementById(button.dataset.target);
      if (!targetInput) return;

      const originalLabel = button.textContent;
      button.disabled = true;
      button.textContent = "Waiting for Finder…";

      try {
        const resp = await fetch("/api/pick-path", {
          method: "POST",
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
          body: `mode=${encodeURIComponent(button.dataset.mode || "file")}`,
        });
        const data = await resp.json();
        if (!resp.ok) {
          alert(data.error || "Could not open the native file picker.");
        } else if (data.path) {
          targetInput.value = data.path;
        }
      } catch (e) {
        alert("Could not reach the app to open the native file picker.");
      } finally {
        button.disabled = false;
        button.textContent = originalLabel;
      }
    });
  });
});
