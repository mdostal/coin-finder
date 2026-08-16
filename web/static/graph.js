document.addEventListener("DOMContentLoaded", () => {
  const canvas = document.getElementById("graph-canvas");
  const dataEl = document.getElementById("graph-data");
  if (!canvas || !dataEl) return;

  const nodes = JSON.parse(dataEl.textContent);
  const addresses = Object.keys(nodes);
  if (addresses.length === 0) return;

  const ctx = canvas.getContext("2d");
  const cx = canvas.width / 2;
  const cy = canvas.height / 2;
  const ringStep = Math.min(cx, cy) / (Math.max(...addresses.map((a) => nodes[a].generation)) + 1 || 1);

  // Ring-by-generation layout: seeds at the center, each hop further out.
  // Deterministic (no physics/force simulation) since generation + a
  // per-ring index is already a complete, stable position.
  const byGeneration = {};
  addresses.forEach((addr) => {
    const gen = nodes[addr].generation || 0;
    (byGeneration[gen] = byGeneration[gen] || []).push(addr);
  });

  const position = {};
  Object.keys(byGeneration).forEach((gen) => {
    const ring = byGeneration[gen];
    const radius = Number(gen) * ringStep;
    ring.forEach((addr, i) => {
      const angle = (2 * Math.PI * i) / ring.length - Math.PI / 2;
      position[addr] = {
        x: cx + radius * Math.cos(radius === 0 ? 0 : angle),
        y: cy + radius * Math.sin(radius === 0 ? 0 : angle),
      };
    });
  });

  const colorFor = (info) => {
    if (info.balance) return "#2dd4a7"; // accent -- has a balance, most interesting
    if (info.confidence === "seed") return "#5b8def";
    if (info.confidence === "co-spend") return "#e0a13c";
    return "#9aa3b2"; // output / lower-confidence
  };

  function draw() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // Edges first, under the nodes.
    ctx.strokeStyle = "#3a4150";
    ctx.lineWidth = 1;
    addresses.forEach((addr) => {
      const parent = nodes[addr].discovered_via;
      if (!parent || !position[parent]) return;
      ctx.beginPath();
      ctx.moveTo(position[addr].x, position[addr].y);
      ctx.lineTo(position[parent].x, position[parent].y);
      ctx.stroke();
    });

    // Nodes on top.
    addresses.forEach((addr) => {
      const p = position[addr];
      const info = nodes[addr];
      ctx.beginPath();
      ctx.fillStyle = colorFor(info);
      ctx.arc(p.x, p.y, info.balance ? 7 : 5, 0, 2 * Math.PI);
      ctx.fill();
    });
  }

  draw();

  const tooltip = document.createElement("div");
  tooltip.style.cssText =
    "position:fixed;pointer-events:none;background:#161a21;color:#e6e9ef;border:1px solid #262b35;" +
    "border-radius:4px;padding:6px 8px;font-size:0.85rem;display:none;z-index:10;max-width:320px;";
  document.body.appendChild(tooltip);

  function nearestAddress(x, y) {
    let best = null;
    let bestDist = 12; // px hit-test radius
    addresses.forEach((addr) => {
      const p = position[addr];
      const d = Math.hypot(p.x - x, p.y - y);
      if (d < bestDist) {
        bestDist = d;
        best = addr;
      }
    });
    return best;
  }

  canvas.addEventListener("mousemove", (event) => {
    const rect = canvas.getBoundingClientRect();
    const x = ((event.clientX - rect.left) / rect.width) * canvas.width;
    const y = ((event.clientY - rect.top) / rect.height) * canvas.height;
    const addr = nearestAddress(x, y);

    if (!addr) {
      tooltip.style.display = "none";
      canvas.style.cursor = "default";
      return;
    }

    const info = nodes[addr];
    const balance = info.balance === null || info.balance === undefined ? "unknown (inconclusive)" : info.balance;
    const dormancy = info.dormant_years === null || info.dormant_years === undefined ? "unknown" : `${info.dormant_years.toFixed(1)}y ago`;
    tooltip.innerHTML = `<code>${addr}</code><br>confidence: ${info.confidence}, generation: ${info.generation}<br>balance: ${balance}<br>last activity: ${dormancy}`;
    tooltip.style.left = `${event.clientX + 12}px`;
    tooltip.style.top = `${event.clientY + 12}px`;
    tooltip.style.display = "block";
    canvas.style.cursor = "pointer";
  });

  canvas.addEventListener("mouseleave", () => {
    tooltip.style.display = "none";
  });

  canvas.addEventListener("click", (event) => {
    const rect = canvas.getBoundingClientRect();
    const x = ((event.clientX - rect.left) / rect.width) * canvas.width;
    const y = ((event.clientY - rect.top) / rect.height) * canvas.height;
    const addr = nearestAddress(x, y);
    if (!addr || !navigator.clipboard) return;
    navigator.clipboard.writeText(addr);
    tooltip.innerHTML = `Copied <code>${addr}</code>`;
  });
});
