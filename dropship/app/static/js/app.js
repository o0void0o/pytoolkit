/* Dropship client.
 *
 * Plain vanilla JS, no deps. Uses XMLHttpRequest for uploads so we get real
 * progress events (fetch() still can't do that).
 */
(() => {
  "use strict";

  const meta = (n) => document.querySelector(`meta[name="${n}"]`)?.content || "";
  const CSRF_COOKIE = meta("csrf-cookie-name");
  const CSRF_HEADER = meta("csrf-header-name");
  const MAX_BYTES = parseInt(meta("max-upload-bytes"), 10) || (5 * 1024 ** 3);

  const $ = (sel) => document.querySelector(sel);
  const getCookie = (name) => {
    const m = document.cookie.match(new RegExp("(?:^|; )" + name + "=([^;]*)"));
    return m ? decodeURIComponent(m[1]) : "";
  };
  const fmtBytes = (n) => {
    if (!Number.isFinite(n) || n < 0) return "—";
    const u = ["B", "KB", "MB", "GB", "TB"];
    let i = 0, v = n;
    while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
    return `${v.toFixed(v >= 10 || i === 0 ? 0 : 1)} ${u[i]}`;
  };
  const fmtDate = (iso) => {
    if (!iso) return "—";
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    const p = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
  };
  const fmtUptime = (sec) => {
    sec = Math.max(0, Math.floor(sec));
    const d = Math.floor(sec / 86400);
    const h = Math.floor((sec % 86400) / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const s = sec % 60;
    if (d) return `${d}d ${h}h ${m}m`;
    if (h) return `${h}h ${m}m ${s}s`;
    if (m) return `${m}m ${s}s`;
    return `${s}s`;
  };
  const escapeHtml = (s) =>
    String(s).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const getCurrentPath = () => {
    const p = new URLSearchParams(location.search).get("path") || "";
    return p.replace(/^\/+|\/+$/g, "");
  };
  const setCurrentPath = (p) => {
    p = (p || "").replace(/^\/+|\/+$/g, "");
    currentPath = p;
    const url = new URL(location.href);
    if (p) url.searchParams.set("path", p);
    else url.searchParams.delete("path");
    history.pushState({ path: p }, "", url.toString());
    refresh();
  };

  const toastHost = $("#toasts");
  const toast = (msg, kind = "info", ttl = 3500) => {
    const el = document.createElement("div");
    el.className = `toast ${kind}`;
    el.textContent = msg;
    toastHost.appendChild(el);
    setTimeout(() => {
      el.classList.add("leaving");
      el.addEventListener("animationend", () => el.remove(), { once: true });
    }, ttl);
  };

  const initMatrix = () => {
    const canvas = $("#matrix-bg");
    if (!canvas) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const ctx = canvas.getContext("2d");
    let cols = 0, drops = [], font = 14;
    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = window.innerWidth * dpr;
      canvas.height = window.innerHeight * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      font = Math.max(12, Math.floor(window.innerWidth / 90));
      cols = Math.floor(window.innerWidth / font);
      drops = new Array(cols).fill(0).map(() => Math.random() * -50);
    };
    resize();
    window.addEventListener("resize", resize, { passive: true });
    const chars = "01<>{}/\\$#%&*+=_-|";
    const draw = () => {
      ctx.fillStyle = "rgba(2, 3, 8, 0.10)";
      ctx.fillRect(0, 0, window.innerWidth, window.innerHeight);
      ctx.font = `${font}px ui-monospace, monospace`;
      for (let i = 0; i < cols; i++) {
        const ch = chars[(Math.random() * chars.length) | 0];
        ctx.fillStyle = "rgba(0, 255, 156, 0.85)";
        ctx.fillText(ch, i * font, drops[i] * font);
        if (drops[i] * font > window.innerHeight && Math.random() > 0.975) drops[i] = 0;
        drops[i] += 1;
      }
    };
    let frameCounter = 0;
    const tick = () => { if (frameCounter++ % 2 === 0) draw(); requestAnimationFrame(tick); };
    tick();
  };

  const breadcrumbEl = $("#breadcrumb");
  const filesBody = $("#files-body");
  const searchInput = $("#search");
  let currentEntries = [];
  let currentPath = "";

  const renderBreadcrumb = () => {
    breadcrumbEl.innerHTML = "";
    const parts = currentPath ? currentPath.split("/") : [];
    const mk = (label, target, current = false) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "crumb" + (current ? " current" : "");
      b.textContent = label;
      if (!current) b.addEventListener("click", () => setCurrentPath(target));
      return b;
    };
    breadcrumbEl.appendChild(mk("~", "", parts.length === 0));
    let accum = "";
    parts.forEach((seg, i) => {
      const sep = document.createElement("span");
      sep.className = "sep";
      sep.textContent = " / ";
      breadcrumbEl.appendChild(sep);
      accum = accum ? `${accum}/${seg}` : seg;
      breadcrumbEl.appendChild(mk(seg, accum, i === parts.length - 1));
    });
  };

  const renderEntries = () => {
    const q = searchInput.value.trim().toLowerCase();
    const filtered = q
      ? currentEntries.filter((e) => e.name.toLowerCase().includes(q))
      : currentEntries;

    filesBody.innerHTML = "";

    if (currentPath) {
      const up = document.createElement("div");
      up.className = "files-row files-row--data";
      up.setAttribute("role", "row");
      up.innerHTML = `
        <span><span class="row-icon dir">↰</span><button type="button" class="dir-name" data-up>..</button></span>
        <span class="col-size"></span>
        <span class="col-date"></span>
        <span class="col-actions"></span>
      `;
      filesBody.appendChild(up);
    }

    if (filtered.length === 0 && !currentPath) {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = q ? "[ no matches ]" : "[ empty ]";
      filesBody.appendChild(empty);
      return;
    }

    const frag = document.createDocumentFragment();
    for (const e of filtered) {
      const row = document.createElement("div");
      row.className = "files-row files-row--data";
      row.setAttribute("role", "row");
      row.dataset.name = e.name;
      row.dataset.kind = e.kind;

      const childPath = currentPath ? `${currentPath}/${e.name}` : e.name;
      const dl = `/api/download?path=${encodeURIComponent(childPath)}`;

      if (e.kind === "dir") {
        row.innerHTML = `
          <span><span class="row-icon dir">▸</span><button type="button" class="dir-name" data-dir="${escapeHtml(childPath)}">${escapeHtml(e.name)}/</button></span>
          <span class="col-size">—</span>
          <span class="col-date">${fmtDate(e.uploaded_at_iso)}</span>
          <span class="col-actions">
            <button class="action-btn action-btn--danger" data-action="delete">delete</button>
          </span>
        `;
      } else {
        row.innerHTML = `
          <span><span class="row-icon file">◆</span><a class="file-name" href="${dl}" download title="${escapeHtml(e.name)}">${escapeHtml(e.name)}</a></span>
          <span class="col-size">${fmtBytes(e.size)}</span>
          <span class="col-date">${fmtDate(e.uploaded_at_iso)}</span>
          <span class="col-actions">
            <a class="action-btn" href="${dl}" download>download</a>
            <button class="action-btn action-btn--danger" data-action="delete">delete</button>
          </span>
        `;
      }
      frag.appendChild(row);
    }
    filesBody.appendChild(frag);
  };

  const fetchEntries = async () => {
    try {
      const url = `/api/files?path=${encodeURIComponent(currentPath)}`;
      const res = await fetch(url, { credentials: "same-origin" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      currentEntries = Array.isArray(data.entries) ? data.entries : [];
      currentPath = data.path || "";
      renderBreadcrumb();
      renderEntries();
    } catch (e) {
      toast(`failed to load: ${e.message}`, "error");
    }
  };

  const deleteEntry = async (name, kind) => {
    const full = currentPath ? `${currentPath}/${name}` : name;
    const what = kind === "dir" ? `folder "${name}" and everything inside it` : `"${name}"`;
    if (!confirm(`delete ${what}?`)) return;
    try {
      const res = await fetch(`/api/files?path=${encodeURIComponent(full)}`, {
        method: "DELETE",
        credentials: "same-origin",
        headers: { [CSRF_HEADER]: getCookie(CSRF_COOKIE) },
      });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(`HTTP ${res.status} — ${txt}`);
      }
      toast(`deleted ${name}`, "success");
      refresh();
    } catch (e) {
      toast(`delete failed: ${e.message}`, "error");
    }
  };

  const setStat = (key, val) => {
    const el = document.querySelector(`[data-stat="${key}"]`);
    if (el) el.textContent = val;
  };
  let lastStats = null;
  const fetchStats = async () => {
    try {
      const res = await fetch("/api/stats", { credentials: "same-origin" });
      if (!res.ok) return;
      lastStats = await res.json();
      paintStats();
    } catch (_) {}
  };
  const paintStats = () => {
    if (!lastStats) return;
    setStat("uptime", fmtUptime(lastStats.uptime_seconds));
    setStat("files", lastStats.stored_files);
    setStat("stored", fmtBytes(lastStats.stored_bytes));
    setStat("session", lastStats.total_uploads_session);
    setStat("free", fmtBytes(lastStats.disk_free_bytes));
  };
  setInterval(() => {
    if (!lastStats) return;
    lastStats.uptime_seconds += 1;
    setStat("uptime", fmtUptime(lastStats.uptime_seconds));
  }, 1000);

  const uploadList = $("#upload-list");
  const makeUploadRow = (file) => {
    const row = document.createElement("div");
    row.className = "upload-row";
    row.innerHTML = `
      <div class="upload-head">
        <span class="upload-name">${escapeHtml(file.name)}</span>
        <span class="upload-meta"><span class="upload-pct">0%</span> · <span class="upload-bytes">0 B / ${fmtBytes(file.size)}</span></span>
      </div>
      <div class="upload-bar"><div class="upload-fill"></div></div>
    `;
    uploadList.hidden = false;
    uploadList.prepend(row);
    return row;
  };

  const uploadOne = (file) => new Promise((resolve) => {
    if (file.size > MAX_BYTES) {
      toast(`${file.name}: exceeds ${fmtBytes(MAX_BYTES)} limit`, "error");
      resolve({ ok: false });
      return;
    }
    const row = makeUploadRow(file);
    const fill = row.querySelector(".upload-fill");
    const pct = row.querySelector(".upload-pct");
    const bytesEl = row.querySelector(".upload-bytes");

    const form = new FormData();
    form.append("files", file, file.name);
    form.append("path", currentPath);

    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/upload");
    xhr.withCredentials = true;
    xhr.setRequestHeader(CSRF_HEADER, getCookie(CSRF_COOKIE));

    xhr.upload.addEventListener("progress", (e) => {
      if (!e.lengthComputable) return;
      const ratio = e.loaded / e.total;
      fill.style.width = `${(ratio * 100).toFixed(1)}%`;
      pct.textContent = `${Math.floor(ratio * 100)}%`;
      bytesEl.textContent = `${fmtBytes(e.loaded)} / ${fmtBytes(e.total)}`;
    });
    xhr.addEventListener("load", () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        row.classList.add("done");
        fill.style.width = "100%";
        pct.textContent = "100%";
        toast(`✓ ${file.name}`, "success", 2200);
        setTimeout(() => {
          row.style.transition = "opacity 0.4s ease, height 0.4s ease, margin 0.4s ease, padding 0.4s ease";
          row.style.opacity = "0";
          row.style.height = `${row.offsetHeight}px`;
          requestAnimationFrame(() => {
            row.style.height = "0";
            row.style.marginTop = "0";
            row.style.paddingTop = "0";
            row.style.paddingBottom = "0";
          });
          setTimeout(() => {
            row.remove();
            if (!uploadList.children.length) uploadList.hidden = true;
          }, 420);
        }, 800);
        resolve({ ok: true });
      } else {
        row.classList.add("error");
        let detail = `HTTP ${xhr.status}`;
        try {
          const body = JSON.parse(xhr.responseText);
          if (body?.error) detail = body.error;
        } catch (_) {}
        toast(`✗ ${file.name}: ${detail}`, "error", 5000);
        resolve({ ok: false });
      }
    });
    xhr.addEventListener("error", () => {
      row.classList.add("error");
      toast(`network error: ${file.name}`, "error");
      resolve({ ok: false });
    });
    xhr.addEventListener("abort", () => {
      row.classList.add("error");
      resolve({ ok: false });
    });
    xhr.send(form);
  });

  const uploadFiles = async (fileList) => {
    if (!fileList || fileList.length === 0) return;
    const files = Array.from(fileList);
    const where = currentPath ? ` to /${currentPath}` : "";
    toast(`queuing ${files.length} file${files.length === 1 ? "" : "s"}${where}…`, "info", 1800);
    for (const f of files) await uploadOne(f);
    refresh();
  };

  const dropzone = $("#dropzone");
  const fileInput = $("#file-input");
  const pickBtn = $("#pick-btn");
  const openPicker = () => fileInput.click();
  dropzone.addEventListener("click", (e) => {
    if (e.target.closest("button, a")) return;
    openPicker();
  });
  dropzone.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openPicker(); }
  });
  pickBtn.addEventListener("click", (e) => { e.stopPropagation(); openPicker(); });
  fileInput.addEventListener("change", () => {
    uploadFiles(fileInput.files);
    fileInput.value = "";
  });

  ["dragenter", "dragover"].forEach((evt) => {
    dropzone.addEventListener(evt, (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropzone.classList.add("drag-over");
    });
  });
  ["dragleave", "drop"].forEach((evt) => {
    dropzone.addEventListener(evt, (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (evt === "dragleave" && dropzone.contains(e.relatedTarget)) return;
      dropzone.classList.remove("drag-over");
    });
  });
  dropzone.addEventListener("drop", (e) => {
    if (e.dataTransfer?.files?.length) uploadFiles(e.dataTransfer.files);
  });
  ["dragover", "drop"].forEach((evt) =>
    window.addEventListener(evt, (e) => {
      if (!dropzone.contains(e.target)) e.preventDefault();
    })
  );

  filesBody.addEventListener("click", (e) => {
    if (e.target.matches("[data-up]")) {
      const parts = currentPath.split("/").filter(Boolean);
      parts.pop();
      setCurrentPath(parts.join("/"));
      return;
    }
    const dirBtn = e.target.closest("[data-dir]");
    if (dirBtn) {
      setCurrentPath(dirBtn.dataset.dir);
      return;
    }
    const action = e.target.closest("[data-action]");
    if (!action) return;
    const row = action.closest(".files-row");
    if (!row) return;
    if (action.dataset.action === "delete") {
      deleteEntry(row.dataset.name, row.dataset.kind);
    }
  });

  searchInput.addEventListener("input", renderEntries);
  $("#refresh-btn").addEventListener("click", () => refresh());

  window.addEventListener("popstate", () => {
    currentPath = getCurrentPath();
    fetchEntries();
  });

  document.addEventListener("keydown", (e) => {
    const inField = ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName);
    if (e.key === "Escape") {
      if (document.activeElement === searchInput) {
        searchInput.value = "";
        renderEntries();
        searchInput.blur();
      }
      return;
    }
    if (inField) return;
    if (e.key === "u" || e.key === "U") { e.preventDefault(); openPicker(); }
    if (e.key === "r" || e.key === "R") { e.preventDefault(); refresh(); }
    if (e.key === "/") { e.preventDefault(); searchInput.focus(); searchInput.select(); }
    if (e.key === "Backspace" && currentPath) {
      e.preventDefault();
      const parts = currentPath.split("/").filter(Boolean);
      parts.pop();
      setCurrentPath(parts.join("/"));
    }
  });

  const refresh = () => { fetchEntries(); fetchStats(); };

  currentPath = getCurrentPath();
  initMatrix();
  refresh();
  setInterval(fetchStats, 15000);
})();
