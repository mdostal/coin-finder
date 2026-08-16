document.addEventListener("DOMContentLoaded", () => {
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
