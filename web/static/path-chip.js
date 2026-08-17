document.addEventListener("click", (event) => {
  const btn = event.target.closest(".path-chip-copy");
  if (!btn) return;
  const path = btn.getAttribute("data-path");
  navigator.clipboard.writeText(path).then(() => {
    const original = btn.textContent;
    btn.textContent = "Copied";
    setTimeout(() => { btn.textContent = original; }, 1200);
  });
});
