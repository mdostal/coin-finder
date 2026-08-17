(function () {
  var THEME_KEY = "coin-finder-theme";
  var PALETTE_KEY = "coin-finder-palette";
  var DEFAULT_THEME = "dark";
  var DEFAULT_PALETTE = "archival";

  function currentTheme() {
    return localStorage.getItem(THEME_KEY) || DEFAULT_THEME;
  }

  function currentPalette() {
    return localStorage.getItem(PALETTE_KEY) || DEFAULT_PALETTE;
  }

  // Light/dark and palette are two orthogonal axes on the same root
  // element (data-theme + data-palette) -- every palette gets a light
  // and dark variant for free from the one existing toggle mechanism.
  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    var toggles = document.querySelectorAll(".theme-toggle-btn");
    for (var i = 0; i < toggles.length; i++) {
      toggles[i].textContent = theme === "dark" ? "Light mode" : "Dark mode";
    }
  }

  function applyPalette(palette) {
    document.documentElement.setAttribute("data-palette", palette);
    var options = document.querySelectorAll("[data-palette-option]");
    for (var i = 0; i < options.length; i++) {
      var isActive = options[i].getAttribute("data-palette-option") === palette;
      options[i].classList.toggle("active", isActive);
      options[i].setAttribute("aria-pressed", isActive ? "true" : "false");
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    applyTheme(currentTheme());
    applyPalette(currentPalette());

    // Multiple toggle buttons can exist on one page (top nav + Settings) --
    // all of them bind by class, not a single id, and all read/write the
    // same localStorage-backed state.
    var toggles = document.querySelectorAll(".theme-toggle-btn");
    for (var i = 0; i < toggles.length; i++) {
      toggles[i].addEventListener("click", function () {
        var next = currentTheme() === "dark" ? "light" : "dark";
        localStorage.setItem(THEME_KEY, next);
        applyTheme(next);
      });
    }

    // Palette options only exist on the Settings page, but the same
    // apply-and-persist mechanism is shared with the toggle above.
    var options = document.querySelectorAll("[data-palette-option]");
    for (var i = 0; i < options.length; i++) {
      options[i].addEventListener("click", function () {
        var palette = this.getAttribute("data-palette-option");
        localStorage.setItem(PALETTE_KEY, palette);
        applyPalette(palette);
      });
    }
  });
})();
