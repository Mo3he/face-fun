"use strict";

const selected = new Set();
const GALLERY_PAGE = 60;
let galleryOffset = 0;

function showMessage(el, text, ok) {
  el.textContent = text;
  el.className = "message " + (ok ? "ok" : "err");
}

async function postForm(url, data) {
  const body = new URLSearchParams(data);
  const res = await fetch(url, { method: "POST", body });
  const payload = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(payload.detail || "Request failed");
  }
  return payload;
}

// ---- status polling -------------------------------------------------
async function pollStatus() {
  try {
    const res = await fetch("/status");
    const data = await res.json();
    const dot = document.getElementById("conn-dot");
    const text = document.getElementById("conn-text");
    if (data.connected) {
      dot.className = "dot ok";
      text.textContent = "Camera connected";
    } else {
      dot.className = "dot bad";
      text.textContent = data.error || "Camera offline";
    }
    const labels = data.labels && data.labels.length
      ? data.labels.join(", ")
      : "nobody yet";
    document.getElementById("labels").textContent = labels;
  } catch (e) {
    document.getElementById("conn-text").textContent = "Cannot reach server";
  }
}

// ---- enrollment -----------------------------------------------------
document.getElementById("enroll-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const name = document.getElementById("enroll-name").value.trim();
  const msg = document.getElementById("message");
  if (!name) {
    showMessage(msg, "Please type your name first.", false);
    return;
  }
  try {
    const r = await postForm("/enroll", { name });
    showMessage(msg, r.message, true);
    document.getElementById("enroll-name").value = "";
  } catch (err) {
    showMessage(msg, err.message, false);
  }
});

// ---- photos ---------------------------------------------------------
document.getElementById("snap").addEventListener("click", async () => {
  const msg = document.getElementById("message");
  try {
    await fetch("/photo", { method: "POST" }).then((r) => {
      if (!r.ok) throw new Error("Could not take photo");
    });
    showMessage(msg, "Photo captured.", true);
    loadGallery();
  } catch (err) {
    showMessage(msg, err.message, false);
  }
});

async function loadGallery(reset = true) {
  const gallery = document.getElementById("gallery");
  const more = document.getElementById("load-more");
  if (reset) {
    galleryOffset = 0;
    gallery.innerHTML = "";
  }
  const res = await fetch(`/photos?limit=${GALLERY_PAGE}&offset=${galleryOffset}`);
  const photos = await res.json();
  photos.forEach((p) => {
    const div = document.createElement("div");
    div.className = "thumb" + (selected.has(p.id) ? " selected" : "");
    div.dataset.id = p.id;

    const img = document.createElement("img");
    img.src = `/photos/${p.filename}`;
    img.alt = p.labels || "photo";
    div.appendChild(img);

    if (p.labels) {
      const labels = document.createElement("div");
      labels.className = "labels";
      labels.textContent = p.labels;
      div.appendChild(labels);
    }

    const del = document.createElement("button");
    del.className = "del";
    del.textContent = "\u00d7";
    del.title = "Delete";
    del.addEventListener("click", async (ev) => {
      ev.stopPropagation();
      if (!confirm("Delete this photo?")) return;
      await fetch(`/photos/${p.id}`, { method: "DELETE" });
      selected.delete(p.id);
      loadGallery();
    });
    div.appendChild(del);

    div.addEventListener("click", () => {
      if (selected.has(p.id)) selected.delete(p.id);
      else selected.add(p.id);
      div.classList.toggle("selected");
    });

    gallery.appendChild(div);
  });
  galleryOffset += photos.length;
  if (more) more.hidden = photos.length < GALLERY_PAGE;
}

document.getElementById("load-more").addEventListener("click", () => loadGallery(false));

document.getElementById("select-all").addEventListener("click", () => {
  document.querySelectorAll(".thumb").forEach((t) => {
    selected.add(Number(t.dataset.id));
    t.classList.add("selected");
  });
});

document.getElementById("clear-sel").addEventListener("click", () => {
  selected.clear();
  document.querySelectorAll(".thumb").forEach((t) => t.classList.remove("selected"));
});

// ---- email ----------------------------------------------------------
document.getElementById("email-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const msg = document.getElementById("email-message");
  const recipient = document.getElementById("email").value.trim();
  if (selected.size === 0) {
    showMessage(msg, "Select at least one photo to send.", false);
    return;
  }
  try {
    const r = await postForm("/email", {
      recipient,
      photo_ids: Array.from(selected).join(","),
    });
    showMessage(msg, r.message, true);
  } catch (err) {
    showMessage(msg, err.message, false);
  }
});

pollStatus();
setInterval(pollStatus, 1500);
loadGallery();
