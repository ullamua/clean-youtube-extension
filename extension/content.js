// Content script - injects FAB on YouTube watch/shorts pages

(function () {
  const FAB_ID = "ytcl-fab";
  const TOAST_ID = "ytcl-toast";

  function isVideoPage() {
    return /\/(watch|shorts)/.test(location.pathname);
  }

  function createFab() {
    if (document.getElementById(FAB_ID) || !isVideoPage()) return;

    const btn = document.createElement("button");
    btn.id = FAB_ID;
    btn.title = "Generate clean link";
    btn.setAttribute("aria-label", "Generate clean YouTube link");
    btn.innerHTML = `
      <span class="ytcl-fab-icon">
        <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M10 14a3.5 3.5 0 0 0 5 0l3-3a3.5 3.5 0 0 0-5-5l-1.5 1.5" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>
          <path d="M14 10a3.5 3.5 0 0 0-5 0l-3 3a3.5 3.5 0 0 0 5 5l1.5-1.5" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </span>
      <span class="ytcl-fab-label">Clean Link</span>
    `;
    btn.addEventListener("click", () => {
      showToast("Click the YT Clean Link icon in your toolbar →");
    });
    document.body.appendChild(btn);

    const toast = document.createElement("div");
    toast.id = TOAST_ID;
    document.body.appendChild(toast);
  }

  function showToast(msg) {
    const toast = document.getElementById(TOAST_ID);
    if (!toast) return;
    toast.textContent = msg;
    toast.classList.add("show");
    clearTimeout(window._ytclToast);
    window._ytclToast = setTimeout(() => toast.classList.remove("show"), 3000);
  }

  function removeFab() {
    document.getElementById(FAB_ID)?.remove();
    document.getElementById(TOAST_ID)?.remove();
  }

  function sync() {
    if (isVideoPage()) createFab();
    else removeFab();
  }

  sync();

  // YouTube SPA navigation
  let lastUrl = location.href;
  const observer = new MutationObserver(() => {
    if (location.href !== lastUrl) {
      lastUrl = location.href;
      removeFab();
      setTimeout(sync, 500);
    }
  });
  observer.observe(document.body, { childList: true, subtree: true });
})();
