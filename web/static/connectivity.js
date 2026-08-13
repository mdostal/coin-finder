(function () {
  var el = document.getElementById("conn-status");
  if (!el) return;

  function render(data) {
    var status = data.network_status;
    el.className = "conn-status conn-" + status.toLowerCase();
    el.textContent = "• " + status;

    var lines = Object.keys(data.features).map(function (key) {
      return key + ": " + data.features[key];
    });
    el.title = lines.join("\n");
  }

  function poll() {
    fetch("/api/status")
      .then(function (r) { return r.json(); })
      .then(render)
      .catch(function () {
        el.className = "conn-status conn-unknown";
        el.textContent = "• status unavailable";
      })
      .finally(function () {
        setTimeout(poll, 10000);
      });
  }

  poll();
})();
