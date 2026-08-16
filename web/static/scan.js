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
    const checked = Array.from(document.querySelectorAll(".bulk-select:checked"));
    if (checked.length === 0) {
      event.preventDefault();
      alert("Check at least one file first.");
      return;
    }
    // One file can carry several Bitcoin addresses (data-addresses is
    // comma-joined); union them all for the Graph/Check-fork-coins
    // actions. Harmless no-op for the Check-balances-selected action,
    // which reads the native "files" checkbox values instead.
    const addresses = checked
      .map((cb) => cb.dataset.addresses)
      .filter(Boolean)
      .join(",")
      .split(",")
      .filter(Boolean);
    bulkAddresses.value = addresses.join("\n");
  });
});
