const pocketId = decodeURIComponent(window.location.pathname.split("/pocket/")[1] || "").trim();

const state = {
  pocketId,
  viewer: null,
  record: null,
  activity: null,
  selectedKind: "surface",
  selectedActivityTypes: new Set(),
};

const elements = {
  title: document.getElementById("detail-page-title"),
  subtitle: document.getElementById("detail-page-subtitle"),
  viewerStatus: document.getElementById("detail-viewer-status"),
  metadata: document.getElementById("detail-metadata"),
  ligandProperties: document.getElementById("detail-ligand-properties"),
  assetLinks: document.getElementById("detail-asset-links"),
  activitySummary: document.getElementById("detail-activity-summary"),
  activityBreakdown: document.getElementById("detail-activity-breakdown"),
  activityBody: document.getElementById("detail-activity-body"),
  viewerButtons: Array.from(document.querySelectorAll(".viewer-button")),
};

async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json();
}

async function fetchText(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.text();
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
  if (!message) {
    elements.viewerStatus.textContent = "";
    elements.viewerStatus.className = "viewer-status hidden";
    return;
  }
  elements.viewerStatus.textContent = message;
  elements.viewerStatus.className = `viewer-status viewer-status-${tone}`;
}

function updateViewerButtons(kind) {
  elements.viewerButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.kind === kind);
  });
}

function syncViewerSize(viewer) {
  if (!viewer) {
    return;
  }
  const container = document.getElementById("structure-viewer");
  if (!container) {
    return;
  }
  const width = container.clientWidth;
  const height = container.clientHeight;
  if (width > 0 && height > 0 && typeof viewer.resize === "function") {
    viewer.resize(width, height);
  }
}
function renderDescriptionList(target, items) {
  target.innerHTML = "";
  for (const [label, value] of items) {
    const dt = document.createElement("dt");
    dt.textContent = label;
    const dd = document.createElement("dd");
    dd.textContent = value ?? "-";
    target.appendChild(dt);
    target.appendChild(dd);
  }
}

function renderMetadata(record) {
  const ligand = record.ligand || {};
  const cluster = record.cluster || {};
  const activity = record.activity_summary || {};
  const coords = cluster.projection_2d || [0, 0];
  renderDescriptionList(elements.metadata, [
    ["Pocket ID", record.pocket_id],
    ["PDB ID", record.pdb_id],
    ["Ligand", ligand.resname],
    ["Chain", ligand.chain_id],
    ["Residue Number", ligand.resseq],
    ["Cluster", cluster.cluster_label],
    ["Projection", `${formatNullableNumber(coords[0])}, ${formatNullableNumber(coords[1])}`],
    ["Protein Residues", record.protein_residue_count],
    ["Patch Count", record.embedding?.patch_count],
    ["Embedding Dim", record.embedding?.embedding_dim],
    ["Activity Links", activity.activity_total_count],
    ["Max pX", activity.max_px],
    ["Embedding Resource", record.downloads?.embedding_npy || "resource_bundle/embeddings/<pocket_id>.npy"],
    ["Created", record.created_at_utc],
    ["Status", record.status],
  ]);
}

function renderLigandProperties(record) {
  const props = record.ligand_properties || {};
  if (props.status !== "computed") {
    renderDescriptionList(elements.ligandProperties, [
      ["Status", props.status || "unavailable"],
      ["Source", props.source || "resource_bundle"],
      ["Reason", props.reason || "Ligand properties are unavailable for this pocket."],
    ]);
    return;
  }

  renderDescriptionList(elements.ligandProperties, [
    ["Formula", props.formula],
    ["Mol Weight", props.molecular_weight],
    ["LogP", props.logp],
    ["TPSA", props.tpsa],
    ["H Donors", props.h_donors],
    ["H Acceptors", props.h_acceptors],
    ["Rotatable Bonds", props.rotatable_bonds],
    ["Ring Count", props.ring_count],
    ["Heavy Atoms", props.heavy_atom_count],
    ["Atom Count", props.atom_count],
  ]);
}

function renderAssetLinks(record) {
  const downloads = record.downloads || {};
  const items = [
    ["Download MaSIF Embedding (.npy)", downloads.embedding_npy],
    ["Pocket Complex (.pdb)", downloads.complex_pdb],
    ["Pocket Protein (.pdb)", downloads.protein_pdb],
    ["Ligand (.pdb)", downloads.ligand_pdb],
  ].filter((item) => item[1]);

  elements.assetLinks.innerHTML = items
    .map(([label, href]) => `<a class="asset-link" href="${href}" target="_blank" rel="noreferrer">${label}</a>`)
    .join("");
}

function renderTypeBreakdown(typeBreakdown) {
  const entries = Object.entries(typeBreakdown || {});
  if (!entries.length) {
    elements.activityBreakdown.innerHTML = "";
    return;
  }
  elements.activityBreakdown.innerHTML = "";
  const allButton = document.createElement("button");
  allButton.type = "button";
  allButton.className = `breakdown-chip breakdown-chip-button${state.selectedActivityTypes.size === 0 ? " active" : ""}`;
  allButton.textContent = "All";
  allButton.addEventListener("click", () => {
    state.selectedActivityTypes.clear();
    renderTypeBreakdown(typeBreakdown);
    renderActivityTable(state.activity);
  });
  elements.activityBreakdown.appendChild(allButton);

  for (const [label, count] of entries.sort((a, b) => b[1] - a[1])) {
    const button = document.createElement("button");
    const isActive = state.selectedActivityTypes.has(label);
    button.type = "button";
    button.className = `breakdown-chip breakdown-chip-button${isActive ? " active" : ""}`;
    button.textContent = `${label} · ${count}`;
    button.addEventListener("click", () => {
      if (state.selectedActivityTypes.has(label)) {
        state.selectedActivityTypes.delete(label);
      } else {
        state.selectedActivityTypes.add(label);
      }
      renderTypeBreakdown(typeBreakdown);
      renderActivityTable(state.activity);
    });
    elements.activityBreakdown.appendChild(button);
  }
}

function renderActivityTable(activity) {
  const selectedTypes = state.selectedActivityTypes;
  const records = selectedTypes.size
    ? activity.strict_records.filter((item) => selectedTypes.has(item.standard_type))
    : activity.strict_records;
  elements.activityBody.innerHTML = "";
  if (!records.length) {
    const row = document.createElement("tr");
    row.innerHTML = `<td colspan="5">${
      selectedTypes.size
        ? `No activity record with selected standard_type filters is available for this pocket.`
        : "No ligand-linked activity record is available for this pocket."
    }</td>`;
    elements.activityBody.appendChild(row);
    return;
  }

  for (const item of records) {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${item.standard_type || "-"}</td>
      <td>${item.standard_relation || "-"}</td>
      <td>${item.standard_value || "-"}</td>
      <td>${item.standard_units || "-"}</td>
      <td>${item.px_value || "-"}</td>
    `;
    elements.activityBody.appendChild(row);
  }
}

function renderActivity(activity) {
  elements.activitySummary.innerHTML = `
    <p><strong>Ligand-linked records:</strong> ${formatInteger(activity.strict_record_count)}</p>
    <p><strong>Standardized records:</strong> ${formatInteger(activity.standardized_record_count)}</p>
    <p><strong>High-quality activity records:</strong> ${formatInteger(activity.high_quality_record_count)}</p>
    <p><strong>Local benchmark pX:</strong> ${activity.local_pX ?? state.record?.local_benchmark_activity?.pX ?? "-"}</p>
    <p><strong>Released split:</strong> ${activity.local_split ?? state.record?.local_benchmark_activity?.split ?? "-"}</p>
    <p class="subtle">${activity.error ? `Query warning: ${activity.error}` : activity.note}</p>
  `;
  renderTypeBreakdown(activity.standard_type_breakdown);
  renderActivityTable(activity);
}

async function ensureViewer() {
  if (state.viewer) {
    return state.viewer;
  }
  if (!window.$3Dmol || typeof window.$3Dmol.createViewer !== "function") {
    throw new Error("3Dmol viewer library is unavailable");
  }
  const container = document.getElementById("structure-viewer");
  state.viewer = window.$3Dmol.createViewer(container, {
    backgroundColor: "white",
  });
  return state.viewer;
}

async function renderSurfaceWithSeparatedLigand() {
  const viewer = await ensureViewer();
  const [proteinText, ligandText] = await Promise.all([
    fetchText(state.record.downloads.protein_pdb),
    fetchText(state.record.downloads.ligand_pdb),
  ]);

  viewer.clear();
  viewer.addModel(proteinText, "pdb");
  viewer.setStyle(
    { hetflag: false },
    { cartoon: { color: "spectrum", opacity: 0.9 } }
  );
  viewer.addSurface(
    window.$3Dmol.SurfaceType.VDW,
    { color: "#b7c9d6", opacity: 0.28 },
    { hetflag: false }
  );
  viewer.addModel(ligandText, "pdb");
  viewer.setStyle(
    { model: 1 },
    { stick: { radius: 0.22, colorscheme: "default" } }
  );
  viewer.zoomTo({ model: 1 });
  syncViewerSize(viewer);
  viewer.render();
  return true;
}

async function renderStructure(kind) {
  state.selectedKind = kind;
  updateViewerButtons(kind);
  const viewer = await ensureViewer();
  const downloads = state.record?.downloads || {};
  const urlByKind = {
    surface: downloads.complex_pdb,
    complex: downloads.complex_pdb,
    protein: downloads.protein_pdb,
    ligand: downloads.ligand_pdb,
  };
  const url = urlByKind[kind];
  if (!url) {
    setViewerStatus("Structure file is unavailable for this selection.", "warn");
    return;
  }
  setViewerStatus(
    kind === "complex" ? "Loading pocket complex from local structure assets..." : "Loading selected structure view...",
    "info"
  );
  try {
    if (kind === "surface") {
      const surfaceLoaded = await renderSurfaceWithSeparatedLigand();
      if (surfaceLoaded) {
        setViewerStatus("Default structure view loaded.", "info");
        return;
      }
    }

    const structureText = await fetchText(url);
    viewer.clear();
    viewer.addModel(structureText, "pdb");
    if (kind === "ligand") {
      viewer.setStyle({}, { stick: { radius: 0.22, colorscheme: "default" } });
      viewer.zoomTo();
    } else {
      viewer.setStyle(
        { hetflag: false },
        { cartoon: { color: "spectrum", opacity: 0.9 } }
      );
      viewer.setStyle(
        { hetflag: true },
        { stick: { radius: 0.2, colorscheme: "default" } }
      );
      viewer.zoomTo({ hetflag: true });
    }
    syncViewerSize(viewer);
    viewer.render();
    if (kind === "surface") {
      setViewerStatus("Pocket surface view loaded.", "info");
    } else if (kind === "complex") {
      setViewerStatus("Pocket complex view loaded.", "info");
    } else {
      setViewerStatus("");
    }
  } catch (error) {
    setViewerStatus(`3D structure load failed: ${error.message}`, "warn");
  }
}

async function bootstrap() {
  if (!state.pocketId) {
    throw new Error("Pocket id is missing from the URL");
  }

  elements.title.textContent = state.pocketId;
  setViewerStatus("Loading pocket detail...", "info");

  const [record, activity] = await Promise.all([
    fetchJson(`/api/pocket/${encodeURIComponent(state.pocketId)}`),
    fetchJson(`/api/activity/${encodeURIComponent(state.pocketId)}`),
  ]);

  state.record = record;
  state.activity = activity;

  elements.title.textContent = `${record.pocket_id} · ${record.pdb_id}`;
  elements.subtitle.textContent = `Ligand ${record.ligand?.resname || "-"} · Cluster ${record.cluster?.cluster_label ?? "-"} · Pocket-centric structure and activity detail`;

  renderMetadata(record);
  renderLigandProperties(record);
  renderAssetLinks(record);
  renderActivity(activity);
  await renderStructure("surface");
}

elements.viewerButtons.forEach((button) => {
  button.addEventListener("click", async () => {
    try {
      await renderStructure(button.dataset.kind);
    } catch (error) {
      setViewerStatus(`3D structure load failed: ${error.message}`, "warn");
    }
  });
});

window.addEventListener("resize", () => {
  if (state.viewer) {
    syncViewerSize(state.viewer);
    state.viewer.render();
  }
});

bootstrap().catch((error) => {
  console.error(error);
  elements.title.textContent = "Pocket detail unavailable";
  elements.subtitle.textContent = error.message;
  setViewerStatus(`Failed to initialize detail page: ${error.message}`, "warn");
});









