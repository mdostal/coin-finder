(function () {
  var script = document.currentScript;
  var jobId = script.getAttribute("data-job-id");
  var initialStatus = script.getAttribute("data-status");
  // Optional: navigate here instead of reloading in place once the job
  // leaves "running" -- used by the unlock flow, whose status page never
  // carries the secret-bearing result itself (see web/jobs.py).
  var doneUrl = script.getAttribute("data-done-url");
  if (!jobId || initialStatus !== "running") {
    return;
  }

  function renderProgress(job) {
    var container = document.getElementById("job-progress");
    if (!container || !job.progress) return;

    var indeterminate = !job.progress.total;
    var pct = indeterminate ? 0 : Math.round((job.progress.current / job.progress.total) * 100);

    container.textContent = "";

    var bar = document.createElement("div");
    bar.className = indeterminate ? "progress-bar progress-bar-indeterminate" : "progress-bar";
    var fill = document.createElement("div");
    fill.className = "progress-bar-fill";
    if (!indeterminate) fill.style.width = pct + "%";
    bar.appendChild(fill);

    var label = document.createElement("div");
    label.className = "progress-label";
    var text = indeterminate ? String(job.progress.current) : job.progress.current + " / " + job.progress.total;
    if (job.progress.message) text += " — " + job.progress.message;
    label.textContent = text;

    container.appendChild(bar);
    container.appendChild(label);
  }

  function poll() {
    fetch("/api/jobs/" + jobId)
      .then(function (response) {
        return response.json();
      })
      .then(function (job) {
        renderProgress(job);
        if (job.status === "running") {
          setTimeout(poll, 2000);
        } else if (doneUrl) {
          window.location.href = doneUrl;
        } else {
          window.location.reload();
        }
      })
      .catch(function () {
        setTimeout(poll, 5000);
      });
  }

  setTimeout(poll, 2000);
})();
