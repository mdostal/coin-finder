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

  function poll() {
    fetch("/api/jobs/" + jobId)
      .then(function (response) {
        return response.json();
      })
      .then(function (job) {
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
