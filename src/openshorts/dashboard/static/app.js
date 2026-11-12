const CATEGORIES = {
  best_moments: "Best Moments",
  funny: "Funny Clips",
  tips_tricks: "Tips & Tricks",
  unsorted: "Unsorted",
};

const PLATFORMS = {
  youtube: { label: "YouTube", icon: "▶", docs: "Create an OAuth client in Google Cloud Console (YouTube Data API v3, scope youtube.upload), run the consent flow, paste the access token here." },
  tiktok: { label: "TikTok", icon: "♪", docs: "Create an app at developers.tiktok.com with Content Posting API access, paste the resulting access token here." },
  instagram: { label: "Instagram", icon: "■", docs: "Needs a Business/Creator account linked to a Facebook Page, an access token with instagram_content_publish, your IG user id, and a public base URL where clips are hosted (Instagram fetches videos by URL, not by upload)." },
};

let connectionsState = {};
let activeCategory = "";

function $(sel, root = document) { return root.querySelector(sel); }
function $all(sel, root = document) { return [...root.querySelectorAll(sel)]; }

function showToast(message, isError = false) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.toggle("error", isError);
  toast.classList.add("show");
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => toast.classList.remove("show"), 3200);
}

async function api(path, options = {}) {
  const resp = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(body.detail || `Request failed (${resp.status})`);
  return body;
}

// ---------------------------------------------------------------- tabs --
function initTabs() {
  $all(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      $all(".tab-btn").forEach((b) => b.classList.remove("active"));
      $all(".tab-panel").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      $(`#tab-${btn.dataset.tab}`).classList.add("active");
      if (btn.dataset.tab === "stats") loadStats();
      if (btn.dataset.tab === "connections") loadConnections();
    });
  });
}

// ------------------------------------------------------------- add tab --
function statusLabel(status) {
  return { queued: "Queued", downloading: "Downloading", detecting: "Detecting highlights",
           clipping: "Cutting clips", done: "Done", error: "Error" }[status] || status;
}

function doneBadge(s) {
  if (s.clip_count === null || s.clip_count === undefined) return statusLabel(s.status);
  if (s.clip_count === 0) return "Done — 0 clips found";
  return `Done — ${s.clip_count} clip${s.clip_count === 1 ? "" : "s"}`;
}

async function loadSources() {
  const sources = await api("/api/sources");
  const list = $("#sources-list");
  if (!sources.length) {
    list.innerHTML = '<p class="empty-state">Nothing queued yet — drop a link above.</p>';
    return;
  }
  list.innerHTML = sources.map((s) => `
    <div class="source-row">
      <span class="src-name" title="${escapeHtml(s.url_or_path)}">${escapeHtml(s.title || s.url_or_path)}</span>
      <span class="status-badge status-${s.status}${s.status === "done" && s.clip_count === 0 ? " status-zero" : ""}">${s.status === "done" ? doneBadge(s) : statusLabel(s.status)}</span>
    </div>
    ${s.status === "done" && s.clip_count === 0 ? `<p class="hint">No highlights crossed the sensitivity threshold. Try dragging "Sensitivity" lower and re-adding this video.</p>` : ""}
    ${s.error ? `<p class="hint" style="color:var(--bad)">${escapeHtml(s.error)}</p>` : ""}
  `).join("");

  const stillWorking = sources.some((s) => !["done", "error"].includes(s.status));
  if (stillWorking) {
    clearTimeout(window._sourcePoll);
    window._sourcePoll = setTimeout(() => { loadSources(); loadClips(); }, 3000);
  }
}

function initAddForm() {
  const thresholdInput = $("#source-threshold");
  const thresholdValue = $("#source-threshold-value");
  thresholdInput.addEventListener("input", () => { thresholdValue.textContent = thresholdInput.value; });

  $("#source-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = $("#source-input");
    const hint = $("#source-hint");
    try {
      await api("/api/sources", {
        method: "POST",
        body: JSON.stringify({ url_or_path: input.value, threshold: parseFloat(thresholdInput.value) }),
      });
      hint.textContent = "Queued — watch progress below.";
      input.value = "";
      loadSources();
    } catch (err) {
      hint.textContent = err.message;
    }
  });
}

// ----------------------------------------------------------- clips tab --
function initCategoryFilters() {
  const row = $("#category-filters");
  Object.entries(CATEGORIES).forEach(([key, label]) => {
    const chip = document.createElement("button");
    chip.className = "chip";
    chip.dataset.category = key;
    chip.textContent = label;
    row.appendChild(chip);
  });
  row.addEventListener("click", (e) => {
    const chip = e.target.closest(".chip");
    if (!chip) return;
    activeCategory = chip.dataset.category;
    $all(".chip", row).forEach((c) => c.classList.toggle("active", c === chip));
    loadClips();
  });
}

function platformBadges(posts) {
  if (!posts.length) return "";
  return `<div class="post-row">${posts.map((p) =>
    `<span class="post-btn posted">${PLATFORMS[p.platform]?.icon || ""} ${PLATFORMS[p.platform]?.label || p.platform}</span>`
  ).join("")}</div>`;
}

async function loadClips() {
  const url = activeCategory ? `/api/clips?category=${encodeURIComponent(activeCategory)}` : "/api/clips";
  const clips = await api(url);
  const grid = $("#clips-grid");
  if (!clips.length) {
    grid.innerHTML = '<p class="empty-state">No clips yet. Add a video to get started.</p>';
    return;
  }
  grid.innerHTML = clips.map((clip) => {
    const postedPlatforms = new Set(clip.posts.map((p) => p.platform));
    const postButtons = Object.keys(PLATFORMS).map((platform) => {
      const posted = postedPlatforms.has(platform);
      const connected = connectionsState[platform]?.connected;
      const disabled = posted || !connected;
      return `<button class="post-btn ${posted ? "posted" : ""}" data-clip="${clip.id}" data-platform="${platform}"
                ${disabled ? "disabled" : ""} title="${posted ? "Already posted" : connected ? "" : platform + " not connected"}">
                ${PLATFORMS[platform].icon} ${posted ? "Posted" : PLATFORMS[platform].label}
              </button>`;
    }).join("");

    return `
      <div class="clip-card">
        <video src="/api/clips/${clip.id}/file" controls preload="metadata"></video>
        <div class="clip-card-body">
          <div class="clip-meta">
            <span>t=${clip.peak_time.toFixed(1)}s</span>
            <span class="clip-score">score ${clip.score.toFixed(1)}</span>
          </div>
          <select class="category-select" data-clip="${clip.id}">
            ${Object.entries(CATEGORIES).map(([k, label]) =>
              `<option value="${k}" ${k === clip.category ? "selected" : ""}>${label}</option>`).join("")}
          </select>
          <div class="post-row">${postButtons}</div>
          ${clip.posts.length ? `<p class="hint">Posted to ${clip.posts.map((p) => PLATFORMS[p.platform]?.label).join(", ")}</p>` : ""}
        </div>
      </div>`;
  }).join("");

  $all(".category-select", grid).forEach((select) => {
    select.addEventListener("change", async () => {
      try {
        await api(`/api/clips/${select.dataset.clip}`, {
          method: "PATCH", body: JSON.stringify({ category: select.value }),
        });
        showToast("Category updated.");
        loadClips();
      } catch (err) { showToast(err.message, true); }
    });
  });

  $all(".post-btn:not([disabled])", grid).forEach((btn) => {
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      btn.textContent = "Posting…";
      try {
        const result = await api(`/api/clips/${btn.dataset.clip}/post`, {
          method: "POST", body: JSON.stringify({ platform: btn.dataset.platform }),
        });
        showToast(`Posted to ${PLATFORMS[btn.dataset.platform].label}: "${result.title}"`);
        loadClips();
      } catch (err) {
        showToast(err.message, true);
        btn.disabled = false;
        btn.textContent = PLATFORMS[btn.dataset.platform].label;
      }
    });
  });
}

// ----------------------------------------------------- connections tab --
async function loadConnections() {
  const rows = await api("/api/connections");
  connectionsState = Object.fromEntries(rows.map((r) => [r.platform, r]));

  const grid = $("#connections-grid");
  grid.innerHTML = Object.keys(PLATFORMS).map((platform) => {
    const row = connectionsState[platform] || {};
    const connected = !!row.connected;
    const extraFields = platform === "instagram" ? `
      <input type="text" data-field="ig_user_id" placeholder="Instagram Business account id" />
      <input type="text" data-field="public_base_url" placeholder="Public URL where your clips are hosted (https://…)" />
    ` : "";
    return `
      <div class="glass connection-card" data-platform="${platform}">
        <div class="conn-head">
          <h3>${PLATFORMS[platform].icon} ${PLATFORMS[platform].label}</h3>
          <span class="conn-status"><span class="dot ${connected ? "connected" : "disconnected"}"></span>${connected ? "Connected" : "Not connected"}</span>
        </div>
        <p class="conn-card-note">${PLATFORMS[platform].docs}</p>
        <input type="text" data-field="access_token" placeholder="${row.token_preview ? "Token saved (" + row.token_preview + ") — paste to replace" : "Paste access token"}" />
        ${extraFields}
        <div class="conn-actions">
          <button class="btn btn-primary btn-small" data-action="save">Save</button>
          <button class="btn btn-ghost btn-small" data-action="disconnect">Disconnect</button>
        </div>
      </div>`;
  }).join("");

  $all(".connection-card", grid).forEach((card) => {
    const platform = card.dataset.platform;
    card.querySelector('[data-action="save"]').addEventListener("click", async () => {
      const token = card.querySelector('[data-field="access_token"]').value.trim();
      const meta = {};
      card.querySelectorAll("[data-field]").forEach((input) => {
        if (input.dataset.field !== "access_token" && input.value.trim()) meta[input.dataset.field] = input.value.trim();
      });
      try {
        const result = await api(`/api/connections/${platform}`, {
          method: "POST", body: JSON.stringify({ access_token: token, meta }),
        });
        showToast(result.connected ? `${PLATFORMS[platform].label} connected.` : "Saved, but token looks invalid.", !result.connected);
        loadConnections();
        loadClips();
      } catch (err) { showToast(err.message, true); }
    });
    card.querySelector('[data-action="disconnect"]').addEventListener("click", async () => {
      await api(`/api/connections/${platform}`, { method: "DELETE" });
      showToast(`${PLATFORMS[platform].label} disconnected.`);
      loadConnections();
      loadClips();
    });
  });
}

// ----------------------------------------------------------- stats tab --
function formatWatchTime(seconds) {
  if (!seconds) return "0m";
  const h = Math.floor(seconds / 3600);
  const m = Math.round((seconds % 3600) / 60);
  return h ? `${h}h ${m}m` : `${m}m`;
}

async function loadStats() {
  const stats = await api("/api/stats");

  $("#stat-tiles").innerHTML = `
    <div class="stat-tile"><div class="stat-value">${stats.total_views.toLocaleString()}</div><div class="stat-label">Total views</div></div>
    <div class="stat-tile"><div class="stat-value">${formatWatchTime(stats.total_watch_time_seconds)}</div><div class="stat-label">Watch time</div></div>
    <div class="stat-tile"><div class="stat-value">${Object.values(stats.by_platform).reduce((a, p) => a + p.posts, 0)}</div><div class="stat-label">Clips posted</div></div>
  `;

  const bestWrap = $("#best-performing-wrap");
  if (stats.best_performing) {
    const b = stats.best_performing;
    bestWrap.innerHTML = `
      <div class="best-card">
        <h4>Best performing</h4>
        <p>${PLATFORMS[b.platform]?.icon || ""} ${PLATFORMS[b.platform]?.label || b.platform} · ${CATEGORIES[b.category] || b.category}
           ${b.remote_url ? `· <a href="${b.remote_url}" target="_blank" style="color:var(--accent-a)">view</a>` : ""}</p>
      </div>`;
  } else {
    bestWrap.innerHTML = "";
  }

  const breakdown = $("#platform-breakdown");
  if (!stats.has_connections) {
    breakdown.innerHTML = '<p class="empty-state">Connect an account in the Connections tab to start tracking performance.</p>';
  } else if (Object.keys(stats.by_platform).length === 0) {
    breakdown.innerHTML = '<p class="empty-state">No posts yet — post a clip to see stats here.</p>';
  } else {
    breakdown.innerHTML = Object.entries(stats.by_platform).map(([platform, p]) => `
      <div class="platform-row">
        <span>${PLATFORMS[platform]?.icon || ""} ${PLATFORMS[platform]?.label || platform} (${p.posts} post${p.posts === 1 ? "" : "s"})</span>
        <span>${p.views.toLocaleString()} views · ${formatWatchTime(p.watch_time_seconds)}</span>
      </div>`).join("");
  }
}

function initStatsRefresh() {
  $("#refresh-stats-btn").addEventListener("click", async () => {
    const btn = $("#refresh-stats-btn");
    btn.disabled = true;
    btn.textContent = "Refreshing…";
    try {
      const result = await api("/api/stats/refresh", { method: "POST" });
      showToast(`Refreshed ${result.refreshed} post(s).`);
      loadStats();
    } catch (err) {
      showToast(err.message, true);
    } finally {
      btn.disabled = false;
      btn.textContent = "Refresh stats";
    }
  });
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

async function init() {
  initTabs();
  initAddForm();
  initCategoryFilters();
  initStatsRefresh();
  await loadConnections();
  await loadClips();
  await loadSources();
}

init();
