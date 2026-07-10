const mode = window.location.pathname === "/setup" ? "setup" : "login";

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
    credentials: "same-origin",
    headers: {
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(options.headers || {}),
    },
    ...options,
  });
  const text = await response.text();
  const payload = text ? JSON.parse(text) : {};
  if (!response.ok) {
    throw new Error(payload.detail || `HTTP ${response.status}`);
  }
  return payload;
}

function renderMode() {
  const isSetup = mode === "setup";
  document.title = isSetup ? "Create Web Account" : "Connie's Uploader Sign In";
  byId("auth-title").textContent = isSetup ? "Create web account" : "Sign in";
  byId("auth-submit").textContent = isSetup ? "Create account" : "Sign in";
  byId("auth-confirm-wrap").classList.toggle("is-hidden", !isSetup);
  byId("auth-password").autocomplete = isSetup ? "new-password" : "current-password";
  byId("auth-confirm-password").required = isSetup;
}

async function loadStatus() {
  const status = await apiJson("/api/auth/status");
  if (mode === "setup" && !status.setup_required) {
    window.location.replace(status.authenticated ? "/" : "/login");
    return;
  }
  if (mode === "login" && status.setup_required) {
    window.location.replace("/setup");
    return;
  }
  if (mode === "login" && status.authenticated) {
    window.location.replace("/");
  }
}

async function submitAuth(event) {
  event.preventDefault();
  const username = byId("auth-username").value.trim();
  const password = byId("auth-password").value;
  const confirmPassword = byId("auth-confirm-password").value;
  if (mode === "setup" && password !== confirmPassword) {
    setMessage("Passwords do not match.", "error");
    return;
  }
  await apiJson(mode === "setup" ? "/api/auth/setup" : "/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
  window.location.replace("/");
}

renderMode();
byId("auth-form").addEventListener("submit", (event) => submitAuth(event).catch((error) => {
  setMessage(error.message || String(error), "error");
}));
loadStatus().catch((error) => setMessage(error.message || String(error), "error"));
