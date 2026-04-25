// Background service worker — handles all API calls

const DEFAULT_BACKEND = "http://localhost:8000";

async function getBackendURL() {
  const result = await chrome.storage.local.get("backendURL");
  return (result.backendURL || DEFAULT_BACKEND).replace(/\/+$/, "");
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "GENERATE_LINK") {
    handleGenerate(message.data)
      .then(sendResponse)
      .catch(err => sendResponse({ error: err.message || "Unknown error" }));
    return true;
  }
  if (message.type === "GET_BACKEND_URL") {
    getBackendURL().then(url => sendResponse({ url }));
    return true;
  }
  if (message.type === "SET_BACKEND_URL") {
    chrome.storage.local.set({ backendURL: message.url }).then(() => sendResponse({ success: true }));
    return true;
  }
  if (message.type === "GET_STATUS") {
    getBackendStatus().then(sendResponse).catch(() => sendResponse({ online: false, url: "" }));
    return true;
  }
  if (message.type === "UPLOAD_COOKIES") {
    handleCookieUpload(message.content)
      .then(sendResponse)
      .catch(err => sendResponse({ error: err.message }));
    return true;
  }
  if (message.type === "DELETE_COOKIES") {
    handleDeleteCookies()
      .then(sendResponse)
      .catch(err => sendResponse({ error: err.message }));
    return true;
  }
});

async function getBackendStatus() {
  const url = await getBackendURL();
  try {
    const ctrl = new AbortController();
    const timeout = setTimeout(() => ctrl.abort(), 5000);
    const res = await fetch(`${url}/`, { signal: ctrl.signal });
    clearTimeout(timeout);
    if (res.ok) {
      const data = await res.json();
      return { online: true, url, data };
    }
    return { online: false, url };
  } catch {
    return { online: false, url };
  }
}

async function handleGenerate(data) {
  const backendURL = await getBackendURL();
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 60000);

  try {
    const res = await fetch(`${backendURL}/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: data.url,
        expire_minutes: Number(data.expire_minutes),
        quality: data.quality || "best"
      }),
      signal: controller.signal
    });

    clearTimeout(timeout);

    const body = await res.json().catch(() => ({}));

    if (!res.ok) {
      throw new Error(body.detail || body.error || `Server error (${res.status})`);
    }

    return body;
  } catch (err) {
    clearTimeout(timeout);
    if (err.name === "AbortError") throw new Error("Request timed out (60s) — the server may be overloaded.");
    if (err.message.includes("Failed to fetch") || err.message.includes("NetworkError")) {
      throw new Error("Cannot reach backend. Check Settings and make sure the server is running.");
    }
    throw err;
  }
}

async function handleCookieUpload(fileContent) {
  const backendURL = await getBackendURL();
  const blob = new Blob([fileContent], { type: "text/plain" });
  const formData = new FormData();
  formData.append("file", blob, "cookies.txt");

  const ctrl = new AbortController();
  const timeout = setTimeout(() => ctrl.abort(), 15000);

  try {
    const res = await fetch(`${backendURL}/upload-cookies`, {
      method: "POST",
      body: formData,
      signal: ctrl.signal
    });
    clearTimeout(timeout);
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.detail || body.error || `Upload failed (${res.status})`);
    return body;
  } catch (err) {
    clearTimeout(timeout);
    if (err.name === "AbortError") throw new Error("Upload timed out.");
    throw err;
  }
}

async function handleDeleteCookies() {
  const backendURL = await getBackendURL();
  const ctrl = new AbortController();
  const timeout = setTimeout(() => ctrl.abort(), 10000);

  try {
    const res = await fetch(`${backendURL}/cookies`, {
      method: "DELETE",
      signal: ctrl.signal
    });
    clearTimeout(timeout);
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.detail || `Delete failed (${res.status})`);
    return body;
  } catch (err) {
    clearTimeout(timeout);
    if (err.name === "AbortError") throw new Error("Request timed out.");
    throw err;
  }
}
