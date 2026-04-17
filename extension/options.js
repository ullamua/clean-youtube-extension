const DEFAULT_URL = "http://localhost:8000";

document.addEventListener("DOMContentLoaded", async () => {
  const input = document.getElementById("backendUrl");
  const result = await chrome.storage.local.get("backendURL");
  input.value = result.backendURL || DEFAULT_URL;

  document.getElementById("saveBtn").addEventListener("click", async () => {
    const url = input.value.trim().replace(/\/+$/, "");
    if (!url) return;
    await chrome.storage.local.set({ backendURL: url });
    showStatus("✅ Settings saved!");
  });

  document.getElementById("resetBtn").addEventListener("click", async () => {
    input.value = DEFAULT_URL;
    await chrome.storage.local.set({ backendURL: DEFAULT_URL });
    showStatus("✅ Reset to default!");
  });
});

function showStatus(msg) {
  const el = document.getElementById("status");
  el.textContent = msg;
  el.classList.add("show");
  setTimeout(() => el.classList.remove("show"), 2000);
}
