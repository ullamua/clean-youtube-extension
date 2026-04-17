// Popup logic

let selectedMinutes = 30;
let currentUrl = null;
let lastGenTime = 0;

document.addEventListener("DOMContentLoaded", init);

async function init() {
  // Get current tab
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  
  if (!tab?.url || !isYouTubeVideo(tab.url)) {
    document.getElementById("noVideo").style.display = "block";
    return;
  }

  currentUrl = tab.url;
  document.getElementById("videoView").style.display = "block";
  
  // Extract title from tab
  const title = tab.title?.replace(" - YouTube", "").trim() || "YouTube Video";
  document.getElementById("videoTitle").textContent = title;

  // Expiration buttons
  document.querySelectorAll(".expire-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".expire-btn").forEach(b => {
        b.classList.remove("active", "danger");
      });
      selectedMinutes = parseInt(btn.dataset.minutes);
      btn.classList.add(selectedMinutes === 0 ? "danger" : "active");
      document.getElementById("neverWarn").style.display = 
        selectedMinutes === 0 ? "block" : "none";
    });
  });

  // Generate
  document.getElementById("generateBtn").addEventListener("click", generate);
  document.getElementById("copyBtn").addEventListener("click", copyLink);
  document.getElementById("openBtn").addEventListener("click", openLink);
  document.getElementById("settingsBtn").addEventListener("click", () => {
    chrome.runtime.openOptionsPage();
  });
}

function isYouTubeVideo(url) {
  return /youtube\.com\/(watch|shorts)/.test(url);
}

async function generate() {
  // Rate limit: 3s cooldown
  if (Date.now() - lastGenTime < 3000) return;
  lastGenTime = Date.now();

  const btn = document.getElementById("generateBtn");
  const errorEl = document.getElementById("error");
  const resultEl = document.getElementById("result");

  btn.disabled = true;
  btn.classList.add("loading");
  errorEl.style.display = "none";
  resultEl.style.display = "none";

  try {
    const response = await chrome.runtime.sendMessage({
      type: "GENERATE_LINK",
      data: { url: currentUrl, expire_minutes: selectedMinutes }
    });

    if (response.error) throw new Error(response.error);

    document.getElementById("resultUrl").textContent = response.clean_url;
    document.getElementById("resultMeta").textContent = 
      `Expires: ${response.expires_in} · ${response.title}`;
    resultEl.style.display = "block";
    showToast("Link generated! ✨");
  } catch (err) {
    errorEl.textContent = `❌ ${err.message || "Failed to generate link"}`;
    errorEl.style.display = "block";
  } finally {
    btn.disabled = false;
    btn.classList.remove("loading");
  }
}

function copyLink() {
  const url = document.getElementById("resultUrl").textContent;
  navigator.clipboard.writeText(url).then(() => {
    showToast("Link copied! 📋");
  });
}

function openLink() {
  const url = document.getElementById("resultUrl").textContent;
  chrome.tabs.create({ url });
}

function showToast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.classList.add("show");
  setTimeout(() => t.classList.remove("show"), 2000);
}
