// Popup logic

let selectedMinutes = 30;
let selectedQuality = "best";
let currentUrl = null;
let lastGenTime = 0;

const QUALITY_LABELS = {
  "360": "Up to 360p",
  "480": "Up to 480p",
  "720": "Up to 720p (HD)",
  "1080": "Up to 1080p (FHD)",
  "best": "Best available"
};

const EXPIRE_LABELS = {
  "5": "5 minutes",
  "30": "30 minutes",
  "60": "1 hour",
  "1440": "24 hours",
  "0": "Never expires"
};

document.addEventListener("DOMContentLoaded", init);

async function init() {
  pingBackend();

  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

  if (!tab?.url || !isYouTubeVideo(tab.url)) {
    document.getElementById("noVideo").style.display = "block";
    return;
  }

  currentUrl = tab.url;
  document.getElementById("videoView").style.display = "block";

  const title = tab.title?.replace(" - YouTube", "").trim() || "YouTube Video";
  document.getElementById("videoTitle").textContent = title;
  document.getElementById("videoUrl").textContent = prettyUrl(tab.url);

  const videoId = extractVideoId(tab.url);
  if (videoId) {
    document.getElementById("videoThumb").style.backgroundImage =
      `url('https://i.ytimg.com/vi/${videoId}/mqdefault.jpg')`;
  }

  // Quality chips
  document.querySelectorAll(".quality-grid .chip").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".quality-grid .chip").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      selectedQuality = btn.dataset.quality;
      document.getElementById("qualityHint").textContent = QUALITY_LABELS[selectedQuality];
    });
  });

  // Expiration chips
  document.querySelectorAll(".expire-grid .chip").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".expire-grid .chip").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      selectedMinutes = parseInt(btn.dataset.minutes);
      document.getElementById("expireHint").textContent = EXPIRE_LABELS[String(selectedMinutes)];
      document.getElementById("neverWarn").classList.toggle("show", selectedMinutes === 0);
    });
  });

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

function extractVideoId(url) {
  try {
    const u = new URL(url);
    if (u.pathname.startsWith("/shorts/")) return u.pathname.split("/")[2];
    return u.searchParams.get("v");
  } catch { return null; }
}

function prettyUrl(url) {
  try {
    const u = new URL(url);
    return u.host + u.pathname;
  } catch { return url; }
}

async function pingBackend() {
  const dot = document.querySelector(".status-dot");
  const label = document.getElementById("backendLabel");
  try {
    const { url } = await chrome.runtime.sendMessage({ type: "GET_BACKEND_URL" });
    label.textContent = new URL(url).host;
    const res = await fetch(url + "/", { method: "GET" });
    if (res.ok) dot.classList.add("online");
    else dot.classList.add("offline");
  } catch {
    dot.classList.add("offline");
  }
}

async function generate() {
  if (Date.now() - lastGenTime < 3000) return;
  lastGenTime = Date.now();

  const btn = document.getElementById("generateBtn");
  const errorEl = document.getElementById("error");
  const resultEl = document.getElementById("result");

  btn.disabled = true;
  btn.classList.add("loading");
  errorEl.classList.remove("show");
  resultEl.classList.remove("show");

  try {
    const response = await chrome.runtime.sendMessage({
      type: "GENERATE_LINK",
      data: {
        url: currentUrl,
        expire_minutes: selectedMinutes,
        quality: selectedQuality
      }
    });

    if (response.error) throw new Error(response.error);

    document.getElementById("resultUrl").textContent = response.clean_url;
    const qualityTag = response.quality ? ` · ${response.quality}` : "";
    document.getElementById("resultMeta").textContent =
      `${response.expires_in}${qualityTag}`;
    resultEl.classList.add("show");
    showToast("Link ready");
  } catch (err) {
    errorEl.textContent = err.message || "Failed to generate link";
    errorEl.classList.add("show");
  } finally {
    btn.disabled = false;
    btn.classList.remove("loading");
  }
}

async function copyLink() {
  const url = document.getElementById("resultUrl").textContent;
  try {
    await navigator.clipboard.writeText(url);
    showToast("Copied to clipboard");
  } catch {
    showToast("Copy failed");
  }
}

function openLink() {
  const url = document.getElementById("resultUrl").textContent;
  chrome.tabs.create({ url });
}

function showToast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(window._toastTimer);
  window._toastTimer = setTimeout(() => t.classList.remove("show"), 1800);
}
