"use strict";

// Session token lives only in memory, so reloading or revisiting /admin always
// requires a fresh login.
let token = null;

function showMessage(el, text, ok) {
  el.textContent = text;
  el.className = "message " + (ok ? "ok" : "err");
}

// fetch wrapper that attaches the bearer token and drops back to the login
// screen on any 401.
async function authedFetch(url, options = {}) {
  const opts = { ...options, headers: { ...(options.headers || {}) } };
  if (token) opts.headers["Authorization"] = "Bearer " + token;
  const res = await fetch(url, opts);
  if (res.status === 401) {
    token = null;
    showLogin();
    throw new Error("Session expired. Please sign in again.");
  }
  return res;
}

// ---- login / logout -------------------------------------------------
function showLogin() {
  document.getElementById("login-overlay").hidden = false;
  document.getElementById("admin-content").hidden = true;
  document.getElementById("logout").hidden = true;
  document.getElementById("login-password").value = "";
}

function showAdmin() {
  document.getElementById("login-overlay").hidden = true;
  document.getElementById("admin-content").hidden = false;
  document.getElementById("logout").hidden = false;
  loadSettings();
  loadFaces();
  loadCaptures();
}

document.getElementById("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const msg = document.getElementById("login-message");
  const username = document.getElementById("login-username").value.trim();
  const password = document.getElementById("login-password").value;
  try {
    const res = await fetch("/admin/login", {
      method: "POST",
      body: new URLSearchParams({ username, password }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || "Sign in failed");
    token = data.token;
    showMessage(msg, "", true);
    showAdmin();
  } catch (err) {
    showMessage(msg, err.message, false);
  }
});

document.getElementById("logout").addEventListener("click", async () => {
  try {
    await authedFetch("/admin/logout", { method: "POST" });
  } catch (_) {
    /* ignore */
  }
  token = null;
  showLogin();
});

// ---- settings -------------------------------------------------------
async function loadSettings() {
  const res = await authedFetch("/admin/settings");
  if (!res.ok) return;
  const s = await res.json();
  const form = document.getElementById("settings-form");
  Object.entries(s).forEach(([key, value]) => {
    const field = form.elements[key];
    if (!field) return;
    if (field.type === "checkbox") field.checked = Boolean(value);
    else field.value = value;
  });
}

document.getElementById("settings-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  const payload = {};
  Array.from(form.elements).forEach((el) => {
    if (!el.name) return;
    if (el.type === "checkbox") payload[el.name] = el.checked;
    else if (el.type === "number") payload[el.name] = el.value === "" ? "" : Number(el.value);
    else payload[el.name] = el.value;
  });
  // Don't push the masked password back if untouched.
  if (payload.smtp_password === "********") delete payload.smtp_password;

  const msg = document.getElementById("settings-message");
  try {
    const res = await authedFetch("/admin/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Save failed");
    showMessage(msg, "Settings saved.", true);
    loadSettings();
  } catch (err) {
    showMessage(msg, err.message, false);
  }
});

document.getElementById("test-email-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const msg = document.getElementById("test-message");
  const recipient = document.getElementById("test-recipient").value.trim();
  try {
    const res = await authedFetch("/admin/test-email", {
      method: "POST",
      body: new URLSearchParams({ recipient }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Failed");
    showMessage(msg, data.message, true);
  } catch (err) {
    showMessage(msg, err.message, false);
  }
});

// ---- enrolled faces -------------------------------------------------
async function loadFaces() {
  const res = await authedFetch("/admin/faces");
  if (!res.ok) return;
  const faces = await res.json();
  const list = document.getElementById("faces-list");
  list.innerHTML = "";
  faces.forEach((f) => {
    const li = document.createElement("li");

    const info = document.createElement("div");
    info.className = "face-info";

    const avatar = document.createElement("div");
    avatar.className = "face-avatar";
    if (f.image) {
      const img = document.createElement("img");
      img.src = `/faces/image/${f.image}?token=${encodeURIComponent(token)}`;
      img.alt = f.name;
      avatar.appendChild(img);
    } else {
      avatar.textContent = (f.name || "?").charAt(0).toUpperCase();
      avatar.classList.add("placeholder");
    }
    info.appendChild(avatar);

    const span = document.createElement("span");
    span.textContent = `${f.name} (added ${f.created_at})`;
    info.appendChild(span);

    const btn = document.createElement("button");
    btn.textContent = "Delete";
    btn.addEventListener("click", async () => {
      if (!confirm(`Delete enrolled face "${f.name}"?`)) return;
      await authedFetch(`/admin/faces/${f.id}`, { method: "DELETE" });
      loadFaces();
    });

    li.appendChild(info);
    li.appendChild(btn);
    list.appendChild(li);
  });
  if (faces.length === 0) {
    list.innerHTML = "<li><span>No faces enrolled yet.</span></li>";
  }
}

// ---- captured faces -------------------------------------------------
const capSelected = new Set();
const CAP_PAGE = 60;
let capOffset = 0;

function renderCapture(c, gallery) {
  const div = document.createElement("div");
  div.className = "thumb" + (capSelected.has(c.id) ? " selected" : "");
  div.dataset.id = c.id;

  const img = document.createElement("img");
  img.src = `/captures/${c.filename}?token=${encodeURIComponent(token)}`;
  img.alt = c.label || "face";
  div.appendChild(img);

  const labels = document.createElement("div");
  labels.className = "labels";
  labels.textContent = `${c.label || "Unknown"} - ${c.created_at}`;
  div.appendChild(labels);

  const del = document.createElement("button");
  del.className = "del";
  del.textContent = "\u00d7";
  del.title = "Delete";
  del.addEventListener("click", async (ev) => {
    ev.stopPropagation();
    if (!confirm("Delete this capture?")) return;
    await authedFetch(`/admin/captures/${c.id}`, { method: "DELETE" });
    capSelected.delete(c.id);
    loadCaptures();
  });
  div.appendChild(del);

  div.addEventListener("click", () => {
    if (capSelected.has(c.id)) capSelected.delete(c.id);
    else capSelected.add(c.id);
    div.classList.toggle("selected");
  });

  gallery.appendChild(div);
}

async function loadCaptures(reset = true) {
  const gallery = document.getElementById("captures");
  const more = document.getElementById("cap-load-more");
  if (reset) {
    capOffset = 0;
    gallery.innerHTML = "";
  }
  const res = await authedFetch(`/admin/captures?limit=${CAP_PAGE}&offset=${capOffset}`);
  if (!res.ok) return;
  const captures = await res.json();
  if (reset && captures.length === 0) {
    gallery.innerHTML = '<p class="hint">No captures yet.</p>';
    more.hidden = true;
    return;
  }
  captures.forEach((c) => renderCapture(c, gallery));
  capOffset += captures.length;
  more.hidden = captures.length < CAP_PAGE;
}

document.getElementById("refresh-captures").addEventListener("click", () => loadCaptures());
document.getElementById("cap-load-more").addEventListener("click", () => loadCaptures(false));

document.getElementById("cap-select-all").addEventListener("click", () => {
  document.querySelectorAll("#captures .thumb").forEach((t) => {
    capSelected.add(Number(t.dataset.id));
    t.classList.add("selected");
  });
});

document.getElementById("cap-clear-sel").addEventListener("click", () => {
  capSelected.clear();
  document.querySelectorAll("#captures .thumb").forEach((t) => t.classList.remove("selected"));
});

document.getElementById("cap-download").addEventListener("click", async () => {
  const msg = document.getElementById("captures-message");
  if (capSelected.size === 0) {
    showMessage(msg, "Select at least one capture to download.", false);
    return;
  }
  try {
    const res = await authedFetch("/admin/captures/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids: Array.from(capSelected) }),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || "Download failed");
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "captures.zip";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    showMessage(msg, `Downloaded ${capSelected.size} capture(s).`, true);
  } catch (err) {
    showMessage(msg, err.message, false);
  }
});

document.getElementById("cap-delete").addEventListener("click", async () => {
  const msg = document.getElementById("captures-message");
  if (capSelected.size === 0) {
    showMessage(msg, "Select at least one capture to delete.", false);
    return;
  }
  const ids = Array.from(capSelected);
  if (!confirm(`Delete ${ids.length} selected capture(s)?`)) return;
  try {
    await Promise.all(
      ids.map((id) => authedFetch(`/admin/captures/${id}`, { method: "DELETE" }))
    );
    capSelected.clear();
    showMessage(msg, `Deleted ${ids.length} capture(s).`, true);
    loadCaptures();
  } catch (err) {
    showMessage(msg, err.message, false);
  }
});

showLogin();
