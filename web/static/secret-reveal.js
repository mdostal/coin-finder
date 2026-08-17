// Eye-toggle reveal for secret values (auto-unlock result's Password
// column, vault reveal page) that are already present in the page's
// initial HTML via a data-secret attribute -- the once-only
// consume_job_result()/vault-resolve call already happened server-side
// on this one page load. This is a pure client-side mask/unmask swap:
// no new network request, no navigation. See
// .pHive/epics/credential-clarity-and-unlock-ux/stories/ccu-01.yaml.
(function () {
  var MASK_TEXT = "••••••••";
  var EYE_OPEN = "👁";
  var EYE_CLOSED = "🙈";

  document.addEventListener("click", function (event) {
    var btn = event.target.closest(".secret-reveal-btn");
    if (!btn) return;

    var field = btn.closest(".secret-field");
    var mask = field ? field.querySelector(".secret-mask") : null;
    if (!mask) return;

    var revealed = mask.getAttribute("data-revealed") === "true";
    if (revealed) {
      mask.textContent = MASK_TEXT;
      mask.setAttribute("data-revealed", "false");
      btn.textContent = EYE_OPEN;
      btn.setAttribute("aria-label", "Reveal value");
      btn.setAttribute("aria-pressed", "false");
    } else {
      mask.textContent = mask.getAttribute("data-secret");
      mask.setAttribute("data-revealed", "true");
      btn.textContent = EYE_CLOSED;
      btn.setAttribute("aria-label", "Hide value");
      btn.setAttribute("aria-pressed", "true");
    }
  });
})();
