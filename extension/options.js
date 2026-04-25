const DEFAULT_URL = "http://localhost:8000";

document.addEventListener("DOMContentLoaded", async () => {
  const input = document.getElementById("backendUrl");
  const result = await chrome.storage.local.get("backendURL");
  input.value = result.backendURL || DEFAULT_URL;

  // Check status on load
  await checkStatus();

  document.getElementById("saveBtn").addEventListener("click", async () => {
    const url = input.value.trim().replace(/\/+$/, "");
    if (!url) return;
    await chrome.storage.local.set({ backendURL: url });
    showSaveStatus("Settings saved");
    await checkStatus();
  });

  document.getElementById("testBtn").addEventListener("click", async () => {
    showSaveStatus("Testing connection…");
    await checkStatus();
  });

  document.getElementById("resetBtn").addEventListener("click", async () => {
    input.value = DEFAULT_URL;
    await chrome.storage.local.set({ backendURL: DEFAULT_URL });
    showSaveStatus("Reset to default");
    await checkStatus();
  });

  document.querySelectorAll(".preset-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      input.value = btn.dataset.url;
    });
  });

  // Cookie upload
  const dropZone = document.getElementById("cookieDropZone");
  const fileInput = document.getElementById("cookieFile");

  dropZone.addEventListener("dragover", e => {
    e.preventDefault();
    dropZone.classList.add("drag-over");
  });
  dropZone.addEventListener("dragleave", () => dropZone.classList.remove("drag-over"));
  dropZone.addEventListener("drop", e => {
    e.preventDefault();
    dropZone.classList.remove("drag-over");
    const file = e.dataTransfer?.files?.[0];
    if (file) handleCookieFile(file);
  });

  fileInput.addEventListener("change", () => {
    if (fileInput.files?.[0]) handleCookieFile(fileInput.files[0]);
    fileInput.value = "";
  });

  document.getElementById("cookieDeleteBtn").addEventListener("click", async () => {
    if (!confirm("Delete cookies from the backend?")) return;
    const response = await chrome.runtime.sendMessage({ type: "DELETE_COOKIES" });
    if (response?.error) {
      showCookieStatus("Error: " + response.error, true);
    } else {
      showCookieStatus("Cookies deleted");
      updateCookieUI(false, 0);
    }
  });
});

async function handleCookieFile(file) {
  if (!file.name.endsWith(".txt") && file.type !== "text/plain") {
    showCookieStatus("Please upload a .txt file (Netscape cookie format)", true);
    return;
  }
  showCookieStatus("Uploading…");

  const text = await file.text();
  const response = await chrome.runtime.sendMessage({ type: "UPLOAD_COOKIES", content: text });

  if (response?.error) {
    showCookieStatus("Upload failed: " + response.error, true);
  } else {
    showCookieStatus(response?.message || "Cookies uploaded successfully");
    await checkStatus();
  }
}

async function checkStatus() {
  const serverStatusRow = document.getElementById("serverStatus");
  const serverStatusLabel = document.getElementById("serverStatusLabel");
  const serverStatusSub = document.getElementById("serverStatusSub");
  const serverStatusIcon = document.getElementById("serverStatusIcon");

  serverStatusRow.style.display = "flex";
  serverStatusLabel.textContent = "Connecting…";
  serverStatusSub.textContent = "";

  const status = await chrome.runtime.sendMessage({ type: "GET_STATUS" });

  if (status?.online) {
    serverStatusIcon.className = "cookie-status-icon ok";
    serverStatusLabel.textContent = "Backend online";
    const v = status.data?.version ? ` · v${status.data.version}` : "";
    serverStatusSub.textContent = `Active links: ${status.data?.active_links ?? "?"}${v}`;

    const hasCookies = status.data?.cookies_configured;
    const cookieEntries = status.data?.cookies_entries ?? 0;
    updateCookieUI(hasCookies, cookieEntries);
  } else {
    serverStatusIcon.className = "cookie-status-icon none";
    serverStatusLabel.textContent = "Cannot reach backend";
    serverStatusSub.textContent = status?.url || "Check the backend URL above";
    updateCookieUI(null, 0);
  }
}

function updateCookieUI(hasCookies, entries) {
  const icon = document.getElementById("cookieStatusIcon");
  const label = document.getElementById("cookieStatusLabel");
  const sub = document.getElementById("cookieStatusSub");
  const deleteBtn = document.getElementById("cookieDeleteBtn");

  if (hasCookies === null) {
    icon.className = "cookie-status-icon none";
    label.textContent = "Status unknown";
    sub.textContent = "Backend unreachable";
    deleteBtn.classList.remove("show");
  } else if (hasCookies) {
    icon.className = "cookie-status-icon ok";
    label.textContent = "Cookies configured";
    sub.textContent = `${entries} entries on server`;
    deleteBtn.classList.add("show");
  } else {
    icon.className = "cookie-status-icon none";
    label.textContent = "No cookies uploaded";
    sub.textContent = "YouTube may block requests without cookies";
    deleteBtn.classList.remove("show");
  }
}

function showSaveStatus(msg, isError = false) {
  const el = document.getElementById("saveStatus");
  el.textContent = msg;
  el.className = "status-msg show" + (isError ? " error" : "");
  clearTimeout(el._timer);
  el._timer = setTimeout(() => el.classList.remove("show"), 2500);
}

function showCookieStatus(msg, isError = false) {
  const el = document.getElementById("cookieStatus");
  el.textContent = msg;
  el.className = "status-msg show" + (isError ? " error" : "");
  clearTimeout(el._timer);
  el._timer = setTimeout(() => el.classList.remove("show"), 2500);
}
