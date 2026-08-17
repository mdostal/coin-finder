(function () {
  var STORAGE_KEY = "coin-finder-theme";

  function apply(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    var toggle = document.getElementById("theme-toggle");
    if (toggle) toggle.textContent = theme === "dark" ? "Light mode" : "Dark mode";
  }

  function current() {
    return localStorage.getItem(STORAGE_KEY) || "dark";
  }

  document.addEventListener("DOMContentLoaded", function () {
    apply(current());
    var toggle = document.getElementById("theme-toggle");
    if (!toggle) return;
    toggle.addEventListener("click", function () {
      var next = current() === "dark" ? "light" : "dark";
      localStorage.setItem(STORAGE_KEY, next);
      apply(next);
    });
  });
})();
