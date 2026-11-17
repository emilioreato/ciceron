(() => {
  const host = location.hostname.toLowerCase();
  const IS_YOUTUBE = /(^|\.)youtube\.com$/.test(host);
  const IS_YOUTU_BE = host === "youtu.be";
  const IS_X = /(^|\.)(x|twitter)\.com$/.test(host);

  // Optional user selectors only affect X/Twitter; no page data leaves the browser.
  if (IS_X) {
    const customId = "ciceron-personal-x";
    const sidebarSelector = '[data-testid="sidebarColumn"]';
    function applyCustomSelectors(items) {
      const root = document.documentElement;
      if (!root) return;
      document.getElementById(customId)?.remove();
      const valid = (Array.isArray(items) ? items : []).filter(s => {
        if (typeof s !== "string" || !s.trim() || s.length > 300 || /[{};@\r\n]/.test(s)) return false;
        try { document.querySelector(s); return true; } catch { return false; }
      }).slice(0, 25);
      root.classList.toggle("ciceron-x-centered", valid.includes(sidebarSelector));
      if (!valid.length) return;
      const style = document.createElement("style"); style.id = customId;
      style.textContent = valid.map(s => `${s} { display: none !important; }`).join("\n");
      (document.head || document.documentElement).appendChild(style);
    }
    let customChangedDuringLoad = false;
    function readCustom() { chrome.storage.local.get({x_selectors: []}, x => { if (!customChangedDuringLoad) applyCustomSelectors(x.x_selectors); }); }
    if (document.documentElement) readCustom();
    else document.addEventListener("DOMContentLoaded", readCustom, {once:true});
    chrome.storage.onChanged.addListener((changes, area) => {
      if (area === "local" && changes.x_selectors) { customChangedDuringLoad = true; applyCustomSelectors(changes.x_selectors.newValue); }
    });
  }

  const STYLE_ID = "pausa-feed-v22-styles";
  const OVERLAY_ID = "pausa-feed-overlay";
  const SEARCH_ALLOW_KEY = "pausaFeedAllowedVideo";

  let enabled = true;
  let lastHref = location.href;
  let currentAllowedVideoId = null;
  let enforceRevision = 0;
  let storageChangedDuringLoad = false;

  function videoIdFrom(url) {
    if (url.hostname === "youtu.be") {
      return url.pathname.split("/").filter(Boolean)[0] || null;
    }
    if (!/(^|\.)youtube\.com$/.test(url.hostname)) return null;
    if (url.pathname === "/watch") return url.searchParams.get("v");
    const live = url.pathname.match(/^\/live\/([^/?#]+)/);
    return live?.[1] || null;
  }

  // A document that *starts* on a video is a deliberate direct link / refresh.
  // This is evaluated only once, before YouTube can SPA-navigate elsewhere.
  if ((IS_YOUTUBE || IS_YOUTU_BE)) {
    try {
      currentAllowedVideoId = videoIdFrom(new URL(location.href));
    } catch {}
  }

  const css = `
    html.pf-enabled.pf-blocked { overflow: hidden !important; background: #f6f8f5 !important; }
    html.pf-enabled.pf-blocked body { overflow: hidden !important; }

    #${OVERLAY_ID} {
      position: fixed !important;
      inset: 0 !important;
      z-index: 2147483647 !important;
      display: grid !important;
      place-items: center !important;
      padding: 24px !important;
      background: #f6f8f5 !important;
      color: #17211c !important;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif !important;
    }
    #${OVERLAY_ID} * { box-sizing: border-box !important; }
    #${OVERLAY_ID} .pf-card {
      width: min(560px, 100%) !important;
      padding: 30px !important;
      border: 1px solid #dce4dd !important;
      border-radius: 18px !important;
      background: #fff !important;
      box-shadow: 0 18px 60px rgba(0,0,0,.08) !important;
      text-align: center !important;
    }
    #${OVERLAY_ID} .pf-mark {
      display: grid !important;
      place-items: center !important;
      width: 46px !important;
      height: 46px !important;
      margin: 0 auto 18px !important;
      border-radius: 14px !important;
      background: #175c3c !important;
      color: #fff !important;
      font: 800 19px/1 system-ui, sans-serif !important;
    }
    #${OVERLAY_ID} h1 { margin: 0 0 8px !important; font: 700 22px/1.2 system-ui, sans-serif !important; }
    #${OVERLAY_ID} p { margin: 0 !important; color: #657169 !important; font: 14px/1.55 system-ui, sans-serif !important; }
    #${OVERLAY_ID} form { display: flex !important; gap: 8px !important; margin-top: 22px !important; }
    #${OVERLAY_ID} input {
      min-width: 0 !important; flex: 1 !important; padding: 12px 14px !important;
      border: 1px solid #ccd6ce !important; border-radius: 11px !important;
      background: #fff !important; color: #17211c !important; font: 14px/1.2 system-ui, sans-serif !important;
    }
    #${OVERLAY_ID} button {
      padding: 12px 16px !important; border: 0 !important; border-radius: 11px !important;
      background: #175c3c !important; color: #fff !important; font: 650 14px/1 system-ui, sans-serif !important;
      cursor: pointer !important;
    }

    /* YouTube search: remove Shorts shelves/cards but leave normal search intact. */
    html.pf-enabled ytd-reel-shelf-renderer,
    html.pf-enabled ytd-rich-shelf-renderer[is-shorts],
    html.pf-enabled grid-shelf-view-model:has(a[href^="/shorts/"]),
    html.pf-enabled ytd-video-renderer:has(a[href^="/shorts/"]),
    html.pf-enabled ytd-rich-item-renderer:has(a[href^="/shorts/"]),
    html.pf-enabled ytm-shorts-lockup-view-model {
      display: none !important;
    }

    /* YouTube watch: video + metadata/comments may remain; recommendation surfaces do not. */
    html.pf-enabled.pf-youtube-watch #secondary,
    html.pf-enabled.pf-youtube-watch #related,
    html.pf-enabled.pf-youtube-watch ytd-watch-next-secondary-results-renderer,
    html.pf-enabled.pf-youtube-watch ytd-compact-autoplay-renderer,
    html.pf-enabled.pf-youtube-watch .ytp-endscreen-content,
    html.pf-enabled.pf-youtube-watch .ytp-ce-element,
    html.pf-enabled.pf-youtube-watch .ytp-cards-button,
    html.pf-enabled.pf-youtube-watch .ytp-cards-teaser,
    html.pf-enabled.pf-youtube-watch .ytp-autonav-toggle-button-container,
    html.pf-enabled.pf-youtube-watch .ytp-autonav-endscreen,
    html.pf-enabled.pf-youtube-watch .ytp-videowall-still {
      display: none !important;
    }

    /* X status: remove discovery/trending column. */
    html.pf-enabled.pf-x-status [data-testid="sidebarColumn"],
    html.pf-enabled.pf-x-status aside {
      display: none !important;
    }

    /* Center the reading column in the space available beside X's navigation. */
    :is(html.ciceron-x-centered, html.pf-enabled.pf-x-status) main[role="main"]:has([data-testid="primaryColumn"]) {
      align-items: center !important;
      min-inline-size: 0 !important;
    }
    :is(html.ciceron-x-centered, html.pf-enabled.pf-x-status) main[role="main"] > :has([data-testid="primaryColumn"]) {
      max-inline-size: 100% !important;
      margin-inline: auto !important;
    }
    :is(html.ciceron-x-centered, html.pf-enabled.pf-x-status) main[role="main"] :has(> [data-testid="primaryColumn"]) {
      inline-size: 100% !important;
      max-inline-size: 100% !important;
      justify-content: center !important;
    }
    :is(html.ciceron-x-centered, html.pf-enabled.pf-x-status) main[role="main"] [data-testid="primaryColumn"] {
      min-inline-size: 0 !important;
      max-inline-size: min(100%, 600px) !important;
      margin-inline: auto !important;
    }
  `;

  function ensureStyle() {
    if (!document.documentElement || document.getElementById(STYLE_ID)) return;
    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = css;
    (document.head || document.documentElement).appendChild(style);
  }

  function clearClasses() {
    const root = document.documentElement;
    if (!root) return;
    root.classList.remove("pf-blocked", "pf-youtube-watch", "pf-youtube-search", "pf-x-status");
  }

  function removeOverlay() {
    document.getElementById(OVERLAY_ID)?.remove();
  }

  function mountOverlay(title, message, withSearch = false) {
    const revision = enforceRevision;
    const root = document.documentElement;
    if (!root) return;
    root.classList.add("pf-blocked");

    const mount = () => {
      // A storage update or route change may have invalidated this pending mount.
      if (!document.body || !enabled || revision !== enforceRevision) return;
      let overlay = document.getElementById(OVERLAY_ID);
      if (overlay) overlay.remove();

      overlay = document.createElement("div");
      overlay.id = OVERLAY_ID;
      const card = document.createElement("div");
      card.className = "pf-card";
      card.innerHTML = `<div class="pf-mark">P</div><h1></h1><p></p>`;
      card.querySelector("h1").textContent = title;
      card.querySelector("p").textContent = message;

      if (withSearch) {
        const form = document.createElement("form");
        const input = document.createElement("input");
        const button = document.createElement("button");
        input.type = "search";
        input.placeholder = "Buscar en YouTube";
        input.autocomplete = "off";
        input.setAttribute("aria-label", "Buscar en YouTube");
        button.type = "submit";
        button.textContent = "Buscar";
        form.append(input, button);
        form.addEventListener("submit", (event) => {
          event.preventDefault();
          const q = input.value.trim();
          if (!q) return;
          location.href = `https://www.youtube.com/results?search_query=${encodeURIComponent(q)}`;
        });
        card.appendChild(form);
      }

      overlay.appendChild(card);
      document.body.appendChild(overlay);
    };

    if (document.body) mount();
    else document.addEventListener("DOMContentLoaded", mount, { once: true });
  }

  function youtubeRouteAllowed(url) {
    if (url.pathname === "/results") {
      document.documentElement.classList.add("pf-youtube-search");
      return true;
    }

    const id = videoIdFrom(url);
    if (id) {
      const oneShot = sessionStorage.getItem(SEARCH_ALLOW_KEY);
      if (id === currentAllowedVideoId || id === oneShot) {
        currentAllowedVideoId = id;
        if (id === oneShot) sessionStorage.removeItem(SEARCH_ALLOW_KEY);
        document.documentElement.classList.add("pf-youtube-watch");
        return true;
      }
      return false;
    }

    return false;
  }

  function isXStatus(url) {
    return /^\/[^/]+\/status\/\d+(?:\/|$)/.test(url.pathname);
  }

  function enforce() {
    if (!document.documentElement) return;
    ++enforceRevision;
    ensureStyle();
    const root = document.documentElement;
    root.classList.toggle("pf-enabled", enabled);
    clearClasses();
    removeOverlay();
    if (!enabled) return;

    let url;
    try { url = new URL(location.href); } catch { return; }

    if (IS_YOUTU_BE) {
      // youtu.be is intentionally allowed only to perform its normal redirect to YouTube watch.
      return;
    }

    if (IS_YOUTUBE) {
      if (youtubeRouteAllowed(url)) return;
      const id = videoIdFrom(url);
      mountOverlay(
        "YouTube sin feed",
        id
          ? "Ese vídeo no fue abierto directamente ni elegido desde una búsqueda."
          : "Inicio, Suscripciones, Shorts, canales y otros feeds están bloqueados. Usa la búsqueda.",
        true
      );
      return;
    }

    if (IS_X) {
      if (isXStatus(url)) {
        root.classList.add("pf-x-status");
        return;
      }
      mountOverlay("X / Twitter sin feed", "Solo se permiten URLs directas de publicaciones.");
    }
  }

  // A result chosen by the user gets a one-use permit for its video id.
  function rememberSearchChoice(event) {
    if (!enabled || !IS_YOUTUBE || location.pathname !== "/results") return;
    const el = event.target instanceof Element ? event.target : null;
    const anchor = el?.closest("a[href]");
    if (!anchor) return;
    try {
      const dest = new URL(anchor.href, location.origin);
      const id = videoIdFrom(dest);
      if (id) sessionStorage.setItem(SEARCH_ALLOW_KEY, id);
    } catch {}
  }

  document.addEventListener("click", rememberSearchChoice, true);
  document.addEventListener("auxclick", rememberSearchChoice, true);
  window.addEventListener("popstate", () => setTimeout(enforce, 0));
  window.addEventListener("hashchange", () => setTimeout(enforce, 0));
  document.addEventListener("yt-navigate-finish", () => setTimeout(enforce, 0));

  // Cheap URL watcher. No whole-page MutationObserver: YouTube mutates the DOM constantly.
  setInterval(() => {
    if (location.href !== lastHref) {
      lastHref = location.href;
      enforce();
    }
  }, 250);

  function start() {
    ensureStyle();
    enforce();
  }
  if (document.documentElement) start();
  else document.addEventListener("DOMContentLoaded", start, { once: true });

  chrome.storage.local.get({ ciceron_enabled: true }, (settings) => {
    // Do not let a delayed initial read override a more recent storage event.
    if (storageChangedDuringLoad) return;
    enabled = settings.ciceron_enabled !== false;
    enforce();
  });

  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === "local" && changes.ciceron_enabled) {
      storageChangedDuringLoad = true;
      enabled = changes.ciceron_enabled.newValue !== false;
      enforce();
    }
  });
})();
