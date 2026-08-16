document.addEventListener("DOMContentLoaded", () => {
  const container = document.getElementById("cy");
  const dataEl = document.getElementById("graph-data");
  if (!container || !dataEl || typeof cytoscape === "undefined") return;

  const nodes = JSON.parse(dataEl.textContent);
  const addresses = Object.keys(nodes);
  if (addresses.length === 0) return;

  const colorFor = (info) => {
    if (info.balance) return "#2dd4a7"; // accent -- has a balance, most interesting
    if (info.confidence === "seed") return "#5b8def";
    if (info.confidence === "co-spend") return "#e0a13c";
    return "#9aa3b2"; // output / lower-confidence
  };

  const elements = [];
  addresses.forEach((addr) => {
    const info = nodes[addr];
    elements.push({
      data: {
        id: addr,
        confidence: info.confidence,
        generation: info.generation,
        balance: info.balance,
        dormant_years: info.dormant_years,
        color: colorFor(info),
        size: info.balance ? 22 : 14,
      },
    });
    if (info.discovered_via) {
      elements.push({ data: { id: `${info.discovered_via}->${addr}`, source: info.discovered_via, target: addr } });
    }
  });

  const cy = cytoscape({
    container,
    elements,
    style: [
      {
        selector: "node",
        style: {
          "background-color": "data(color)",
          width: "data(size)",
          height: "data(size)",
        },
      },
      {
        selector: "edge",
        style: {
          width: 1,
          "line-color": "#3a4150",
          "curve-style": "bezier",
          "target-arrow-shape": "none",
        },
      },
    ],
    // Ring distance = hop count -- concentric (not breadthfirst) is the
    // right layout for that: breadthfirst lays generations out as
    // horizontal bands, which falls apart when one generation has 20x
    // more nodes than another (confirmed live -- 189 nodes at one
    // generation vs 2 at another squashed everything into a sliver).
    // Concentric places nodes in genuine rings by radius, sized to fit
    // however many nodes share a ring.
    layout: {
      name: "concentric",
      concentric: (node) => -node.data("generation"),
      levelWidth: () => 1,
      minNodeSpacing: 18,
      animate: false,
      fit: true,
      padding: 20,
    },
  });

  // The container's real size isn't always settled at the moment
  // cytoscape() first measures it (e.g. mid-layout reflow) -- resize +
  // re-fit once more after the initial layout so a wide graph (dozens+
  // nodes at one generation) doesn't render partly off-screen.
  cy.resize();
  cy.fit(undefined, 20);

  const tooltip = document.createElement("div");
  tooltip.style.cssText =
    "position:fixed;pointer-events:none;background:#161a21;color:#e6e9ef;border:1px solid #262b35;" +
    "border-radius:4px;padding:6px 8px;font-size:0.85rem;display:none;z-index:10;max-width:320px;";
  document.body.appendChild(tooltip);

  function describe(node) {
    const info = node.data();
    const balance = info.balance === null || info.balance === undefined ? "unknown (inconclusive)" : info.balance;
    const dormancy =
      info.dormant_years === null || info.dormant_years === undefined ? "unknown" : `${info.dormant_years.toFixed(1)}y ago`;
    return `<code>${info.id}</code><br>confidence: ${info.confidence}, generation: ${info.generation}<br>balance: ${balance}<br>last activity: ${dormancy}`;
  }

  cy.on("mouseover", "node", (event) => {
    tooltip.innerHTML = describe(event.target);
    tooltip.style.display = "block";
    container.style.cursor = "pointer";
  });

  cy.on("mouseout", "node", () => {
    tooltip.style.display = "none";
    container.style.cursor = "default";
  });

  container.addEventListener("mousemove", (event) => {
    if (tooltip.style.display === "block") {
      tooltip.style.left = `${event.clientX + 12}px`;
      tooltip.style.top = `${event.clientY + 12}px`;
    }
  });

  cy.on("tap", "node", (event) => {
    const addr = event.target.id();
    if (!navigator.clipboard) return;
    navigator.clipboard.writeText(addr);
    tooltip.innerHTML = `Copied <code>${addr}</code>`;
    tooltip.style.display = "block";
  });
});
