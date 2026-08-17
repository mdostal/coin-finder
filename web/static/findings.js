document.addEventListener("DOMContentLoaded", () => {
  const selectAll = document.getElementById("bulk-select-all");
  const bulkForm = document.getElementById("bulk-form");
  const bulkAddresses = document.getElementById("bulk-addresses");
  const bulkWatchSelection = document.getElementById("bulk-watch-selection");
  const bulkTryUnlock = document.getElementById("bulk-try-unlock");

  if (selectAll) {
    selectAll.addEventListener("change", () => {
      document.querySelectorAll(".bulk-select").forEach((cb) => {
        cb.checked = selectAll.checked;
      });
    });
  }

  if (bulkForm && bulkAddresses) {
    bulkForm.addEventListener("submit", (event) => {
      const checked = Array.from(document.querySelectorAll(".bulk-select:checked"));
      if (checked.length === 0) {
        event.preventDefault();
        alert("Check at least one finding first.");
        return;
      }

      // Graph/Check-fork-coins are genuinely Bitcoin-only tools -- scope
      // those two down to just the checked Bitcoin rows. Watch/Try-unlock
      // (the other two formaction targets on this same shared form) apply
      // to any coin, so they use the full checked set unfiltered.
      const submitter = event.submitter;
      const btcOnly = !!(submitter && submitter.dataset.btcOnly === "1");
      const relevant = btcOnly ? checked.filter((cb) => cb.dataset.coin === "Bitcoin") : checked;
      if (btcOnly && relevant.length === 0) {
        event.preventDefault();
        alert("None of the checked findings are Bitcoin -- this action only applies to Bitcoin findings.");
        return;
      }

      bulkAddresses.value = relevant.map((cb) => cb.value).join("\n");
      if (bulkWatchSelection) {
        // One "coin\taddress" pair per line -- address alone can't
        // disambiguate across coins the way it can for the Bitcoin-only
        // addresses field above.
        bulkWatchSelection.value = checked.map((cb) => `${cb.dataset.coin}\t${cb.value}`).join("\n");
      }
    });
  }

  if (bulkTryUnlock) {
    bulkTryUnlock.addEventListener("click", () => {
      const paths = Array.from(document.querySelectorAll(".bulk-select:checked"))
        .map((cb) => cb.dataset.sourcePath)
        .filter(Boolean);
      if (paths.length === 0) {
        alert("Check at least one finding with a known wallet file first.");
        return;
      }
      const params = new URLSearchParams();
      paths.forEach((p) => params.append("wallet_path", p));
      // Navigates to the same auto-unlock confirmation page the
      // per-finding "Try unlock" link uses -- no job starts on this
      // click, same safety gate (network check, vault check, explicit
      // Run) as every other unlock entry point.
      window.location.href = `${bulkTryUnlock.dataset.unlockUrl}?${params.toString()}`;
    });
  }
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
