/* Standup page (standup story).
 *
 * Fills the page shell in tasks/templates/tasks/standup.html from ONE call to
 * GET /api/projects/<id>/standup/. Every section renders on its own: if one
 * comes back as {"error": ...} it shows the error and a Retry button, which
 * re-fetches just that section (?sections=<name>), and the others are untouched.
 *
 * No libraries. Elements are built with h() (never innerHTML), so task titles and
 * names are always text. Works in the browser (window.Standup) and in Node for the
 * component tests (module.exports), where each renderer gets a jsdom element.
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.Standup = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const REFRESH_MS = 60 * 1000;
  // Tiles where going up is bad news: their delta is red when it rises.
  const BAD_WHEN_UP = new Set(["blocked", "overdue", "bugs_created"]);

  // ---- Small helpers ----------------------------------------------------
  function maker(doc) {
    return function h(tag, attrs, ...children) {
      const el = doc.createElement(tag);
      for (const [key, value] of Object.entries(attrs || {})) {
        if (value === null || value === undefined || value === false) continue;
        if (key === "class") el.className = value;
        else if (key === "text") el.textContent = value;
        else if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
        else if (key === "dataset") Object.assign(el.dataset, value);
        else el.setAttribute(key, value === true ? "" : value);
      }
      for (const child of children.flat(Infinity)) {
        if (child === null || child === undefined || child === false) continue;
        el.append(child.nodeType ? child : doc.createTextNode(String(child)));
      }
      return el;
    };
  }

  function fill(container, ...children) {
    container.replaceChildren(...children.flat().filter(Boolean));
    return container;
  }

  function parseDay(iso) {  // "2026-10-23" as a local date (not UTC midnight)
    const [y, m, d] = iso.split("-").map(Number);
    return new Date(y, m - 1, d);
  }

  const fmt = {
    day: (iso) => iso ? parseDay(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" }) : "—",
    time: (iso) => new Date(iso).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" }),
    dateTime: (iso) => new Date(iso).toLocaleString("en-US", {
      weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }),
    delta: (n) => (n > 0 ? "+" + n : n < 0 ? "−" + Math.abs(n) : "no change"),
  };

  function renderEmpty(container, message) {
    const h = maker(container.ownerDocument);
    return fill(container, h("p", { class: "empty", text: message }));
  }

  function renderError(container, message, onRetry) {
    const h = maker(container.ownerDocument);
    return fill(container, h("div", { class: "sec-error msg msg-error", role: "alert" },
      h("span", { text: message || "This section couldn't be loaded." }),
      onRetry ? h("button", { type: "button", class: "retry", onclick: onRetry }, "Retry") : null));
  }

  function renderSkeleton(container) {
    const h = maker(container.ownerDocument);
    return fill(container, h("div", { class: "skeleton-lines", "aria-hidden": "true" },
      h("div", { class: "skeleton" }), h("div", { class: "skeleton" }),
      h("div", { class: "skeleton short" })));
  }

  // ---- Summary tiles (AC3) ------------------------------------------------
  function renderTiles(container, tiles, ctx = {}) {
    const h = maker(container.ownerDocument);
    if (!tiles || !tiles.length) return renderEmpty(container, "Nothing to summarise yet.");
    return fill(container, h("div", { class: "tiles" }, tiles.map((tile) => {
      const active = ctx.filterKey === tile.key;
      const direction = tile.delta > 0 ? "up" : tile.delta < 0 ? "down" : "same";
      return h("button", {
        type: "button", class: "tile" + (active ? " active" : ""), "aria-pressed": String(active),
        dataset: { key: tile.key },
        title: `${tile.previous} in the previous window. Click to filter the task list.`,
        onclick: () => ctx.onSelectTile && ctx.onSelectTile(tile),
      },
        h("div", { class: "label", text: tile.label }),
        h("div", { class: "count", text: String(tile.count) }),
        h("div", { class: `delta ${direction}${BAD_WHEN_UP.has(tile.key) ? " bad" : ""}`,
                   text: `${fmt.delta(tile.delta)} vs previous` }));
    })));
  }

  // ---- Task list, filtered by the selected tile ---------------------------
  function renderTaskList(container, tasks, ctx = {}) {
    const h = maker(container.ownerDocument);
    const filter = ctx.filter || null;
    if (!tasks || !tasks.length) return renderEmpty(container, "No tasks in this project yet.");
    const shown = filter ? tasks.filter((t) => filter.ids.has(t.id)) : tasks;
    const bar = filter && h("div", { class: "filter-bar" },
      h("span", {}, "Showing ", h("strong", { text: filter.label }), ` (${shown.length})`),
      h("button", { type: "button", class: "link clear-filter", style: "color: var(--accent)",
                    onclick: () => ctx.onClearFilter && ctx.onClearFilter() }, "Show all tasks"));
    if (!shown.length) {
      return fill(container, bar, h("p", { class: "empty", text: `No tasks match “${filter.label}”.` }));
    }
    const rows = shown.map((t) => h("tr", { dataset: { taskId: String(t.id) } },
      h("td", {}, t.title,
        t.kind === "bug" ? h("span", { class: "status status-critical flag", text: "Bug" }) : null,
        t.blocked ? h("span", { class: "status status-blocked flag", text: "Blocked" }) : null),
      h("td", {}, h("span", { class: `status status-${t.status}`, text: t.status_label })),
      h("td", { text: t.assignee || "—" }),
      h("td", { class: t.overdue ? "overdue" : null, style: t.overdue ? "color: var(--err-text)" : null },
        fmt.day(t.due), t.overdue ? " (overdue)" : ""),
      h("td", { text: t.is_critical ? "Critical" : "" })));
    return fill(container, bar, h("table", { class: "task-table" },
      h("thead", {}, h("tr", {}, ["Task", "Status", "Assignee", "Due", "Critical path"].map(
        (label) => h("th", { scope: "col", text: label })))),
      h("tbody", {}, rows)));
  }

  // Section name -> renderer(container, data, ctx). The other sections add themselves below.
  const RENDERERS = {
    tiles: (el, data, ctx) => renderTiles(el, data, ctx),
    tasks: (el, data, ctx) => renderTaskList(el, data, ctx),
  };

  // ---- The page -----------------------------------------------------------
  function start(root, options = {}) {
    const doc = root.ownerDocument;
    const win = doc.defaultView;
    const fetchFn = options.fetch || win.fetch.bind(win);
    const api = root.dataset.api;
    const form = root.querySelector("#window-form");
    const windowSelect = root.querySelector("#window-select");
    const customRange = root.querySelector("#custom-range");
    const windowError = root.querySelector("#window-error");
    const state = { data: {}, filter: null, loaded: false };

    const body = (name) => root.querySelector(`section[data-section="${name}"] .sec-body`);

    function windowParams() {
      const params = new URLSearchParams({ window: windowSelect.value });
      if (windowSelect.value === "custom") {
        params.set("from", form.elements.from.value);
        params.set("to", form.elements.to.value);
      }
      return params;
    }

    const ctx = {
      root, state,
      get filterKey() { return state.filter && state.filter.key; },
      get filter() { return state.filter; },
      onSelectTile(tile) {
        state.filter = state.filter && state.filter.key === tile.key ? null : tileFilter(tile);
        render("tiles");
        render("tasks");
        if (state.filter) {
          const list = root.querySelector('section[data-section="tasks"]');
          if (list && list.scrollIntoView) list.scrollIntoView({ behavior: "smooth", block: "start" });
        }
      },
      onClearFilter() { state.filter = null; render("tiles"); render("tasks"); },
      csrf: root.dataset.csrf,
      orderUrl: root.dataset.orderUrl,
      fetch: fetchFn,
    };

    function tileFilter(tile) {
      return { key: tile.key, label: tile.label, ids: new Set(tile.task_ids) };
    }

    function render(name) {
      const el = body(name);
      if (!el || !(name in state.data) || !RENDERERS[name]) return;
      const value = state.data[name];
      if (value && value.error) return renderError(el, value.error, () => retry(name));
      try {
        RENDERERS[name](el, value, ctx);
      } catch (err) {  // a rendering bug in one section mustn't stop the others
        if (win.console) win.console.error(err);
        renderError(el, "This section couldn't be shown.", () => retry(name));
      }
    }

    function retry(name) {
      const el = body(name);
      if (el) renderSkeleton(el);
      return load([name]);
    }

    async function load(only) {
      const params = windowParams();
      if (only) params.set("sections", only.join(","));
      let response, data;
      try {
        response = await fetchFn(`${api}?${params}`, {
          headers: { Accept: "application/json" }, credentials: "same-origin" });
        data = await response.json().catch(() => ({}));
      } catch (err) {
        return failed(only, "Couldn't reach the server. Check your connection and retry.");
      }
      if (response.status === 400) {  // a bad window: say why, keep what's on screen
        windowError.textContent = data.detail || Object.values(data).flat().join(" ") || "Check the dates.";
        windowError.hidden = false;
        return;
      }
      if (!response.ok) {
        return failed(only, response.status === 403
          ? "You're not a member of this project." : `The server had a problem (${response.status}).`);
      }
      windowError.hidden = true;
      apply(data);
    }

    function failed(only, message) {
      // On a background refresh keep the last good data; otherwise each section says why.
      const names = only || Array.from(root.querySelectorAll("section[data-section]"),
                                       (s) => s.dataset.section);
      for (const name of names) {
        if (!state.loaded || only) state.data[name] = { error: message };
        render(name);
      }
      if (state.loaded && !only) {
        root.querySelector("#last-updated").textContent += " · refresh failed";
      }
    }

    function apply(data) {
      root.querySelector("#window-label").textContent = data.window ? data.window.label : "";
      if (data.generated_at) {
        root.querySelector("#last-updated").textContent = `Last updated ${fmt.time(data.generated_at)}`;
      }
      for (const name of Object.keys(RENDERERS)) {
        if (name in data) state.data[name] = data[name];
      }
      // Keep the tile filter across refreshes, with the tile's new task list.
      if (state.filter && Array.isArray(state.data.tiles)) {
        const tile = state.data.tiles.find((t) => t.key === state.filter.key);
        state.filter = tile ? tileFilter(tile) : null;
      }
      state.loaded = true;
      for (const name of Object.keys(RENDERERS)) if (name in data) render(name);
    }

    function updateUrl() {
      win.history.replaceState(null, "", `${win.location.pathname}?${windowParams()}`);
    }

    // Window: presets load at once; a custom range waits for Apply.
    windowSelect.addEventListener("change", () => {
      customRange.hidden = windowSelect.value !== "custom";
      if (windowSelect.value === "custom") return;
      updateUrl();
      load();
    });
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      if (!form.elements.from.value || !form.elements.to.value) {
        windowError.textContent = "Pick both a start and an end date.";
        windowError.hidden = false;
        return;
      }
      updateUrl();
      load();
    });

    // Project selector: same window, other project.
    const projectSelect = root.querySelector("#project-select");
    if (projectSelect) {
      projectSelect.addEventListener("change", () => {
        const url = root.dataset.pageUrlTemplate.replace("/0/", `/${projectSelect.value}/`);
        win.location.assign(`${url}?${windowParams()}`);
      });
    }

    root.querySelector("#refresh").addEventListener("click", () => load());

    // Present mode: no nav, bigger text. Remembered on this device.
    const presentButton = root.querySelector("#present");
    function setPresent(on) {
      doc.body.classList.toggle("present", on);
      presentButton.setAttribute("aria-pressed", String(on));
      presentButton.textContent = on ? "Exit present" : "Present";
      try { win.localStorage.setItem("standup.present", on ? "1" : ""); } catch (e) { /* private mode */ }
    }
    presentButton.addEventListener("click", () => setPresent(!doc.body.classList.contains("present")));
    try { if (win.localStorage.getItem("standup.present")) setPresent(true); } catch (e) { /* ignore */ }

    const ready = load();
    const timer = options.autoRefresh === false ? null : win.setInterval(() => load(), REFRESH_MS);
    return { ready, load, ctx, stop: () => timer && win.clearInterval(timer) };
  }

  return { start, RENDERERS, renderTiles, renderTaskList, renderEmpty, renderError,
           renderSkeleton, maker, fill, fmt };
});
