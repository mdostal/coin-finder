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

// Coin filter tabs + live search -- client-side only, a simple `hidden`
// toggle per card is plenty at this app's realistic scale (a personal
// recovery tool, not a multi-tenant SaaS with hundreds of rows).
document.addEventListener("DOMContentLoaded", () => {
  const coinTabs = document.querySelectorAll(".coin-tab");
  const searchInput = document.getElementById("findings-search");
  const cards = document.querySelectorAll(".finding-card");
  const noMatches = document.getElementById("finding-list-no-matches");
  if (!cards.length) return;

  let activeCoin = "all";

  function applyFindingsFilters() {
    const query = ((searchInput && searchInput.value) || "").trim().toLowerCase();
    let visibleCount = 0;
    cards.forEach((card) => {
      const matchesCoin = activeCoin === "all" || card.dataset.coin === activeCoin;
      const matchesSearch = !query || (card.dataset.search || "").indexOf(query) !== -1;
      const show = matchesCoin && matchesSearch;
      card.hidden = !show;
      if (show) visibleCount += 1;
    });
    if (noMatches) noMatches.hidden = visibleCount !== 0;
  }

  coinTabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      coinTabs.forEach((t) => {
        t.classList.remove("active");
        t.setAttribute("aria-pressed", "false");
      });
      tab.classList.add("active");
      tab.setAttribute("aria-pressed", "true");
      activeCoin = tab.dataset.coinFilter;
      applyFindingsFilters();
    });
  });

  if (searchInput) {
    searchInput.addEventListener("input", applyFindingsFilters);
  }
});
