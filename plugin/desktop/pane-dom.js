/** Part studio view. No imports: the desktop bundle and the headless preview share this file. */

function mountPane(root, state, actions, css) {
  if (!root) return;
  ensurePaneStyle(css);
  const model = state && typeof state === "object" ? state : {};
  root.textContent = "";
  root.className = "p2p-host";
  const pane = el("section", "p2p");
  pane.setAttribute("aria-label", "Part studio");
  root.appendChild(pane);
  if (model.backend === "loading") {
    pane.appendChild(emptyBlock("Part studio", "Looking for the current part run."));
    return;
  }
  if (model.backend === "offline") {
    pane.appendChild(emptyBlock("Part studio is offline", model.message || "Enable photo-to-part, then rescan plugins. The tools still run without this pane."));
    return;
  }
  if (!model.run) {
    pane.appendChild(emptyBlock("No part run yet", "Ask Hermes to recreate a part from a photo. Stages, the overlay, each render, and the STL paths show up here while the tools run."));
    return;
  }
  const run = model.run;
  pane.appendChild(header(run));
  if (Array.isArray(model.runs) && model.runs.length > 1) {
    pane.appendChild(runSwitcher(model, actions));
  }
  pane.appendChild(steps(run.stages));
  const note = el("p", "p2p-message");
  note.appendChild(document.createTextNode(run.message || "Working."));
  if (run.tool) {
    note.appendChild(el("span", "p2p-tool", "  ·  " + run.tool));
  }
  pane.appendChild(note);
  pane.appendChild(compare(run));
  pane.appendChild(metrics(run.metrics || {}));
  pane.appendChild(approvalBlock(run.approval || {}));
  pane.appendChild(flags(run));
  pane.appendChild(outputs(run.outputs));
  pane.appendChild(film(run, model.selectedIteration, actions));
}

function header(run) {
  const top = el("div", "p2p-top");
  const brand = el("div", "p2p-brand");
  brand.appendChild(el("div", "p2p-mark"));
  const names = el("div");
  names.appendChild(el("p", "p2p-kicker", "Part studio"));
  names.appendChild(el("h1", "p2p-title", run.title || "Untitled part"));
  brand.appendChild(names);
  top.appendChild(brand);
  const status = run.status || "idle";
  const live = el("div", "p2p-live is-" + status);
  live.appendChild(el("i", "p2p-dot"));
  live.appendChild(document.createTextNode(statusLabel(status, run.stage_label)));
  top.appendChild(live);
  return top;
}

function statusLabel(status, stage) {
  if (status === "waiting") return "Approval";
  if (status === "ready") return "Ready";
  if (status === "error") return "Error";
  if (status === "running") return stage || "Live";
  return "Idle";
}

function steps(rows) {
  const list = el("ol", "p2p-steps");
  (rows || []).forEach(function (row) {
    const item = el("li", "p2p-step is-" + (row.state || "pending"));
    item.appendChild(el("i"));
    item.appendChild(document.createTextNode(row.label || row.id || ""));
    list.appendChild(item);
  });
  return list;
}

function compare(run) {
  const images = run.images || {};
  const grid = el("div", "p2p-compare");
  const left = images.overlay || images.photo || "";
  const leftLabel = images.overlay ? "Photo + overlay" : "Photo";
  const right = images.render || images.compare || "";
  const version = run.iteration ? "Render v" + run.iteration : "Render";
  grid.appendChild(shot(left, leftLabel, "Input photo"));
  grid.appendChild(shot(right, version, "Latest render"));
  return grid;
}

function shot(src, caption, alt) {
  const figure = el("figure", "p2p-shot");
  if (imageSrc(src)) {
    const img = el("img");
    img.src = imageSrc(src);
    img.alt = alt;
    figure.appendChild(img);
  } else {
    figure.appendChild(el("div", "p2p-fallback", "Waiting"));
  }
  figure.appendChild(el("figcaption", "", caption));
  return figure;
}

function metrics(metrics) {
  const grid = el("div", "p2p-metrics");
  grid.appendChild(metric("Overlay IoU", formatIou(metrics), metrics.iou_label || ""));
  grid.appendChild(metric("Scale", scaleLabel(metrics.scale_source), confidenceLine(metrics)));
  const trust = el("div", "p2p-metric");
  trust.appendChild(el("b", "", "Trust"));
  const pill = el("span", "p2p-trust is-" + trustClass(metrics.trust), metrics.trust || "pending");
  trust.appendChild(pill);
  grid.appendChild(trust);
  grid.appendChild(metric("Dimensions", metrics.dimensions || "Not set", metrics.px_per_mm ? metrics.px_per_mm + " px/mm" : ""));
  return grid;
}

function metric(label, value, sub) {
  const node = el("div", "p2p-metric");
  node.appendChild(el("b", "", label));
  node.appendChild(el("strong", "", value || "—"));
  if (sub) node.appendChild(el("em", "", sub));
  return node;
}

function formatIou(metrics) {
  const value = Number(metrics.iou);
  if (!Number.isFinite(value)) return "—";
  return value.toFixed(3);
}

function scaleLabel(text) {
  const raw = String(text || "").trim();
  const known = {
    "us quarter": "US quarter",
    "us penny": "US penny",
    "us nickel": "US nickel",
    "us dime": "US dime",
    "us half": "US half",
    "euro 1": "€1",
    "euro 2": "€2",
    "euro 50c": "50¢ euro",
    "gbp 1": "£1",
    "cad quarter": "CAD quarter",
    "cad loonie": "CAD loonie",
    "user part dimension": "Part dimension",
  };
  return known[raw.toLowerCase()] || raw || "Unknown";
}

function confidenceLine(metrics) {
  return [metrics.scale_confidence, metrics.scale_note].filter(Boolean).join(" · ");
}

function trustClass(trust) {
  const text = String(trust || "pending").toLowerCase();
  if (text === "trusted") return "trusted";
  if (text === "untrusted") return "untrusted";
  if (text.indexOf("guide") >= 0) return "guide";
  return "pending";
}

function approvalBlock(approval) {
  const section = el("div", "p2p-section");
  section.appendChild(el("p", "p2p-label", "Approval gate"));
  const line = el("p", "p2p-approval");
  line.appendChild(el("strong", "", approvalLabel(approval.status)));
  if (approval.message) {
    line.appendChild(document.createTextNode(" — " + approval.message));
  }
  section.appendChild(line);
  return section;
}

function approvalLabel(status) {
  return {
    waiting: "Waiting",
    approved: "Approved",
    skipped: "Skipped",
    not_required: "Not required",
    idle: "Not asked yet",
  }[status] || "Not asked yet";
}

function flags(run) {
  const section = el("div", "p2p-section");
  section.appendChild(el("p", "p2p-label", "Warnings and errors"));
  const errors = run.errors || [];
  const warnings = run.warnings || [];
  if (!errors.length && !warnings.length) {
    section.appendChild(el("p", "p2p-quiet", "None."));
    return section;
  }
  errors.slice(0, 4).forEach(function (text) {
    const row = el("p", "p2p-flag is-bad");
    row.appendChild(el("strong", "", "Error"));
    row.appendChild(document.createTextNode(" " + text));
    section.appendChild(row);
  });
  warnings.slice(0, 4).forEach(function (text) {
    const row = el("p", "p2p-flag");
    row.appendChild(el("strong", "", "Warning"));
    row.appendChild(document.createTextNode(" " + text));
    section.appendChild(row);
  });
  return section;
}

function outputs(items) {
  const section = el("div", "p2p-section");
  section.appendChild(el("p", "p2p-label", "STL and CAD"));
  if (!items || !items.length) {
    section.appendChild(el("p", "p2p-quiet", "Paths appear when a build writes them."));
    return section;
  }
  const list = el("div", "p2p-outputs");
  items.forEach(function (item) {
    const row = el("p", "p2p-path");
    row.appendChild(el("span", "", item.kind || "FILE"));
    row.appendChild(el("code", "", item.path || ""));
    list.appendChild(row);
  });
  section.appendChild(list);
  return section;
}

function film(run, selected, actions) {
  const section = el("div", "p2p-section");
  section.appendChild(el("p", "p2p-label", "Iterations"));
  const items = run.iterations || [];
  if (!items.length) {
    section.appendChild(el("p", "p2p-quiet", "Each render joins this strip."));
    return section;
  }
  const strip = el("div", "p2p-film");
  items.forEach(function (item) {
    const on = selected ? item.n === selected : item.active;
    const button = el("button", "p2p-iter" + (on ? " is-on" : ""));
    button.type = "button";
    button.addEventListener("click", function () {
      if (actions && typeof actions.onSelectIteration === "function") {
        actions.onSelectIteration(item);
      }
    });
    if (imageSrc(item.thumb)) {
      const img = el("img");
      img.src = imageSrc(item.thumb);
      img.alt = "";
      button.appendChild(img);
    } else {
      button.appendChild(el("div", "p2p-fallback", item.label || ""));
    }
    const iou = Number(item.iou);
    const detail = (item.label || "") + (Number.isFinite(iou) ? "  " + iou.toFixed(2) : "") + (item.trust ? "  " + item.trust : "");
    button.appendChild(el("small", "", detail));
    strip.appendChild(button);
  });
  section.appendChild(strip);
  return section;
}

function runSwitcher(model, actions) {
  const row = el("div", "p2p-runs");
  model.runs.forEach(function (item) {
    const button = el("button", "p2p-run" + (item.id === model.selectedRun ? " is-on" : ""));
    button.type = "button";
    button.textContent = item.title || item.id;
    button.addEventListener("click", function () {
      if (actions && typeof actions.onSelectRun === "function") actions.onSelectRun(item.id);
    });
    row.appendChild(button);
  });
  return row;
}

function emptyBlock(title, copy) {
  const block = el("div", "p2p-empty");
  const brand = el("div", "p2p-brand");
  brand.appendChild(el("div", "p2p-mark"));
  const names = el("div");
  names.appendChild(el("p", "p2p-kicker", "Part studio"));
  brand.appendChild(names);
  block.appendChild(brand);
  block.appendChild(el("h2", "", title));
  block.appendChild(el("p", "", copy));
  return block;
}

function imageSrc(value) {
  return typeof value === "string" && value.indexOf("data:image/") === 0 ? value : "";
}

function ensurePaneStyle(css) {
  if (!css || document.getElementById("p2p-pane-style")) return;
  const style = document.createElement("style");
  style.id = "p2p-pane-style";
  style.textContent = css;
  document.head.appendChild(style);
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null && text !== "") node.textContent = text;
  return node;
}
