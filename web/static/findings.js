document.addEventListener("DOMContentLoaded", () => {
  const selectAll = document.getElementById("bulk-select-all");
  const bulkForm = document.getElementById("bulk-form");
  const bulkAddresses = document.getElementById("bulk-addresses");
  const bulkWatchSelection = document.getElementById("bulk-watch-selection");
  const bulkTryUnlock = document.getElementById("bulk-try-unlock");
  const bulkWalletPaths = document.getElementById("bulk-wallet-paths");
  const bulkExtractKeys = document.getElementById("bulk-extract-keys");

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

      // "Check credential status" (ccu-03) needs wallet file paths, not
      // addresses -- same data-source-path attribute bulk-try-unlock
      // below reads, just submitted through this shared form instead of
      // a separate confirmation page (this action has no network/vault
      // safety gate to confirm, unlike Try-unlock).
      const isCredentialStatus = !!(submitter && submitter.dataset.credentialStatus === "1");
      if (isCredentialStatus) {
        const walletPaths = Array.from(new Set(checked.map((cb) => cb.dataset.sourcePath).filter(Boolean)));
        if (walletPaths.length === 0) {
          event.preventDefault();
          alert("Check at least one finding with a known wallet file first.");
          return;
        }
        if (bulkWalletPaths) bulkWalletPaths.value = walletPaths.join("\n");
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

  // Submits a POST with one hidden <input name="fieldName"> per value,
  // then navigates there -- used instead of a GET `?fieldName=...&
  // fieldName=...` query string for bulk selections, which can carry
  // enough repeated params to exceed the server's URI-length limit long
  // before Flask ever sees the request (confirmed live: a 414 "URI Too
  // Long" on a large bulk "Try unlock selected" selection). A form body
  // has no comparable practical size ceiling for this.
  function submitBulkSelection(actionUrl, fieldName, values) {
    const form = document.createElement("form");
    form.method = "POST";
    form.action = actionUrl;
    form.style.display = "none";
    values.forEach((value) => {
      const input = document.createElement("input");
      input.type = "hidden";
      input.name = fieldName;
      input.value = value;
      form.appendChild(input);
    });
    document.body.appendChild(form);
    form.submit();
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
      // Posts to the same auto-unlock confirmation page the per-finding
      // "Try unlock" link uses -- no job starts on this click, same
      // safety gate (network check, vault check, explicit Run) as every
      // other unlock entry point.
      submitBulkSelection(bulkTryUnlock.dataset.unlockConfirmUrl, "wallet_path", paths);
    });
  }

  if (bulkExtractKeys) {
    bulkExtractKeys.addEventListener("click", () => {
      // bpk-02: mirrors bulk-try-unlock's pattern above, but filters to
      // data-key-extractable="1" (bpk-01) rows and builds one
      // "wallet_path\taddress" pair per row -- extraction is per-address,
      // not per-wallet, so a bare source-path list (like Try-unlock's)
      // isn't enough here. The server re-derives and re-filters this
      // same candidate set on its own before running anything -- this
      // client-side filter is a UX nicety, not the real safety check.
      const pairs = Array.from(document.querySelectorAll(".bulk-select:checked"))
        .filter((cb) => cb.dataset.keyExtractable === "1" && cb.dataset.sourcePath)
        .map((cb) => `${cb.dataset.sourcePath}\t${cb.value}`);
      if (pairs.length === 0) {
        alert("None of the checked findings have a known extractable key -- run Check credential status first if you haven't yet.");
        return;
      }
      submitBulkSelection(bulkExtractKeys.dataset.extractConfirmUrl, "pair", pairs);
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
