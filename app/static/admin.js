"use strict";

function showMessage(el, text, ok) {
  el.textContent = text;
  el.className = "message " + (ok ? "ok" : "err");
}

async function loadSettings() {
  const res = await fetch("/admin/settings");
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
    const res = await fetch("/admin/settings", {
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
    const res = await fetch("/admin/test-email", {
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

async function loadFaces() {
  const res = await fetch("/status");
  const data = await res.json();
  const list = document.getElementById("faces-list");
  list.innerHTML = "";
  (data.enrolled || []).forEach((f) => {
    const li = document.createElement("li");
    const span = document.createElement("span");
    span.textContent = `${f.name} (added ${f.created_at})`;
    const btn = document.createElement("button");
    btn.textContent = "Delete";
    btn.addEventListener("click", async () => {
      await fetch(`/admin/faces/${f.id}`, { method: "DELETE" });
      loadFaces();
    });
    li.appendChild(span);
    li.appendChild(btn);
    list.appendChild(li);
  });
  if (!data.enrolled || data.enrolled.length === 0) {
    list.innerHTML = "<li><span>No faces enrolled yet.</span></li>";
  }
}

loadSettings();
loadFaces();
