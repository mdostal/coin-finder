document.addEventListener("DOMContentLoaded", () => {
  const checkingEl = document.getElementById("ai-checking");
  const assistEl = document.getElementById("ai-assist");
  const keyFormEl = document.getElementById("ai-key-form");
  if (!checkingEl || !assistEl || !keyFormEl) return;

  // Fetched after the page has already rendered, deliberately -- checking
  // for a saved key can take several seconds (the vault call itself is
  // slow from this app's own subprocess context), and the rest of this
  // wizard page must stay usable while that's in flight.
  fetch("/ai-assist/status")
    .then((resp) => resp.json())
    .then((data) => {
      checkingEl.style.display = "none";
      (data.has_key ? assistEl : keyFormEl).style.display = "block";
    })
    .catch(() => {
      checkingEl.textContent = "Could not check for a saved API key -- reload to try again.";
    });

  const askBtn = document.getElementById("ai-ask-btn");
  const questionEl = document.getElementById("ai-question");
  const answerEl = document.getElementById("ai-answer");
  if (!askBtn || !questionEl || !answerEl) return;

  askBtn.addEventListener("click", async () => {
    const question = questionEl.value.trim();
    if (!question) return;

    const originalLabel = askBtn.textContent;
    askBtn.disabled = true;
    askBtn.textContent = "Asking…";
    answerEl.textContent = "";

    try {
      const resp = await fetch("/ai-assist/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      });
      const data = await resp.json();
      answerEl.textContent = resp.ok ? data.answer : data.error || "Something went wrong.";
    } catch (e) {
      answerEl.textContent = "Could not reach the app to ask.";
    } finally {
      askBtn.disabled = false;
      askBtn.textContent = originalLabel;
    }
  });
});
