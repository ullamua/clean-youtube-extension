// Background service worker - handles API calls

const DEFAULT_BACKEND = "http://localhost:8000";

async function getBackendURL() {
  const result = await chrome.storage.local.get("backendURL");
  return result.backendURL || DEFAULT_BACKEND;
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "GENERATE_LINK") {
    handleGenerate(message.data).then(sendResponse).catch(err => {
      sendResponse({ error: err.message || "Unknown error" });
    });
    return true; // async
  }
  if (message.type === "GET_BACKEND_URL") {
    getBackendURL().then(url => sendResponse({ url }));
    return true;
  }
  if (message.type === "SET_BACKEND_URL") {
    chrome.storage.local.set({ backendURL: message.url }).then(() => {
      sendResponse({ success: true });
    });
    return true;
  }
});

async function handleGenerate(data) {
  const backendURL = await getBackendURL();
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30000);

  try {
    const res = await fetch(`${backendURL}/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: data.url,
        expire_minutes: data.expire_minutes
      }),
      signal: controller.signal
    });

    clearTimeout(timeout);

    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      throw new Error(errBody.detail || `Server error (${res.status})`);
    }

    return await res.json();
  } catch (err) {
    clearTimeout(timeout);
    if (err.name === "AbortError") throw new Error("Request timed out (30s)");
    throw err;
  }
}
