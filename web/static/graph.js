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

  // Cross-group overlap (mcrg-02) is a SEPARATE visual channel from
  // colorFor()'s confidence/balance fill -- never fold this into the fill
  // color itself, or "is this high confidence" and "is this cross-group"
  // stop being independently readable off the same node. A single-run
  // graph (item_result.html) never sets info.cross_group at all, and the
  // combined-graph route (group_view_graph.html) always sets it to a real
  // (possibly empty) list -- either way, absent/empty means "no border",
  // so the single-run view renders exactly as it always has.
  const borderFor = (info) => {
    const crossGroup = Array.isArray(info.cross_group) ? info.cross_group : [];
    if (crossGroup.length === 0) {
      return { width: 0, style: "solid", color: "transparent" };
    }
    return { width: 4, style: "dashed", color: "#f5f5f5" };
  };

  const elements = [];
  addresses.forEach((addr) => {
    const info = nodes[addr];
    const crossGroup = Array.isArray(info.cross_group) ? info.cross_group : [];
    const border = borderFor(info);
    elements.push({
      data: {
        id: addr,
        confidence: info.confidence,
        generation: info.generation,
        balance: info.balance,
        dormant_years: info.dormant_years,
        color: colorFor(info),
        size: info.balance ? 22 : 14,
        crossGroup,
        borderWidth: border.width,
        borderStyle: border.style,
        borderColor: border.color,
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
          // Independent of background-color -- this is the cross-group
          // overlap channel (mcrg-02), never a substitute for it. Zero
          // width on every non-cross-group node (including every node in
          // the single-run view, which never sets cross_group) renders
          // identically to before this border existed.
          "border-width": "data(borderWidth)",
          "border-style": "data(borderStyle)",
          "border-color": "data(borderColor)",
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

  // "never a bare label without the real evidence behind it" -- same
  // discipline compute_confidence_scores follows for its confidence_label
  // (always returned with the raw counts that produced it). A cross-group
  // node's tooltip must show which specific runs/seeds found it, not just
  // an unadorned "overlap" tag.
  function describeCrossGroup(crossGroup) {
    if (!crossGroup || crossGroup.length === 0) return "";
    const lines = crossGroup
      .map((entry) => {
        const seeds = Array.isArray(entry.seed_addresses) ? entry.seed_addresses.join(", ") : "unknown seed";
        return `&nbsp;&nbsp;run ${entry.run_id} (seed: ${seeds}) -- ${entry.confidence}, gen ${entry.generation}`;
      })
      .join("<br>");
    return `<br><strong>cross-group:</strong> found independently by ${crossGroup.length} of the selected runs<br>${lines}`;
  }

  function describe(node) {
    const info = node.data();
    const balance = info.balance === null || info.balance === undefined ? "unknown (inconclusive)" : info.balance;
    const dormancy =
      info.dormant_years === null || info.dormant_years === undefined ? "unknown" : `${info.dormant_years.toFixed(1)}y ago`;
    return (
      `<code>${info.id}</code><br>confidence: ${info.confidence}, generation: ${info.generation}<br>` +
      `balance: ${balance}<br>last activity: ${dormancy}${describeCrossGroup(info.crossGroup)}`
    );
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
    // Copy confirmation plus the same real evidence hover shows -- a
    // click must not lose the cross-group runs/seeds behind a bare
    // "Copied" message.
    tooltip.innerHTML = `Copied <code>${addr}</code>${describeCrossGroup(event.target.data("crossGroup"))}`;
    tooltip.style.display = "block";
  });
});
