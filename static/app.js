const state = {
  points: [],
  page: 1,
  pageSize: 20,
  total: 0,
  selectedPocketId: null,
  selectedStructureKind: "complex",
  viewer: null,
  viewerInitializing: false,
  viewerFailed: false,
  summary: null,
};

const elements = {
  summaryGrid: document.getElementById("summary-grid"),
  statusGrid: document.getElementById("status-grid"),
  qualityGrid: document.getElementById("quality-grid"),
  embeddingPlot: document.getElementById("embedding-plot"),
  splitPlot: document.getElementById("split-plot"),
  splitSummary: document.getElementById("split-summary"),
  searchInput: document.getElementById("search-input"),
  clusterFilter: document.getElementById("cluster-filter"),
  splitFilter: document.getElementById("split-filter"),
  affinityFilter: document.getElementById("affinity-filter"),
  activityFilter: document.getElementById("activity-filter"),
  searchButton: document.getElementById("search-button"),
  browserBody: document.getElementById("browser-body"),
  resultMeta: document.getElementById("result-meta"),
  pageLabel: document.getElementById("page-label"),
  prevPage: document.getElementById("prev-page"),
  nextPage: document.getElementById("next-page"),
  detailEmpty: document.getElementById("detail-empty"),
  detailContent: document.getElementById("detail-content"),
  detailHeader: document.getElementById("detail-header"),
  viewerStatus: document.getElementById("viewer-status"),
  molstarViewer: document.getElementById("molstar-viewer"),
  metadataList: document.getElementById("metadata-list"),
  activitySummary: document.getElementById("activity-summary"),
  activityTypeBreakdown: document.getElementById("activity-type-breakdown"),
  activityBody: document.getElementById("activity-body"),
  viewerButtons: Array.from(document.querySelectorAll(".viewer-button")),
};

async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json();
}

function formatInteger(value) {
  return Number(value || 0).toLocaleString();
}

function formatNullableNumber(value, digits = 2) {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  const num = Number(value);
  return Number.isFinite(num) ? num.toFixed(digits) : String(value);
}

function setViewerStatus(message = "", tone = "info") {
  if (!elements.viewerStatus) {
    return;
  }
  if (!message) {
    elements.viewerStatus.textContent = "";
    elements.viewerStatus.className = "viewer-status hidden";
    return;
  }
  elements.viewerStatus.textContent = message;
  elements.viewerStatus.className = `viewer-status viewer-status-${tone}`;
}

function createSummaryCard(label, value, accent, sublabel = "") {
  const card = document.createElement("article");
  card.className = "summary-card";
  card.innerHTML = `
    <span class="summary-label">${label}</span>
    <strong class="summary-value ${accent}">${value}</strong>
    <span class="summary-sublabel">${sublabel}</span>
  `;
  return card;
}

function renderSummary(summary) {
  state.summary = summary;
  const splitCounts = summary.released_split_counts || {};
  const cards = [
    ["Pocket Instances", formatInteger(summary.total_pockets), "tone-orange", "All embedded pockets in the current index"],
    ["Unique PDB Entries", formatInteger(summary.total_pdb_entries), "tone-blue", "Distinct structures represented by pockets"],
    ["Ligand Codes", formatInteger(summary.unique_ligand_codes), "tone-green", "Unique three-letter ligand identifiers"],
    ["Clusters", formatInteger(summary.cluster_count), "tone-red", "Cluster labels loaded from the projection file"],
    [`${summary.released_split_name || "Released"} Train`, formatInteger(splitCounts.train), "tone-blue", "Entries assigned to the released training split"],
    [`${summary.released_split_name || "Released"} Validation`, formatInteger(splitCounts.val), "tone-orange", "Entries assigned to the released validation split"],
    [`${summary.released_split_name || "Released"} Test`, formatInteger(splitCounts.test), "tone-red", "Entries assigned to the released test split"],
    ["Activity-Mapped Pockets", formatInteger(summary.matched_pocket_count), "tone-blue", "Pockets with at least one linked bioactivity record"],
    ["Standardized Activity", formatInteger(summary.standardized_pocket_count), "tone-green", "Pockets with a recorded affinity value"],
    ["High-Quality Activity", formatInteger(summary.high_quality_pocket_count), "tone-red", "Pockets with cleaner standardized activity aggregations"],
  ];

  elements.summaryGrid.innerHTML = "";
  for (const [label, value, accent, sublabel] of cards) {
    elements.summaryGrid.appendChild(createSummaryCard(label, value, accent, sublabel));
  }
}

function renderStatus(items) {
  elements.statusGrid.innerHTML = "";
  for (const item of items) {
    const node = document.createElement("article");
    node.className = "status-card";
    node.innerHTML = `
      <div class="status-top">
        <h3>${item.title}</h3>
        <span class="badge badge-${item.state === "implemented" ? "ok" : "warn"}">${item.state}</span>
      </div>
      <p>${item.detail}</p>
    `;
    elements.statusGrid.appendChild(node);
  }
}

function renderQualityInfo(items) {
  elements.qualityGrid.innerHTML = "";
  for (const item of items) {
    const node = document.createElement("article");
    node.className = "quality-card";
    node.innerHTML = `
      <h3>${item.field}</h3>
      <p>${item.meaning}</p>
    `;
    elements.qualityGrid.appendChild(node);
  }
}

function plotLayout(title) {
  return {
    title: { text: title, font: { family: "Space Grotesk, sans-serif", size: 18 } },
    paper_bgcolor: "#fffaf2",
    plot_bgcolor: "#fffdf8",
    margin: { l: 44, r: 24, t: 56, b: 44 },
    xaxis: { title: "Projection 1", zeroline: false, gridcolor: "#eadfce" },
    yaxis: { title: "Projection 2", zeroline: false, gridcolor: "#eadfce" },
    legend: { orientation: "h" },
  };
}

function plotConfig() {
  return { responsive: true, displaylogo: false };
}

function goToPocketPage(pocketId) {
  window.location.href = `/pocket/${encodeURIComponent(pocketId)}`;
}

function renderEmbeddingPlot(points) {
  const trace = {
    x: points.map((item) => item.projection_2d[0]),
    y: points.map((item) => item.projection_2d[1]),
    text: points.map((item) => {
      const activityLabel = item.has_standardized_activity
        ? "standardized activity"
        : item.has_activity
          ? "activity mapped"
          : "no activity";
      return `${item.pocket_id}<br>PDB ${item.pdb_id}<br>Ligand ${item.ligand_resname || "-"}<br>${activityLabel}`;
    }),
    customdata: points.map((item) => item.pocket_id),
    mode: "markers",
    type: "scattergl",
    marker: {
      size: points.map((item) => (item.has_high_quality_activity ? 8 : 6)),
      color: points.map((item) => item.cluster_label ?? -1),
      colorscale: "Turbo",
      opacity: 0.74,
      showscale: true,
      colorbar: { title: "Cluster" },
      line: {
        color: points.map((item) => (item.has_high_quality_activity ? "#7c2d12" : "rgba(0,0,0,0)")),
        width: points.map((item) => (item.has_high_quality_activity ? 1.4 : 0)),
      },
    },
    hovertemplate: "%{text}<extra></extra>",
  };

  Plotly.newPlot(elements.embeddingPlot, [trace], plotLayout("Cluster-colored embedding space"), plotConfig());
  elements.embeddingPlot.on("plotly_click", (event) => {
    const pocketId = event.points?.[0]?.customdata;
    if (pocketId) {
      goToPocketPage(pocketId);
    }
  });
}

function renderSplitSummary(counts, splitName) {
  const trainCount = counts.train || 0;
  const valCount = counts.val || 0;
  const testCount = counts.test || 0;
  const total = trainCount + valCount + testCount;
  elements.splitSummary.innerHTML = `
    <div class="split-card">
      <span class="split-label">Train</span>
      <strong>${formatInteger(trainCount)}</strong>
      <span class="split-meta">${total ? ((trainCount / total) * 100).toFixed(1) : "0.0"}%</span>
    </div>
    <div class="split-card">
      <span class="split-label">Validation</span>
      <strong>${formatInteger(valCount)}</strong>
      <span class="split-meta">${total ? ((valCount / total) * 100).toFixed(1) : "0.0"}%</span>
    </div>
    <div class="split-card">
      <span class="split-label">Test</span>
      <strong>${formatInteger(testCount)}</strong>
      <span class="split-meta">${total ? ((testCount / total) * 100).toFixed(1) : "0.0"}%</span>
    </div>
    <div class="split-card split-card-wide">
      <span class="split-label">Released split</span>
      <strong>${splitName || "Pocket split"}</strong>
      <span class="split-meta">Fixed benchmark annotation distributed with PocketEval</span>
    </div>
  `;
}

function renderSplitPlot(points) {
  const splitName = state.summary?.released_split_name || "Pocket split";
  const counts = state.summary?.released_split_counts || {};
  const train = points.filter((item) => item.split === "train");
  const val = points.filter((item) => item.split === "val");
  const test = points.filter((item) => item.split === "test");
  renderSplitSummary(counts, splitName);

  const traces = [
    {
      x: train.map((item) => item.projection_2d[0]),
      y: train.map((item) => item.projection_2d[1]),
      customdata: train.map((item) => item.pocket_id),
      text: train.map((item) => `${item.pocket_id}<br>Released split: train`),
      mode: "markers",
      type: "scattergl",
      name: "Train",
      marker: { size: 6, color: "#1864ab", opacity: 0.42 },
      hovertemplate: "%{text}<extra></extra>",
    },
    {
      x: val.map((item) => item.projection_2d[0]),
      y: val.map((item) => item.projection_2d[1]),
      customdata: val.map((item) => item.pocket_id),
      text: val.map((item) => `${item.pocket_id}<br>Released split: validation`),
      mode: "markers",
      type: "scattergl",
      name: "Validation",
      marker: { size: 7, color: "#c96a1b", opacity: 0.78 },
      hovertemplate: "%{text}<extra></extra>",
    },
    {
      x: test.map((item) => item.projection_2d[0]),
      y: test.map((item) => item.projection_2d[1]),
      customdata: test.map((item) => item.pocket_id),
      text: test.map((item) => `${item.pocket_id}<br>Released split: test`),
      mode: "markers",
      type: "scattergl",
      name: "Test",
      marker: { size: 7, color: "#c92a2a", opacity: 0.9 },
      hovertemplate: "%{text}<extra></extra>",
    },
  ];

  Plotly.newPlot(elements.splitPlot, traces, plotLayout(`Released ${splitName} split`), plotConfig());
  elements.splitPlot.on("plotly_click", (event) => {
    const pocketId = event.points?.[0]?.customdata;
    if (pocketId) {
      goToPocketPage(pocketId);
    }
  });
}

function formatPocketFlags(item) {
  if (item.has_high_quality_activity) {
    return `<span class="table-flag table-flag-strong">high-quality</span>`;
  }
  if (item.has_standardized_activity) {
    return `<span class="table-flag table-flag-mid">standardized</span>`;
  }
  if (item.has_activity) {
    return `<span class="table-flag table-flag-lite">mapped</span>`;
  }
  return `<span class="table-flag table-flag-off">none</span>`;
}

async function loadBrowser() {
  const search = encodeURIComponent(elements.searchInput.value.trim());
  const cluster = encodeURIComponent(elements.clusterFilter.value);
  const split = encodeURIComponent(elements.splitFilter.value);
  const affinity = encodeURIComponent(elements.affinityFilter.value);
  const activity = encodeURIComponent(elements.activityFilter.value);
  const payload = await fetchJson(
    `/api/pockets?q=${search}&cluster=${cluster}&split=${split}&affinity=${affinity}&activity=${activity}&page=${state.page}&page_size=${state.pageSize}`
  );
  state.total = payload.total;
  elements.browserBody.innerHTML = "";
  elements.resultMeta.textContent = `${payload.total.toLocaleString()} matching pockets`;
  elements.pageLabel.textContent = `Page ${payload.page}`;
  elements.prevPage.disabled = payload.page <= 1;
  elements.nextPage.disabled = payload.page * payload.page_size >= payload.total;

  for (const item of payload.items) {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td><a class="pocket-link" href="/pocket/${encodeURIComponent(item.pocket_id)}">${item.pocket_id}</a></td>
      <td>${item.pdb_id}</td>
      <td>${item.ligand_resname || "-"}</td>
      <td>${item.cluster_label ?? "-"}</td>
      <td>${item.split || "-"}</td>
      <td>${formatPocketFlags(item)} <span class="inline-mono">${formatInteger(item.activity_total_count)}</span></td>
      <td>${item.max_px !== null && item.max_px !== undefined ? formatNullableNumber(item.max_px) : "-"}</td>
    `;
    row.addEventListener("click", (event) => {
      if (event.target.closest("a")) {
        return;
      }
      goToPocketPage(item.pocket_id);
    });
    elements.browserBody.appendChild(row);
  }
}

function populateClusterFilter(points) {
  const labels = Array.from(new Set(points.map((item) => item.cluster_label).filter((item) => item !== null))).sort((a, b) => a - b);
  for (const label of labels) {
    const option = document.createElement("option");
    option.value = String(label);
    option.textContent = `Cluster ${label}`;
    elements.clusterFilter.appendChild(option);
  }
}

async function bootstrap() {
  const [summary, status, points, qualityInfo] = await Promise.all([
    fetchJson("/api/summary"),
    fetchJson("/api/status"),
    fetchJson("/api/points"),
    fetchJson("/api/quality-info"),
  ]);
  state.points = points.items;
  renderSummary(summary);
  renderStatus(status.items);
  renderQualityInfo(qualityInfo.items);
  populateClusterFilter(state.points);
  renderEmbeddingPlot(state.points);
  renderSplitPlot(state.points);
  await loadBrowser();
}

elements.searchButton.addEventListener("click", async () => {
  state.page = 1;
  await loadBrowser();
});
elements.searchInput.addEventListener("keydown", async (event) => {
  if (event.key === "Enter") {
    state.page = 1;
    await loadBrowser();
  }
});
elements.clusterFilter.addEventListener("change", async () => {
  state.page = 1;
  await loadBrowser();
});
elements.splitFilter.addEventListener("change", async () => {
  state.page = 1;
  await loadBrowser();
});
elements.affinityFilter.addEventListener("change", async () => {
  state.page = 1;
  await loadBrowser();
});
elements.activityFilter.addEventListener("change", async () => {
  state.page = 1;
  await loadBrowser();
});
elements.prevPage.addEventListener("click", async () => {
  if (state.page > 1) {
    state.page -= 1;
    await loadBrowser();
  }
});
elements.nextPage.addEventListener("click", async () => {
  if (state.page * state.pageSize < state.total) {
    state.page += 1;
    await loadBrowser();
  }
});
bootstrap().catch((error) => {
  console.error(error);
  alert(`Failed to initialize platform: ${error.message}`);
});
