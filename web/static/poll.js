(function () {
  var script = document.currentScript;
  var jobId = script.getAttribute("data-job-id");
  var initialStatus = script.getAttribute("data-status");
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
