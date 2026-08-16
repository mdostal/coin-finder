document.addEventListener("DOMContentLoaded", () => {
  const selectAll = document.getElementById("bulk-select-all");
  const bulkForm = document.getElementById("bulk-form");
  const bulkAddresses = document.getElementById("bulk-addresses");
  if (!bulkForm || !bulkAddresses) return;

  if (selectAll) {
    selectAll.addEventListener("change", () => {
      document.querySelectorAll(".bulk-select").forEach((cb) => {
        cb.checked = selectAll.checked;
      });
    });
  }

  bulkForm.addEventListener("submit", (event) => {
    const checked = Array.from(document.querySelectorAll(".bulk-select:checked")).map((cb) => cb.value);
    if (checked.length === 0) {
      event.preventDefault();
      alert("Check at least one finding first.");
      return;
    }
    bulkAddresses.value = checked.join("\n");
  });
});
