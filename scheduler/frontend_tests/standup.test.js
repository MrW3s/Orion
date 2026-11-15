// Component tests for tasks/static/tasks/standup.js (standup story, AC11).
// Run from scheduler/: npm test   (Node's built-in runner + jsdom, no other libraries)
const { test, describe } = require("node:test");
const assert = require("node:assert/strict");
const { JSDOM } = require("jsdom");
const Standup = require("../tasks/static/tasks/standup.js");

function container() {
  return new JSDOM("<!doctype html><div id=c></div>").window.document.getElementById("c");
}
const texts = (el, sel) => Array.from(el.querySelectorAll(sel), (n) => n.textContent.trim());

const TILES = [
  { key: "completed", label: "Tasks completed", count: 2, previous: 1, delta: 1, task_ids: [1, 2] },
  { key: "in_progress", label: "Moved to In progress", count: 1, previous: 1, delta: 0, task_ids: [3] },
  { key: "blocked", label: "Currently blocked", count: 1, previous: 2, delta: -1, task_ids: [3] },
  { key: "active_members", label: "Active members", count: 2, previous: 1, delta: 1, task_ids: [1, 3] },
  { key: "overdue", label: "Overdue", count: 1, previous: 0, delta: 1, task_ids: [4] },
  { key: "bugs_created", label: "Bugs created", count: 0, previous: 0, delta: 0, task_ids: [] },
];
const TASKS = [
  { id: 1, title: "Design", kind: "task", status: "complete", status_label: "Complete", assignee: "alice",
    due: "2026-11-02", is_critical: true, blocked: false, overdue: false },
  { id: 2, title: "Docs", kind: "task", status: "complete", status_label: "Complete", assignee: null,
    due: "2026-11-03", is_critical: false, blocked: false, overdue: false },
  { id: 3, title: "API", kind: "task", status: "in_progress", status_label: "In progress", assignee: "bob",
    due: "2026-11-05", is_critical: true, blocked: true, overdue: false },
  { id: 4, title: "Crash", kind: "bug", status: "todo", status_label: "Not started", assignee: "bob",
    due: "2026-11-01", is_critical: false, blocked: false, overdue: true },
];
const LEGEND = ["created", "in_progress", "done", "blocked", "unblocked", "reassigned", "reopened"]
  .map((kind) => ({ kind, label: kind }));
const event = (at, kind, task = "Design", person = "alice") => ({ at, kind, task, person, task_id: 1 });

describe("summary tiles", () => {
  test("show count and change against the previous window", () => {
    const el = Standup.renderTiles(container(), TILES);
    assert.equal(el.querySelectorAll(".tile").length, 6);
    assert.deepEqual(texts(el, ".tile .count"), ["2", "1", "1", "2", "1", "0"]);
    assert.equal(el.querySelector('[data-key="completed"] .delta').textContent, "+1 vs previous");
    assert.equal(el.querySelector('[data-key="blocked"] .delta').textContent, "−1 vs previous");
    assert.equal(el.querySelector('[data-key="in_progress"] .delta').textContent, "no change vs previous");
    // Rising blockers and overdue tasks are bad news, so they're marked as such
    assert.ok(el.querySelector('[data-key="overdue"] .delta').classList.contains("bad"));
  });

  test("clicking a tile selects it", () => {
    const picked = [];
    const el = Standup.renderTiles(container(), TILES, { onSelectTile: (t) => picked.push(t.key) });
    el.querySelector('[data-key="overdue"]').click();
    assert.deepEqual(picked, ["overdue"]);
    const active = Standup.renderTiles(container(), TILES, { filterKey: "overdue" });
    assert.equal(active.querySelector(".tile.active").dataset.key, "overdue");
    assert.equal(active.querySelector(".tile.active").getAttribute("aria-pressed"), "true");
  });

  test("empty state", () => {
    assert.match(Standup.renderTiles(container(), []).textContent, /Nothing to summarise/);
  });
});

describe("task list", () => {
  test("a tile filter shows only its tasks, and can be cleared", () => {
    let cleared = false;
    const el = Standup.renderTaskList(container(), TASKS, {
      filter: { key: "completed", label: "Tasks completed", ids: new Set([1, 2]) },
      onClearFilter: () => { cleared = true; },
    });
    assert.deepEqual(Array.from(el.querySelectorAll("tbody tr"), (r) => r.dataset.taskId), ["1", "2"]);
    assert.match(el.querySelector(".filter-bar").textContent, /Tasks completed \(2\)/);
    el.querySelector(".clear-filter").click();
    assert.ok(cleared);
  });

  test("flags bugs, blocked and overdue tasks", () => {
    const el = Standup.renderTaskList(container(), TASKS);
    const crash = el.querySelector('[data-task-id="4"]');
    assert.match(crash.textContent, /Bug/);
    assert.match(crash.textContent, /\(overdue\)/);
    assert.match(el.querySelector('[data-task-id="3"]').textContent, /Blocked/);
  });

  test("empty states", () => {
    assert.match(Standup.renderTaskList(container(), []).textContent, /No tasks in this project yet/);
    const none = Standup.renderTaskList(container(), TASKS,
      { filter: { key: "bugs_created", label: "Bugs created", ids: new Set() } });
    assert.match(none.textContent, /No tasks match “Bugs created”/);
  });

  test("titles are text, never HTML", () => {
    const el = Standup.renderTaskList(container(), [{ ...TASKS[0], title: '<img src=x onerror="alert(1)">' }]);
    assert.equal(el.querySelector("img"), null);
    assert.match(el.textContent, /<img src=x/);
  });
});

describe("activity timeline", () => {
  const window_ = { start: "2026-11-10T05:00:00Z", end: "2026-11-11T15:00:00Z", legend: LEGEND };

  test("one marker per event, with a legend and hover details", () => {
    const el = Standup.renderTimeline(container(), { ...window_, event_count: 2, grouped: false, markers: [
      { at: "2026-11-10T14:00:00Z", kind: "done", count: 1, events: [event("2026-11-10T14:00:00Z", "done")] },
      { at: "2026-11-11T13:00:00Z", kind: "blocked", count: 1,
        events: [event("2026-11-11T13:00:00Z", "blocked", "API", "bob")] },
    ] });
    const markers = el.querySelectorAll(".marker");
    assert.equal(markers.length, 2);
    assert.ok(markers[0].classList.contains("kind-done"));
    assert.equal(markers[0].querySelector(".marker-count"), null);
    assert.match(markers[1].getAttribute("aria-label"), /^blocked: API, by bob at /);
    assert.match(markers[1].querySelector(".marker-tip").textContent, /API.*bob/);
    assert.equal(el.querySelectorAll(".legend li").length, 7);
  });

  test("grouped markers show how many events they hold", () => {
    const many = Array.from({ length: 12 }, (_, i) => event("2026-11-10T14:00:00Z", i % 2 ? "done" : "created"));
    const el = Standup.renderTimeline(container(), { ...window_, event_count: 31, grouped: true, markers: [
      { at: "2026-11-10T14:00:00Z", kind: "mixed", count: 12, events: many },
      { at: "2026-11-10T15:00:00Z", kind: "done", count: 19,
        events: Array.from({ length: 19 }, () => event("2026-11-10T15:10:00Z", "done")) },
    ] });
    assert.deepEqual(texts(el, ".marker-count"), ["12", "19"]);
    assert.match(el.querySelector(".timeline-summary").textContent, /31 events, grouped by hour/);
    // A big group lists the first few and says how many more
    assert.match(el.querySelectorAll(".marker-tip")[1].textContent, /and 11 more/);
  });

  test("markers stay inside the track", () => {
    const el = Standup.renderTimeline(container(), { ...window_, event_count: 1, grouped: true, markers: [
      { at: "2026-11-10T04:00:00Z", kind: "done", count: 1, events: [event("2026-11-10T04:30:00Z", "done")] }] });
    assert.equal(el.querySelector(".marker").style.left, "0%");
  });

  test("empty state still shows the legend", () => {
    const el = Standup.renderTimeline(container(), { ...window_, event_count: 0, grouped: false, markers: [] });
    assert.match(el.textContent, /No activity in this window/);
    assert.equal(el.querySelectorAll(".legend li").length, 7);
  });
});

describe("person cards, schedule health and blockers", () => {
  const PEOPLE = [
    { user_id: 1, name: "alice", active: true, completed: [{ id: 1, title: "Design" }], in_progress: [], blocked: [] },
    { user_id: 2, name: "bob", active: true, completed: [], in_progress: [{ id: 3, title: "API" }],
      blocked: [{ id: 3, title: "API", reason: "Waiting for keys" }] },
    { user_id: 3, name: "sam", active: false, completed: [], in_progress: [], blocked: [] },
  ];

  test("cards show the window's work, blockers with reasons, and no-activity members", () => {
    const el = Standup.renderPeople(container(), PEOPLE, { speaker: 2 });
    assert.deepEqual(texts(el, ".person strong"), ["alice", "bob", "sam"]);
    assert.match(el.querySelector('[data-user-id="2"]').textContent, /Waiting for keys/);
    assert.match(el.querySelector('[data-user-id="3"]').textContent, /No activity in window\./);
    assert.ok(el.querySelector('[data-user-id="2"]').classList.contains("speaking"));
  });

  test("moving a card reports the new order", () => {
    const orders = [];
    const el = Standup.renderPeople(container(), PEOPLE, { onReorder: (ids) => orders.push(ids) });
    el.querySelector('[aria-label="Move sam up"]').click();
    assert.deepEqual(orders, [[1, 3, 2]]);
    assert.ok(el.querySelector('[aria-label="Move alice up"]').disabled);
  });

  test("blockers: oldest first as given, stale ones highlighted", () => {
    const el = Standup.renderBlockers(container(), [
      { id: 3, title: "API", owner: "bob", reason: "Keys", since: "2026-11-06T14:00:00Z", days_blocked: 3, stale: true },
      { id: 5, title: "Push", owner: null, reason: "", since: "2026-11-10T14:00:00Z", days_blocked: 1, stale: false },
    ]);
    assert.deepEqual(texts(el, ".blocker-head strong"), ["API", "Push"]);
    assert.ok(el.querySelector('[data-task-id="3"]').classList.contains("stale"));
    assert.match(el.querySelector('[data-task-id="3"]').textContent, /3 working days/);
    assert.match(el.querySelector('[data-task-id="5"]').textContent, /Unassigned/);
  });

  test("empty states", () => {
    assert.match(Standup.renderPeople(container(), []).textContent, /No team members/);
    assert.match(Standup.renderBlockers(container(), []).textContent, /Nothing is blocked/);
    const health = Standup.renderHealth(container(), { critical_path: [], slipped: [], downstream_moved: [],
      forecast: { available: false, reason: "Not built yet." } });
    assert.match(health.textContent, /no critical path/);
    assert.match(health.textContent, /On-time forecast: not available/);
  });

  test("schedule health flags slips and downstream moves", () => {
    const el = Standup.renderHealth(container(), {
      project_end: "2026-11-16",
      critical_path: [{ id: 1, title: "Design", due: "2026-11-05", status: "in_progress", slipped: true }],
      slipped: [{ id: 1, title: "Design", from: "2026-11-02", to: "2026-11-05", days: 3 }],
      downstream_moved: [{ id: 2, title: "Docs", from: "2026-11-03", to: "2026-11-06", days: 3, because_of: ["Design"] }],
      forecast: { available: false, reason: "" },
    });
    assert.ok(el.querySelector(".critical-path tr.slipped"));
    assert.match(el.querySelector(".slips").textContent, /Design: Nov 2 → Nov 5 \(\+3 days\)/);
    assert.match(el.querySelector(".downstream").textContent, /because Design slipped/);
  });
});

describe("error states", () => {
  test("an error with a Retry button", () => {
    let retried = 0;
    const el = Standup.renderError(container(), "Boom", () => retried++);
    assert.equal(el.querySelector("[role=alert] span").textContent, "Boom");
    el.querySelector("button.retry").click();
    assert.equal(retried, 1);
  });
});

// ---- The page: one failing section, retry, tile filter, window errors ----------
const PAGE = `<!doctype html><body><div id="standup" data-api="/api/projects/1/standup/"
  data-order-url="/api/projects/1/standup/order/" data-page-url-template="/projects/0/standup/" data-csrf="t">
  <select id="project-select"><option value="1" selected>A</option><option value="2">B</option></select>
  <form id="window-form"><select id="window-select" name="window">
    <option value="since_last" selected>Since</option><option value="today">Today</option>
    <option value="custom">Custom</option></select>
    <span id="custom-range" hidden><input name="from"><input name="to"><button type="submit">Apply</button></span>
    <span id="window-label"></span><span id="last-updated"></span>
    <button type="button" id="refresh">Refresh</button><button type="button" id="present">Present</button></form>
  <div id="window-error" hidden></div>
  ${["tiles", "timeline", "people", "blockers", "schedule_health", "tasks"].map((s) =>
    `<section data-section="${s}"><div class="sec-body">loading</div></section>`).join("")}
  <button id="next-speaker">Next</button></div></body>`;

function page(responder) {
  const dom = new JSDOM(PAGE, { url: "http://localhost/projects/1/standup/" });
  const calls = [];
  const fetch = async (url, init = {}) => {
    calls.push({ url, init });
    const [status, body] = responder(url, init, calls.length);
    return { ok: status < 400, status, json: async () => body };
  };
  const root = dom.window.document.getElementById("standup");
  const app = Standup.start(root, { fetch, autoRefresh: false });
  const section = (name) => root.querySelector(`section[data-section="${name}"] .sec-body`);
  return { dom, root, app, calls, section };
}

const FULL = {
  window: { key: "since_last", label: "Since Tue, Nov 10" }, generated_at: "2026-11-11T15:00:00Z",
  tiles: TILES, tasks: TASKS, timeline: { error: "This section couldn't be loaded." },
  people: [], blockers: [], schedule_health: { critical_path: [], slipped: [], downstream_moved: [], forecast: {} },
};

describe("standup page", () => {
  test("one failing section shows an error and retries alone; the rest render", async () => {
    const p = page((url, init, n) => n === 1 ? [200, FULL]
      : [200, { timeline: { start: "2026-11-10T05:00:00Z", end: "2026-11-11T15:00:00Z", legend: LEGEND,
                            event_count: 0, grouped: false, markers: [] } }]);
    await p.app.ready;
    assert.match(p.section("timeline").textContent, /couldn't be loaded/);
    assert.equal(p.section("tiles").querySelectorAll(".tile").length, 6);
    assert.match(p.root.querySelector("#last-updated").textContent, /^Last updated/);
    p.section("timeline").querySelector("button.retry").click();
    await new Promise((r) => setTimeout(r, 0));
    assert.match(p.calls[1].url, /sections=timeline/);
    assert.match(p.section("timeline").textContent, /No activity in this window/);
    assert.equal(p.section("tiles").querySelectorAll(".tile").length, 6);
  });

  test("a network failure shows an error in every section", async () => {
    const dom = new JSDOM(PAGE, { url: "http://localhost/projects/1/standup/" });
    const root = dom.window.document.getElementById("standup");
    const app = Standup.start(root, { fetch: async () => { throw new Error("offline"); }, autoRefresh: false });
    await app.ready;
    for (const s of root.querySelectorAll("section[data-section]")) {
      assert.match(s.textContent, /Couldn't reach the server/);
      assert.ok(s.querySelector("button.retry"));
    }
  });

  test("clicking a tile filters the task list; clicking again clears it", async () => {
    const p = page(() => [200, FULL]);
    await p.app.ready;
    p.section("tiles").querySelector('[data-key="overdue"]').click();
    assert.deepEqual(Array.from(p.section("tasks").querySelectorAll("tbody tr"), (r) => r.dataset.taskId), ["4"]);
    p.section("tiles").querySelector('[data-key="overdue"]').click();
    assert.equal(p.section("tasks").querySelectorAll("tbody tr").length, 4);
  });

  test("changing the window updates the URL and reloads", async () => {
    const p = page(() => [200, FULL]);
    await p.app.ready;
    const select = p.root.querySelector("#window-select");
    select.value = "today";
    select.dispatchEvent(new p.dom.window.Event("change"));
    await new Promise((r) => setTimeout(r, 0));
    assert.equal(p.dom.window.location.search, "?window=today");
    assert.match(p.calls.at(-1).url, /window=today/);
  });

  test("a bad custom range says why and keeps the page", async () => {
    const p = page((url, init, n) => n === 1 ? [200, FULL]
      : [400, { error: "InvalidWindow", detail: "The end date can't be before the start date" }]);
    await p.app.ready;
    const form = p.root.querySelector("#window-form");
    p.root.querySelector("#window-select").value = "custom";
    form.elements.from.value = "2026-11-06";
    form.elements.to.value = "2026-11-02";
    form.dispatchEvent(new p.dom.window.Event("submit", { cancelable: true }));
    await new Promise((r) => setTimeout(r, 0));
    const error = p.root.querySelector("#window-error");
    assert.equal(error.hidden, false);
    assert.match(error.textContent, /end date can't be before/);
    assert.equal(p.section("tiles").querySelectorAll(".tile").length, 6);
  });

  test("next speaker cycles through the cards", async () => {
    const people = [{ user_id: 1, name: "alice", active: false, completed: [], in_progress: [], blocked: [] },
                    { user_id: 2, name: "bob", active: false, completed: [], in_progress: [], blocked: [] }];
    const p = page(() => [200, { ...FULL, people }]);
    await p.app.ready;
    const next = p.root.querySelector("#next-speaker");
    next.click();
    assert.equal(p.section("people").querySelector(".speaking").dataset.userId, "1");
    next.click();
    next.click();
    assert.equal(p.section("people").querySelector(".speaking").dataset.userId, "1");
  });

  test("reordering saves with the CSRF token, and rolls back if it fails", async () => {
    const people = [{ user_id: 1, name: "alice", active: false, completed: [], in_progress: [], blocked: [] },
                    { user_id: 2, name: "bob", active: false, completed: [], in_progress: [], blocked: [] }];
    const p = page((url, init) => init.method === "PUT" ? [500, {}] : [200, { ...FULL, people }]);
    await p.app.ready;
    p.section("people").querySelector('[aria-label="Move bob up"]').click();
    await new Promise((r) => setTimeout(r, 0));
    const put = p.calls.find((c) => c.init.method === "PUT");
    assert.equal(put.init.headers["X-CSRFToken"], "t");
    assert.deepEqual(JSON.parse(put.init.body), { user_ids: [2, 1] });
    assert.deepEqual(texts(p.section("people"), ".person strong"), ["alice", "bob"]);
    assert.match(p.section("people").textContent, /wasn't saved/);
  });
});
