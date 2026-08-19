(function () {
  // Resource-profile section of the Settings page (structured-outline.md
  // #1.6). Only present on /settings -- every selector below is scoped to
  // elements that only exist there, mirroring theme.js's own pattern of a
  // single global script that's a no-op on any other page.
  var FIELDS = [
    "search_walk_threads",
    "analyze_processes",
    "check_balances_global_workers",
    "check_balances_per_coin_concurrency",
  ];

  function byId(id) {
    return document.getElementById(id);
  }

  function setStatus(message) {
    var el = byId("resource-profile-status");
    if (el) el.textContent = message || "";
  }

  // Applies a fetched {mode, overrides, auto} payload to the DOM: which
  // section is visible, the mode toggle's pressed state, the auto
  // display's live numbers, and the custom inputs' current values (an
  // override when set, else the same auto number as a sensible starting
  // point to edit from).
  function render(settings) {
    var isCustom = settings.mode === "custom";

    var autoBtn = byId("resource-profile-mode-auto");
    var customBtn = byId("resource-profile-mode-custom");
    if (autoBtn) autoBtn.setAttribute("aria-pressed", isCustom ? "false" : "true");
    if (customBtn) customBtn.setAttribute("aria-pressed", isCustom ? "true" : "false");

    var autoDisplay = byId("resource-profile-auto-display");
    var customFields = byId("resource-profile-custom-fields");
    if (autoDisplay) autoDisplay.hidden = isCustom;
    if (customFields) customFields.hidden = !isCustom;

    for (var i = 0; i < FIELDS.length; i++) {
      var field = FIELDS[i];
      var autoEl = byId("resource-profile-auto-" + field);
      if (autoEl) autoEl.textContent = settings.auto[field];

      var input = byId("resource-profile-custom-" + field);
      if (input) {
        var override = settings.overrides[field];
        input.value = override !== null && override !== undefined ? override : settings.auto[field];
      }
    }
  }

  function loadSettings() {
    return fetch("/api/scan-settings")
      .then(function (resp) {
        return resp.json();
      })
      .then(render);
  }

  function setMode(mode) {
    setStatus("Saving...");
    fetch("/api/scan-settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: mode }),
    })
      .then(function (resp) {
        return resp.json();
      })
      .then(function (settings) {
        render(settings);
        setStatus(mode === "custom" ? "Custom mode -- edit any field below." : "Auto mode -- values update live from this machine.");
      })
      .catch(function () {
        setStatus("Failed to save -- try again.");
      });
  }

  function setOverride(field, rawValue) {
    var value = rawValue === "" ? null : parseInt(rawValue, 10);
    if (value !== null && (isNaN(value) || value < 1)) {
      setStatus("Enter a whole number of 1 or more, or leave blank to use auto.");
      return;
    }

    var overrides = {};
    overrides[field] = value;

    setStatus("Saving...");
    fetch("/api/scan-settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ overrides: overrides }),
    })
      .then(function (resp) {
        return resp.json();
      })
      .then(function (settings) {
        render(settings);
        setStatus("Saved -- takes effect on the next job you start.");
      })
      .catch(function () {
        setStatus("Failed to save -- try again.");
      });
  }

  document.addEventListener("DOMContentLoaded", function () {
    if (!byId("resource-profile-card")) return;

    loadSettings();

    var autoBtn = byId("resource-profile-mode-auto");
    var customBtn = byId("resource-profile-mode-custom");
    if (autoBtn) autoBtn.addEventListener("click", function () { setMode("auto"); });
    if (customBtn) customBtn.addEventListener("click", function () { setMode("custom"); });

    for (var i = 0; i < FIELDS.length; i++) {
      (function (field) {
        var input = byId("resource-profile-custom-" + field);
        if (!input) return;
        input.addEventListener("change", function () {
          setOverride(field, input.value);
        });
      })(FIELDS[i]);
    }
  });
})();
