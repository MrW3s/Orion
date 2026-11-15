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

  // ---- Activity timeline (AC4) --------------------------------------------
  const EVENT_STYLE = {  // kind -> icon; colours are the .kind-<kind> classes
    created: "+", in_progress: "▶", done: "✓", blocked: "!", unblocked: "↻",
    reassigned: "⇄", reopened: "↩", mixed: "•",
  };
  const TIP_LIMIT = 8;
  const ROWS = 3;  // markers closer than MIN_GAP% go on different rows...
  // ...and when every row is taken, the marker is nudged right of the closest one, so bunched
  // activity (e.g. all on Friday, in a Friday-to-Monday window) stays readable. The tooltip
  // always shows the exact time.

  function renderTimeline(container, timeline, ctx = {}) {
    const h = maker(container.ownerDocument);
    const legend = h("ul", { class: "legend", "aria-label": "Legend" },
      (timeline.legend || []).map((item) => h("li", {},
        h("span", { class: `swatch kind-${item.kind}`, "aria-hidden": "true", text: EVENT_STYLE[item.kind] }),
        item.label)));
    if (!timeline.markers || !timeline.markers.length) {
      return fill(container, h("p", { class: "empty", text: "No activity in this window." }), legend);
    }
    const start = Date.parse(timeline.start);
    const span = Math.max(Date.parse(timeline.end) - start, 1);
    const MIN_GAP = 2.5;
    const lastLeft = new Array(ROWS).fill(-Infinity);

    const markers = timeline.markers.map((marker) => {
      let left = Math.min(100, Math.max(0, ((Date.parse(marker.at) - start) / span) * 100));
      let row = lastLeft.findIndex((prev) => left - prev >= MIN_GAP);
      if (row === -1) {
        row = lastLeft.indexOf(Math.min(...lastLeft));
        left = Math.min(100, lastLeft[row] + MIN_GAP);
      }
      lastLeft[row] = left;
      const first = marker.events[0];
      const label = marker.count > 1
        ? `${marker.count} events around ${fmt.time(marker.at)}`
        : `${kindLabel(timeline, first.kind)}: ${first.task}, by ${first.person} at ${fmt.time(first.at)}`;
      const tip = h("div", { class: "marker-tip" + (left > 65 ? " to-left" : ""), role: "tooltip" },
        marker.events.slice(0, TIP_LIMIT).map((e) => h("div", {},
          h("span", { class: `swatch kind-${e.kind}`, "aria-hidden": "true", text: EVENT_STYLE[e.kind] }),
          h("span", {}, h("strong", { text: e.task }),
            h("br"), `${kindLabel(timeline, e.kind)} · ${e.person} · ${fmt.time(e.at)}`))),
        marker.count > TIP_LIMIT ? h("div", { class: "muted", text: `and ${marker.count - TIP_LIMIT} more` }) : null);
      return h("button", {
        type: "button", class: `marker kind-${marker.kind}`, "aria-label": label,
        style: `left: ${left}%; top: ${6 + row * 26}px`, dataset: { count: String(marker.count) },
      }, h("span", { "aria-hidden": "true", text: EVENT_STYLE[marker.kind] || "•" }),
         marker.count > 1 ? h("span", { class: "marker-count", text: String(marker.count) }) : null,
         tip);
    });

    const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => h("span", {
      class: "tick", style: `left: ${f * 100}%`,
      text: fmt.dateTime(new Date(start + f * span).toISOString()) }));
    const summary = `${timeline.event_count} event${timeline.event_count === 1 ? "" : "s"}` +
      (timeline.grouped ? ", grouped by hour" : "");
    return fill(container,
      h("p", { class: "small muted timeline-summary", text: summary }),
      h("div", { class: "timeline-track" }, h("div", { class: "axis" }), markers),
      h("div", { class: "ticks small muted" }, ticks),
      legend);
  }

  function kindLabel(timeline, kind) {
    const item = (timeline.legend || []).find((l) => l.kind === kind);
    return item ? item.label : kind;
  }

  // ---- Per-person cards (AC5) ----------------------------------------------
  function renderPeople(container, people, ctx = {}) {
    const h = maker(container.ownerDocument);
    if (!people || !people.length) return renderEmpty(container, "No team members on this project yet.");
    const ids = people.map((p) => p.user_id);
    const move = (from, to) => {
      if (to < 0 || to >= ids.length || from === to) return;
      const next = ids.slice();
      next.splice(to, 0, next.splice(from, 1)[0]);
      if (ctx.onReorder) ctx.onReorder(next);
    };
    let dragged = null;

    const list = (title, tasks, extra) => tasks.length ? h("div", { class: "person-list" },
      h("div", { class: "small muted", text: `${title} (${tasks.length})` }),
      h("ul", {}, tasks.map((t) => h("li", {}, t.title, extra ? extra(t) : null)))) : null;

    const cards = people.map((person, index) => {
      const body = person.active ? [
        list("Completed in window", person.completed),
        list("In progress now", person.in_progress),
        list("Blocked", person.blocked, (t) => h("div", { class: "small reason", text: t.reason })),
      ].filter(Boolean) : [];
      if (person.active && !body.length) {
        body.push(h("p", { class: "empty", text: "Active, but nothing completed, in progress or blocked." }));
      }
      if (!person.active) {
        body.push(h("p", { class: "empty", text: "No activity in window." }),
                  list("In progress now", person.in_progress),
                  list("Blocked", person.blocked, (t) => h("div", { class: "small reason", text: t.reason })));
      }
      const card = h("li", {
        class: "person" + (ctx.speaker === person.user_id ? " speaking" : "") + (person.active ? "" : " idle"),
        draggable: "true", dataset: { userId: String(person.user_id) },
        "aria-current": ctx.speaker === person.user_id ? "true" : null,
        ondragstart: (e) => { dragged = index; e.dataTransfer.effectAllowed = "move";
                              e.dataTransfer.setData("text/plain", String(person.user_id)); },
        ondragover: (e) => { e.preventDefault(); card.classList.add("drop-target"); },
        ondragleave: () => card.classList.remove("drop-target"),
        ondrop: (e) => { e.preventDefault(); card.classList.remove("drop-target");
                         if (dragged !== null) move(dragged, index); dragged = null; },
      },
        h("div", { class: "person-head" },
          h("span", { class: "grip", "aria-hidden": "true", text: "⋮⋮" }),
          h("strong", { text: person.name }),
          h("span", { class: "order-buttons" },
            h("button", { type: "button", class: "link", "aria-label": `Move ${person.name} up`,
                          disabled: index === 0, onclick: () => move(index, index - 1) }, "↑"),
            h("button", { type: "button", class: "link", "aria-label": `Move ${person.name} down`,
                          disabled: index === people.length - 1, onclick: () => move(index, index + 1) }, "↓"))),
        body);
      return card;
    });
    return fill(container, h("ol", { class: "people" }, cards));
  }

  // ---- Schedule health (AC6) ------------------------------------------------
  function renderHealth(container, health, ctx = {}) {
    const h = maker(container.ownerDocument);
    const move = (t) => `${fmt.day(t.from)} → ${fmt.day(t.to)} (${t.days > 0 ? "+" : ""}${t.days} day${Math.abs(t.days) === 1 ? "" : "s"})`;
    const forecast = health.forecast || {};
    const forecastBox = forecast.available
      ? h("div", { class: "forecast" }, `On-time probability: ${Math.round(forecast.probability * 100)}%`)
      : h("div", { class: "forecast muted small" }, h("strong", { text: "On-time forecast: not available. " }),
          forecast.reason || "");
    if (!health.critical_path || !health.critical_path.length) {
      return fill(container, h("p", { class: "empty", text: "No tasks scheduled yet, so there's no critical path." }),
                  forecastBox);
    }
    return fill(container,
      h("p", {}, "Projected end: ", h("strong", { text: fmt.day(health.project_end) })),
      h("h3", { text: "Critical path" }),
      h("table", { class: "task-table critical-path" },
        h("thead", {}, h("tr", {}, ["Task", "Due", "Status"].map((l) => h("th", { scope: "col", text: l })))),
        h("tbody", {}, health.critical_path.map((t) => h("tr", { class: t.slipped ? "slipped" : null },
          h("td", {}, t.title, t.slipped ? h("span", { class: "status status-critical flag", text: "Slipped" }) : null),
          h("td", { text: fmt.day(t.due) }),
          h("td", { text: STATUS_LABEL[t.status] || t.status }))))),
      h("h3", { text: "Slipped in this window" }),
      health.slipped.length
        ? h("ul", { class: "slips" }, health.slipped.map((t) => h("li", {}, h("strong", { text: t.title }), ": ", move(t))))
        : h("p", { class: "empty", text: "No critical-path task slipped in this window." }),
      health.downstream_moved.length ? [
        h("h3", { text: "Moved downstream" }),
        h("ul", { class: "downstream" }, health.downstream_moved.map((t) => h("li", {},
          h("strong", { text: t.title }), ": ", move(t),
          h("span", { class: "small muted", text: ` because ${t.because_of.join(", ")} slipped` })))),
      ] : null,
      forecastBox);
  }
  const STATUS_LABEL = { todo: "Not started", in_progress: "In progress", complete: "Complete" };

  // ---- Blockers (AC7) ---------------------------------------------------------
  function renderBlockers(container, blockers, ctx = {}) {
    const h = maker(container.ownerDocument);
    if (!blockers || !blockers.length) return renderEmpty(container, "Nothing is blocked.");
    return fill(container, h("ul", { class: "blockers" }, blockers.map((b) => h("li", {
      class: "blocker" + (b.stale ? " stale" : ""), dataset: { taskId: String(b.id) } },
      h("div", { class: "blocker-head" },
        h("strong", { text: b.title }),
        h("span", { class: "days", text: `${b.days_blocked} working day${b.days_blocked === 1 ? "" : "s"}` })),
      h("div", { class: "small" }, `${b.owner || "Unassigned"} · since ${fmt.dateTime(b.since)}`),
      b.reason ? h("div", { class: "small reason", text: b.reason }) : null,
      b.stale ? h("div", { class: "small stale-note", text: "Blocked for more than 2 working days" }) : null))));
  }

  // Section name -> renderer(container, data, ctx). The other sections add themselves below.
  const RENDERERS = {
    tiles: (el, data, ctx) => renderTiles(el, data, ctx),
    tasks: (el, data, ctx) => renderTaskList(el, data, ctx),
    timeline: (el, data, ctx) => renderTimeline(el, data, ctx),
    people: (el, data, ctx) => renderPeople(el, data, ctx),
    schedule_health: (el, data, ctx) => renderHealth(el, data, ctx),
    blockers: (el, data, ctx) => renderBlockers(el, data, ctx),
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
    const state = { data: {}, filter: null, loaded: false, speaker: null };

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
      get speaker() { return state.speaker; },
      onReorder: (ids) => saveOrder(ids),
    };

    // ---- Speaking order -------------------------------------------------
    async function saveOrder(ids) {
      const before = state.data.people;
      const byId = new Map(before.map((p) => [p.user_id, p]));
      state.data.people = ids.map((id) => byId.get(id));
      render("people");
      try {
        const response = await fetchFn(root.dataset.orderUrl, {
          method: "PUT", credentials: "same-origin",
          headers: { "Content-Type": "application/json", Accept: "application/json",
                     "X-CSRFToken": root.dataset.csrf },
          body: JSON.stringify({ user_ids: ids }),
        });
        if (!response.ok) throw new Error(String(response.status));
      } catch (err) {
        state.data.people = before;
        render("people");
        const el = body("people");
        if (el) el.prepend(maker(doc)("div", { class: "msg msg-error", role: "alert",
                                               text: "The new order wasn't saved. Try again." }));
      }
    }

    function nextSpeaker() {
      const people = Array.isArray(state.data.people) ? state.data.people : [];
      if (!people.length) return;
      const at = people.findIndex((p) => p.user_id === state.speaker);
      state.speaker = people[(at + 1) % people.length].user_id;
      render("people");
      const card = root.querySelector(`.person[data-user-id="${state.speaker}"]`);
      if (card && card.scrollIntoView) card.scrollIntoView({ behavior: "smooth", block: "center" });
    }
    const nextButton = root.querySelector("#next-speaker");
    if (nextButton) nextButton.addEventListener("click", nextSpeaker);

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
    return { ready, load, ctx, nextSpeaker, stop: () => timer && win.clearInterval(timer) };
  }

  return { start, RENDERERS, renderTiles, renderTaskList, renderTimeline, renderPeople, renderHealth, renderBlockers, renderEmpty, renderError,
           renderSkeleton, maker, fill, fmt };
});
