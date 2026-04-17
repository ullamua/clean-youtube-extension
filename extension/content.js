// Content script - injects FAB on YouTube watch/shorts pages

(function() {
  if (document.getElementById("ytcl-fab")) return;

  function isVideoPage() {
    return /\/(watch|shorts)/.test(location.pathname);
  }

  function createFab() {
    if (document.getElementById("ytcl-fab") || !isVideoPage()) return;
    const btn = document.createElement("button");
    btn.id = "ytcl-fab";
    btn.title = "Get Clean Link";
    btn.textContent = "🔗";
    btn.addEventListener("click", () => {
      // MV3: Can't programmatically open popup from content script.
      // Instead, show a toast telling user to click the extension icon.
      const toast = document.getElementById("ytcl-toast");
      if (toast) {
        toast.textContent = "Click the 🔗 extension icon in your toolbar!";
        toast.classList.add("show");
        setTimeout(() => toast.classList.remove("show"), 3000);
      }
    });
    document.body.appendChild(btn);

    const toast = document.createElement("div");
    toast.id = "ytcl-toast";
    document.body.appendChild(toast);
  }

  function removeFab() {
    document.getElementById("ytcl-fab")?.remove();
    document.getElementById("ytcl-toast")?.remove();
  }

  createFab();

  // YouTube SPA navigation
  let lastUrl = location.href;
  const observer = new MutationObserver(() => {
    if (location.href !== lastUrl) {
      lastUrl = location.href;
      removeFab();
      setTimeout(createFab, 500);
    }
  });
  observer.observe(document.body, { childList: true, subtree: true });
})();
