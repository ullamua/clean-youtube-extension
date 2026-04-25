// Popup logic v2

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
  // Load saved preferences
  const prefs = await chrome.storage.local.get(["savedQuality", "savedMinutes"]);
  if (prefs.savedQuality) selectedQuality = prefs.savedQuality;
  if (prefs.savedMinutes !== undefined) selectedMinutes = prefs.savedMinutes;

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

  // Quality chips — restore saved preference
  document.querySelectorAll(".quality-grid .chip").forEach(btn => {
    if (btn.dataset.quality === selectedQuality) {
      document.querySelectorAll(".quality-grid .chip").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById("qualityHint").textContent = QUALITY_LABELS[selectedQuality];
    }
    btn.addEventListener("click", () => {
      document.querySelectorAll(".quality-grid .chip").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      selectedQuality = btn.dataset.quality;
      document.getElementById("qualityHint").textContent = QUALITY_LABELS[selectedQuality];
      chrome.storage.local.set({ savedQuality: selectedQuality });
    });
  });

  // Expiration chips — restore saved preference
  document.querySelectorAll(".expire-grid .chip").forEach(btn => {
    const minutes = parseInt(btn.dataset.minutes, 10);
    if (minutes === selectedMinutes) {
      document.querySelectorAll(".expire-grid .chip").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById("expireHint").textContent = EXPIRE_LABELS[String(selectedMinutes)];
      document.getElementById("neverWarn").classList.toggle("show", selectedMinutes === 0);
    }
    btn.addEventListener("click", () => {
      document.querySelectorAll(".expire-grid .chip").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      selectedMinutes = parseInt(btn.dataset.minutes, 10);
      document.getElementById("expireHint").textContent = EXPIRE_LABELS[String(selectedMinutes)];
      document.getElementById("neverWarn").classList.toggle("show", selectedMinutes === 0);
      chrome.storage.local.set({ savedMinutes: selectedMinutes });
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
  return /youtube\.com\/(watch|shorts)/.test(url) || /youtu\.be\//.test(url);
}

function extractVideoId(url) {
  try {
    const u = new URL(url);
    if (u.hostname === "youtu.be") return u.pathname.slice(1);
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
    const status = await chrome.runtime.sendMessage({ type: "GET_STATUS" });
    if (status?.url) {
      label.textContent = new URL(status.url).host;
    }
    if (status?.online) {
      dot.classList.add("online");
      dot.classList.remove("offline");
      if (status.data?.cookies_configured) {
        const count = status.data.cookies_entries || "?";
        document.getElementById("cookieStatus").textContent = `Cookies: ${count} entries`;
        document.getElementById("cookieStatus").className = "cookie-badge ok";
      } else {
        document.getElementById("cookieStatus").textContent = "No cookies";
        document.getElementById("cookieStatus").className = "cookie-badge warn";
      }
    } else {
      dot.classList.add("offline");
      dot.classList.remove("online");
    }
  } catch {
    dot.classList.add("offline");
    dot.classList.remove("online");
  }
}

async function generate() {
  const now = Date.now();
  if (now - lastGenTime < 2000) return;
  lastGenTime = now;

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

    if (response?.error) throw new Error(response.error);
    if (!response?.clean_url) throw new Error("Invalid response from backend.");

    document.getElementById("resultUrl").textContent = response.clean_url;
    document.getElementById("resultUrl").dataset.url = response.clean_url;

    const parts = [];
    if (response.expires_in) parts.push(response.expires_in);
    if (response.quality) parts.push(response.quality);
    document.getElementById("resultMeta").textContent = parts.join(" · ");

    if (response.title) {
      document.getElementById("resultTitle").textContent = response.title;
      document.getElementById("resultTitle").style.display = "block";
    }

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
  const url = document.getElementById("resultUrl").textContent.trim();
  if (!url) return;
  try {
    await navigator.clipboard.writeText(url);
    showToast("Copied to clipboard");
  } catch {
    // Fallback
    const ta = document.createElement("textarea");
    ta.value = url;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    document.body.removeChild(ta);
    showToast("Copied!");
  }
}

function openLink() {
  const url = document.getElementById("resultUrl").textContent.trim();
  if (url) chrome.tabs.create({ url });
}

function showToast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(window._toastTimer);
  window._toastTimer = setTimeout(() => t.classList.remove("show"), 2000);
}
