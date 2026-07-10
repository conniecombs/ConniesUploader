const SERVICE_ALIASES = {
  "imx.to": {
    thumbnail_size: "imx_thumb",
    thumbnail_format: "imx_format",
    cover_count: "imx_cover_count",
    save_links: "imx_links",
    gallery_id: "imx_gallery_id",
  },
  "pixhost.to": {
    content_type: "pix_content",
    thumbnail_size: "pix_thumb",
    cover_count: "pix_cover_count",
    save_links: "pix_links",
    gallery_hash: "pix_gallery_hash",
  },
  turboimagehost: {
    thumbnail_size: "turbo_thumb",
    cover_count: "turbo_cover_count",
    save_links: "turbo_links",
    gallery_id: "turbo_gallery_id",
  },
  "vipr.im": {
    thumbnail_size: "vipr_thumb",
    cover_count: "vipr_cover_count",
    save_links: "vipr_links",
  },
  "imagebam.com": {
    content_type: "imagebam_content",
    thumbnail_size: "imagebam_thumb",
    cover_count: "imagebam_cover_count",
  },
  "imgur.com": {
    content_type: "imgur_content",
    thumbnail_size: "imgur_thumb",
    save_links: "imgur_links",
    album_id: "imgur_album_id",
    title: "imgur_title",
  },
};

const CREDENTIAL_SERVICE_LABELS = {
  "imx.to": ["imx.to"],
  "pixhost.to": [],
  turboimagehost: ["Turbo"],
  "vipr.im": ["Vipr"],
  "imagebam.com": ["ImageBam"],
  "imgur.com": ["Imgur"],
};

const EVENT_TYPES = [
  "snapshot",
  "status",
  "prog",
  "result",
  "output",
  "output_error",
  "gallery_url",
  "register_pix_gal",
];

const state = {
  health: null,
  services: [],
  settings: {},
  credentials: null,
  queue: [],
  inputPath: "",
  currentUpload: null,
  eventSource: null,
  pollTimer: null,
  serviceOptionValues: {},
};

function byId(id) {
  return document.getElementById(id);
}

function setMessage(text, type = "") {
  const line = byId("message-line");
  line.textContent = text || "";
  line.className = "message-line";
  if (text) {
    line.classList.add("is-visible");
  }
  if (type) {
    line.classList.add(`is-${type}`);
  }
}

async function apiJson(url, options = {}) {
  const response = await fetch(url, {
    cache: "no-store",
    headers: {
      ...(options.body && !(options.body instanceof FormData)
        ? { "Content-Type": "application/json" }
        : {}),
      ...(options.headers || {}),
    },
    ...options,
  });
  const text = await response.text();
  let payload = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch (_error) {
      payload = { detail: text };
    }
  }
  if (!response.ok) {
    const detail = payload?.detail || `HTTP ${response.status}`;
    throw new Error(Array.isArray(detail) ? detail.map((item) => item.msg).join("; ") : detail);
  }
  return payload || {};
}

function formatSize(value) {
  if (value === null || value === undefined) {
    return "";
  }
  const units = ["B", "KB", "MB", "GB"];
  let size = Number(value);
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${size.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function basename(path) {
  return String(path || "").split(/[\\/]/).filter(Boolean).pop() || String(path || "");
}

function normalizeValues(values) {
  if (Array.isArray(values)) {
    return values.map((value) => String(value));
  }
  if (typeof values === "string") {
    return values.split(/\s+/).filter(Boolean);
  }
  return [];
}

function currentServiceId() {
  return byId("service-select").value || state.settings.service || "";
}

function currentService() {
  const serviceId = currentServiceId();
  return state.services.find((service) => service.id === serviceId) || null;
}

function flattenSchema(schema) {
  const fields = [];
  for (const item of schema || []) {
    if (item.type === "separator" || item.type === "label") {
      continue;
    }
    if (item.type === "inline_group") {
      for (const nested of item.fields || []) {
        if (nested.type !== "label") {
          fields.push(nested);
        }
      }
      continue;
    }
    fields.push(item);
  }
  return fields.filter((field) => field.key);
}

function optionStore(serviceId) {
  if (!state.serviceOptionValues[serviceId]) {
    state.serviceOptionValues[serviceId] = {};
  }
  return state.serviceOptionValues[serviceId];
}

function settingValue(serviceId, field) {
  const store = optionStore(serviceId);
  if (Object.prototype.hasOwnProperty.call(store, field.key)) {
    return store[field.key];
  }
  const alias = SERVICE_ALIASES[serviceId]?.[field.key];
  if (alias && Object.prototype.hasOwnProperty.call(state.settings, alias)) {
    return state.settings[alias];
  }
  if (Object.prototype.hasOwnProperty.call(state.settings, field.key)) {
    return state.settings[field.key];
  }
  return field.default ?? "";
}

function coerceFieldValue(field, value) {
  if (field.type === "checkbox") {
    return Boolean(value);
  }
  if (field.key === "cover_count") {
    return Number.parseInt(value || "0", 10) || 0;
  }
  return String(value ?? "");
}

function renderRuntime() {
  byId("status-value").textContent = state.health?.status || "offline";
  byId("mode-value").textContent = state.health?.mode || "-";
  byId("input-value").textContent = state.health?.paths?.input || "-";
  byId("output-value").textContent = state.health?.paths?.output || "-";
}

function renderServices() {
  const select = byId("service-select");
  const previous = select.value || state.settings.service;
  select.replaceChildren();
  for (const service of state.services) {
    const option = document.createElement("option");
    option.value = service.id;
    option.textContent = service.name || service.id;
    select.append(option);
  }
  const fallback = state.services[0]?.id || "";
  select.value = state.services.some((service) => service.id === previous) ? previous : fallback;
  byId("worker-count").value = state.settings.global_worker_count ?? 8;
  byId("thread-limit").value = state.settings.global_thread_limit ?? 5;
  byId("template-select").value = state.settings.output_format || "BBCode";
  renderServiceOptions();
  renderCredentials();
}

function renderServiceOptions() {
  const container = byId("service-options");
  const service = currentService();
  container.replaceChildren();
  if (!service) {
    container.append(emptyState("No services loaded."));
    return;
  }
  const fields = flattenSchema(service.settings_schema);
  if (!fields.length) {
    container.append(emptyState("No service options."));
    return;
  }
  for (const field of fields) {
    const label = document.createElement("label");
    label.textContent = field.label || field.key;
    let control;
    const currentValue = settingValue(service.id, field);
    if (field.type === "dropdown") {
      control = document.createElement("select");
      const values = normalizeValues(field.values);
      for (const value of values) {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = field.value_labels?.[value] || value;
        control.append(option);
      }
      control.value = String(currentValue);
      if (control.value !== String(currentValue) && values.length) {
        control.value = values[0];
      }
    } else if (field.type === "checkbox") {
      control = document.createElement("input");
      control.type = "checkbox";
      control.checked = Boolean(currentValue);
      label.classList.add("checkbox-label");
    } else {
      control = document.createElement("input");
      control.type = "text";
      control.value = String(currentValue ?? "");
      if (field.placeholder) {
        control.placeholder = field.placeholder;
      }
    }
    control.dataset.settingKey = field.key;
    control.addEventListener("change", () => {
      optionStore(service.id)[field.key] =
        field.type === "checkbox" ? control.checked : control.value;
    });
    label.append(control);
    container.append(label);
  }
}

function renderCredentials() {
  const container = byId("credential-fields");
  container.replaceChildren();
  const serviceId = currentServiceId();
  const allowedLabels = CREDENTIAL_SERVICE_LABELS[serviceId] || [];
  const fields = (state.credentials?.fields || []).filter((field) =>
    allowedLabels.includes(field.service),
  );
  if (!fields.length) {
    container.append(emptyState("No credentials required."));
    return;
  }
  for (const field of fields) {
    const row = document.createElement("div");
    row.className = "field-row";

    const label = document.createElement("label");
    label.htmlFor = `cred-${field.key}`;
    label.textContent = field.label || field.key;

    const wrap = document.createElement("div");
    const input = document.createElement("input");
    input.id = `cred-${field.key}`;
    input.dataset.credentialKey = field.key;
    input.type = field.secret ? "password" : "text";
    input.placeholder = field.present ? "Saved" : "";
    input.autocomplete = "off";
    const note = document.createElement("div");
    note.className = "status-note";
    note.textContent = field.present ? "Stored" : "Empty";

    wrap.append(input, note);
    row.append(label, wrap);
    container.append(row);
  }
}

function emptyState(text) {
  const node = document.createElement("div");
  node.className = "empty-state";
  node.textContent = text;
  return node;
}

async function loadHealth() {
  state.health = await apiJson("/api/health");
  renderRuntime();
}

async function loadServicesAndSettings() {
  const [services, settings, credentials] = await Promise.all([
    apiJson("/api/services"),
    apiJson("/api/settings"),
    apiJson("/api/credentials/status"),
  ]);
  state.services = services.services || [];
  state.settings = settings.settings || {};
  state.credentials = credentials;
  renderServices();
}

async function loadInputFiles(path = state.inputPath) {
  const payload = await apiJson(`/api/files/input?path=${encodeURIComponent(path || "")}`);
  state.inputPath = path || "";
  byId("input-path-label").textContent = payload.path || payload.root || "/input";
  renderInputFiles(payload.entries || []);
}

function renderInputFiles(entries) {
  const list = byId("input-file-list");
  list.replaceChildren();
  if (!entries.length) {
    list.append(emptyState("No mounted input files."));
    return;
  }
  for (const entry of entries) {
    const row = document.createElement("div");
    row.className = "file-row";
    const main = document.createElement("div");
    main.className = "row-main";
    const title = document.createElement("span");
    title.className = "row-title";
    title.textContent = entry.name;
    const meta = document.createElement("span");
    meta.className = "row-meta";
    meta.textContent = entry.is_dir ? "Folder" : `${formatSize(entry.size)} - mounted`;
    main.append(title, meta);
    const button = document.createElement("button");
    button.className = "secondary-button";
    button.type = "button";
    button.textContent = entry.is_dir ? "Open" : "Add";
    button.addEventListener("click", () => {
      if (entry.is_dir) {
        loadInputFiles(entry.relative_path).catch(showError);
      } else {
        addQueueFile({
          name: entry.name,
          path: entry.path,
          size: entry.size,
          source: "mounted",
        });
      }
    });
    row.append(main, button);
    list.append(row);
  }
}

function parentInputPath(path) {
  const parts = String(path || "")
    .split(/[\\/]/)
    .filter(Boolean);
  parts.pop();
  return parts.join("/");
}

function addQueueFile(file) {
  if (state.queue.some((item) => item.path === file.path)) {
    setMessage(`${file.name} is already queued.`);
    return;
  }
  state.queue.push({ ...file, cover: false });
  renderQueue();
  setMessage(`${file.name} queued.`, "success");
}

function renderQueue() {
  const list = byId("queue-list");
  list.replaceChildren();
  if (!state.queue.length) {
    list.append(emptyState("No files queued."));
    return;
  }
  state.queue.forEach((file, index) => {
    const row = document.createElement("div");
    row.className = "queue-row";
    const main = document.createElement("div");
    main.className = "row-main";
    const title = document.createElement("span");
    title.className = "row-title";
    title.textContent = file.name || basename(file.path);
    const meta = document.createElement("span");
    meta.className = "row-meta";
    meta.textContent = `${file.source} - ${formatSize(file.size)} - ${file.path}`;
    main.append(title, meta);

    const cover = document.createElement("label");
    cover.className = "cover-toggle";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = file.cover;
    checkbox.addEventListener("change", () => {
      state.queue[index].cover = checkbox.checked;
    });
    cover.append(checkbox, document.createTextNode("Cover"));

    const remove = document.createElement("button");
    remove.className = "ghost-button";
    remove.type = "button";
    remove.textContent = "Remove";
    remove.addEventListener("click", () => {
      state.queue.splice(index, 1);
      renderQueue();
    });

    row.append(main, cover, remove);
    list.append(row);
  });
}

function collectSettings() {
  const service = currentService();
  const serviceId = service?.id || currentServiceId();
  const settings = {
    service: serviceId,
    global_worker_count: Number.parseInt(byId("worker-count").value || "8", 10),
    global_thread_limit: Number.parseInt(byId("thread-limit").value || "5", 10),
    output_format: byId("template-select").value || "BBCode",
  };
  for (const field of flattenSchema(service?.settings_schema || [])) {
    const control = document.querySelector(`[data-setting-key="${field.key}"]`);
    if (!control) {
      continue;
    }
    const value = coerceFieldValue(
      field,
      field.type === "checkbox" ? control.checked : control.value,
    );
    settings[field.key] = value;
    const alias = SERVICE_ALIASES[serviceId]?.[field.key];
    if (alias) {
      settings[alias] = value;
    }
  }
  const galleryId = byId("gallery-id").value.trim();
  if (galleryId) {
    settings.gallery_id = galleryId;
    if (serviceId === "imx.to") {
      settings.imx_gallery_id = galleryId;
    } else if (serviceId === "pixhost.to") {
      settings.gallery_hash = galleryId;
      settings.pix_gallery_hash = galleryId;
    } else if (serviceId === "turboimagehost") {
      settings.turbo_gallery_id = galleryId;
    } else if (serviceId === "imgur.com") {
      settings.album_id = galleryId;
      settings.imgur_album_id = galleryId;
    }
  }
  return settings;
}

async function saveSettings() {
  const payload = await apiJson("/api/settings", {
    method: "PUT",
    body: JSON.stringify({ settings: collectSettings() }),
  });
  state.settings = payload.settings || state.settings;
  renderServices();
  setMessage("Settings saved.", "success");
}

async function saveCredentials() {
  const credentials = {};
  for (const input of document.querySelectorAll("[data-credential-key]")) {
    if (input.value.trim()) {
      credentials[input.dataset.credentialKey] = input.value.trim();
    }
  }
  if (!Object.keys(credentials).length) {
    setMessage("No credential changes.");
    return;
  }
  state.credentials = await apiJson("/api/credentials", {
    method: "PUT",
    body: JSON.stringify({ credentials }),
  });
  renderCredentials();
  setMessage("Credentials saved.", "success");
}

async function stageBrowserUploads() {
  const input = byId("browser-file-input");
  if (!input.files.length) {
    setMessage("No browser files selected.");
    return;
  }
  const form = new FormData();
  for (const file of input.files) {
    form.append("files", file);
  }
  const payload = await apiJson("/api/files/upload", {
    method: "POST",
    body: form,
  });
  for (const file of payload.files || []) {
    addQueueFile({
      name: file.name,
      path: file.path,
      size: file.size,
      source: "uploaded",
    });
  }
  input.value = "";
}

function galleryPayload(settings) {
  const id = byId("gallery-id").value.trim();
  if (!id) {
    return null;
  }
  return {
    id,
    name: id,
    service: settings.service,
  };
}

async function startUpload() {
  if (!state.queue.length) {
    setMessage("Queue at least one file before starting.", "error");
    return;
  }
  await saveSettings();
  const settings = collectSettings();
  const title = byId("batch-title").value.trim() || "Web Batch";
  const group = {
    title,
    files: state.queue.map((file) => file.path),
    cover_files: state.queue.filter((file) => file.cover).map((file) => file.path),
    selected_template: byId("template-select").value || "BBCode",
    selected_thread: "Do Not Post",
    source: "web",
    gallery: galleryPayload(settings),
  };
  const payload = await apiJson("/api/uploads", {
    method: "POST",
    body: JSON.stringify({ settings, groups: [group] }),
  });
  applyUpload(payload.upload);
  openEventSource(payload.upload.id);
  setMessage("Upload started.", "success");
}

function openEventSource(uploadId) {
  if (state.eventSource) {
    state.eventSource.close();
  }
  if (state.pollTimer) {
    window.clearInterval(state.pollTimer);
    state.pollTimer = null;
  }
  if (typeof EventSource === "undefined") {
    startUploadPolling(uploadId);
    return;
  }
  const source = new EventSource(`/api/uploads/${encodeURIComponent(uploadId)}/events`);
  state.eventSource = source;
  for (const type of EVENT_TYPES) {
    source.addEventListener(type, (event) => {
      const payload = JSON.parse(event.data);
      if (type === "snapshot") {
        applyUpload(payload);
      } else {
        appendEvent(type, payload.file_path, payload.value);
        refreshCurrentUpload().catch(showError);
      }
    });
  }
  source.onerror = () => {
    if (state.currentUpload && isTerminal(state.currentUpload.state)) {
      source.close();
      state.eventSource = null;
    }
  };
}

function startUploadPolling(uploadId) {
  appendEvent("status", null, "Progress stream unavailable; polling status.");
  state.pollTimer = window.setInterval(() => {
    apiJson(`/api/uploads/${encodeURIComponent(uploadId)}`)
      .then((payload) => applyUpload(payload.upload))
      .catch((error) => {
        window.clearInterval(state.pollTimer);
        state.pollTimer = null;
        showError(error);
      });
  }, 1000);
}

async function refreshCurrentUpload() {
  if (!state.currentUpload?.id) {
    return;
  }
  const payload = await apiJson(`/api/uploads/${encodeURIComponent(state.currentUpload.id)}`);
  applyUpload(payload.upload);
}

async function cancelUpload() {
  if (!state.currentUpload?.id) {
    return;
  }
  const payload = await apiJson(
    `/api/uploads/${encodeURIComponent(state.currentUpload.id)}/cancel`,
    { method: "POST" },
  );
  applyUpload(payload.upload);
  setMessage("Upload cancelled.");
}

function isTerminal(uploadState) {
  return ["complete", "cancelled", "failed"].includes(uploadState);
}

function applyUpload(upload) {
  if (!upload) {
    return;
  }
  state.currentUpload = upload;
  renderUpload();
  if (isTerminal(upload.state)) {
    if (state.eventSource) {
      state.eventSource.close();
      state.eventSource = null;
    }
    if (state.pollTimer) {
      window.clearInterval(state.pollTimer);
      state.pollTimer = null;
    }
    loadHistory().catch(showError);
  }
}

function renderUpload() {
  const upload = state.currentUpload;
  const statePill = byId("upload-state");
  const uploadState = upload?.state || "idle";
  statePill.textContent = uploadState;
  statePill.className = `state-pill ${uploadState}`;
  const completed = upload?.completed_files || 0;
  const failed = upload?.failed_files || 0;
  const total = upload?.total_files || 0;
  const percent = total ? Math.round((completed / total) * 100) : 0;
  byId("progress-bar").style.width = `${percent}%`;
  byId("progress-count").textContent = failed
    ? `${completed} / ${total} (${failed} failed)`
    : `${completed} / ${total}`;
  byId("session-id").textContent = upload?.id || "-";
  byId("cancel-upload-button").disabled = !upload || isTerminal(upload.state);
  byId("start-upload-button").disabled = upload?.state === "running";
  renderResults(upload);
}

function appendEvent(kind, filePath, value) {
  const log = byId("event-log");
  if (log.firstElementChild?.classList.contains("empty-state")) {
    log.replaceChildren();
  }
  const row = document.createElement("div");
  row.className = "event-row";
  const type = document.createElement("span");
  type.className = "event-type";
  type.textContent = kind.replace("_", " ");
  const text = document.createElement("span");
  const fileName = filePath ? basename(filePath) : "";
  if (typeof value === "string") {
    text.textContent = fileName ? `${fileName}: ${value}` : value;
  } else if (value?.viewer_url) {
    text.textContent = `${basename(value.file_path)} uploaded`;
  } else if (value?.output_name) {
    text.textContent = `Generated ${value.output_name}`;
  } else {
    text.textContent = fileName || "Updated";
  }
  row.append(type, text);
  log.prepend(row);
  while (log.children.length > 80) {
    log.lastElementChild.remove();
  }
}

function renderResults(upload) {
  const linkList = byId("result-links");
  linkList.replaceChildren();
  const results = upload?.results || [];
  const outputs = upload?.output_files || [];
  if (!results.length && !outputs.length) {
    linkList.append(emptyState("No results yet."));
    byId("generated-output").value = "";
    return;
  }
  for (const output of outputs) {
    const row = document.createElement("div");
    row.className = "result-row";
    const main = document.createElement("div");
    main.className = "row-main";
    const title = document.createElement("span");
    title.className = "row-title";
    title.textContent = output.group_title || output.output_name;
    const meta = document.createElement("span");
    meta.className = "row-meta";
    meta.textContent = output.output_file;
    main.append(title, meta);
    const link = document.createElement("a");
    link.href = `/api/output/${encodeURIComponent(output.output_name)}`;
    link.textContent = "Download";
    row.append(main, link);
    linkList.append(row);
  }
  for (const result of results) {
    const row = document.createElement("div");
    row.className = "result-row";
    const main = document.createElement("div");
    main.className = "row-main";
    const title = document.createElement("span");
    title.className = "row-title";
    title.textContent = basename(result.file_path);
    const meta = document.createElement("span");
    meta.className = "row-meta";
    meta.textContent = result.success === false
      ? result.error || "Upload failed"
      : result.viewer_url || "No viewer URL";
    main.append(title, meta);
    if (result.success === false) {
      const status = document.createElement("span");
      status.className = "result-status failed";
      status.textContent = "Failed";
      row.append(main, status);
    } else {
      const link = document.createElement("a");
      link.href = result.viewer_url || "#";
      link.target = "_blank";
      link.rel = "noreferrer";
      link.textContent = "Open";
      row.append(main, link);
    }
    linkList.append(row);
  }
  byId("generated-output").value = outputs.map((output) => output.text || "").join("\n\n");
}

async function loadHistory() {
  const payload = await apiJson("/api/history");
  const list = byId("history-list");
  list.replaceChildren();
  const entries = payload.entries || [];
  if (!entries.length) {
    list.append(emptyState("No generated history."));
    return;
  }
  for (const entry of entries.slice(0, 8)) {
    const row = document.createElement("div");
    row.className = "history-row";
    const main = document.createElement("div");
    main.className = "row-main";
    const title = document.createElement("span");
    title.className = "row-title";
    title.textContent = entry.name;
    const meta = document.createElement("span");
    meta.className = "row-meta";
    meta.textContent = `${formatSize(entry.size)} - ${entry.modified}`;
    main.append(title, meta);
    row.append(main);
    list.append(row);
  }
}

async function copyOutput() {
  const text = byId("generated-output").value;
  if (!text.trim()) {
    setMessage("No generated output to copy.");
    return;
  }
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
  } else {
    byId("generated-output").select();
    document.execCommand("copy");
  }
  setMessage("Generated output copied.", "success");
}

function clearQueue() {
  state.queue = [];
  renderQueue();
}

function showError(error) {
  setMessage(error.message || String(error), "error");
}

function bindEvents() {
  byId("service-select").addEventListener("change", () => {
    renderServiceOptions();
    renderCredentials();
  });
  byId("save-settings-button").addEventListener("click", () => saveSettings().catch(showError));
  byId("save-credentials-button").addEventListener("click", () => saveCredentials().catch(showError));
  byId("refresh-files-button").addEventListener("click", () => loadInputFiles().catch(showError));
  byId("up-directory-button").addEventListener("click", () =>
    loadInputFiles(parentInputPath(state.inputPath)).catch(showError),
  );
  byId("stage-upload-button").addEventListener("click", () =>
    stageBrowserUploads().catch(showError),
  );
  byId("clear-queue-button").addEventListener("click", clearQueue);
  byId("start-upload-button").addEventListener("click", () => startUpload().catch(showError));
  byId("cancel-upload-button").addEventListener("click", () => cancelUpload().catch(showError));
  byId("copy-output-button").addEventListener("click", () => copyOutput().catch(showError));
  byId("refresh-history-button").addEventListener("click", () => loadHistory().catch(showError));
}

async function init() {
  bindEvents();
  renderQueue();
  byId("event-log").append(emptyState("No events yet."));
  byId("history-list").append(emptyState("No generated history."));
  await Promise.all([loadHealth(), loadServicesAndSettings()]);
  await Promise.all([loadInputFiles(), loadHistory()]);
  setMessage("Ready.", "success");
}

init().catch(showError);
