# Sprint 1 Architecture: Task Scheduling Backend

Stack: **React** (frontend, not in this repo) · **Django + Django REST Framework** (backend) ·
**SQLite** (database) · **Django Channels** (WebSockets for real-time updates).

## 1. Architecture style

A **client-server** system using a **thin client**:

| Layer | Where | In this repo |
|---|---|---|
| Presentation | React in the browser | (not included); talks to the REST API and the WebSocket. For now there are simple Django-rendered pages: `accounts/templates/` (story 4) and `tasks/templates/` (schedule and Gantt chart) |
| Application processing | Django server | `tasks/services.py`, `scheduling/` |
| Data management | Django server + SQLite | `*/models.py`, `tasks/repository.py` |

Inside the server the code follows **MVC**:

* **Model:** Django models (`Project`, `Task`, `GanttReport`) plus the scheduling engine
* **View:** the React screens (the JSON from `serializers.py` is what they display)
* **Controller:** `tasks/views.py` (REST) and `notifications/consumers.py` (WebSocket)

Requests flow one way: **controller → service → (repository | engine | access | publisher)**.

## 2. Modules

| Module | Single responsibility (cohesion) | Hides this design decision (information hiding) |
|---|---|---|
| `scheduling/` | Given tasks and dependencies, work out the schedule (graph, cycle detection, ordering, dates, slack, critical path) | The scheduling algorithm. **Imports nothing from Django** |
| `tasks/` | The task use cases (stories 1 & 2, PM story, Gantt story) and their API and pages | How tasks are stored and which concrete collaborators are used |
| `accounts/` | Users' roles and the pages for managing them (story 4) | Which role may use which feature (`ROLE_FEATURES` in `services.py`) |
| `projects/` | Projects, who belongs to them (members, owner), creating them, client notes | The membership and ownership rules (`access.py`) |
| `clients/` | The client's view-only dashboard: progress, and notes for the team | Which project details a client may see (`ClientProject` / `ClientTask` in `services.py`) |
| `notifications/` | Telling connected members that something changed | The real-time transport (Channels/WebSockets) |
| `common/` | Shared domain errors and their HTTP mapping | Mapping from business errors to HTTP status codes |
| `config/` | Settings, URL routing, ASGI entry point | Deployment details |

### Inside `tasks/`, each file has one job

| File | Job | Knows about HTTP? | Knows about the ORM? |
|---|---|---|---|
| `views.py` | Parse request → call one service method → return JSON | yes | no |
| `serializers.py` | JSON shape validation | yes | read-only |
| `services.py` | Business rules for the stories | **no** | **no** (goes through the repository) |
| `repository.py` | All task queries | no | yes |
| `pages.py` | Server-rendered schedule and Gantt pages: call the service, render a template | yes | no |
| `forms.py` | HTML form shape validation (add task, edit dependencies, Gantt report) | yes | no |
| `gantt.py` | Turns task dates into bar positions on the Gantt timeline (pure date math) | no | no |
| `container.py` | Wires concrete classes into `TaskService` | no | no |
| `models.py` | Task and GanttReport tables + `TaskStatus` | no | yes |

## 3. Dependencies (coupling)

```
            config
              │
           clients ──────────────────────────────┐
              │                                  │
              ▼                                  ▼
            tasks ─────────────┬──────────────┬─────────────┐
              │                │              │             │
              ▼                ▼              ▼             ▼
         scheduling      notifications ──► projects ──► common
         (pure Python)
```

* **`clients` → `tasks`, `projects`:** the dashboard reads tasks through `TaskRepository` and
  checks ownership through `ProjectAccess`. Nothing imports `clients`; the schedule page only
  redirects to its URL by name, so there's no cycle.

* **No cycles** between modules (checked: `scheduling` and `common` import nothing from the others).
* **`projects` → `accounts` and `tasks` → `accounts`:** creating a project asks
  `RoleService.can(user, "create_projects")`, the PM risk view asks `can(user, "view_risk")`, and
  the Gantt chart and its reports ask `can(user, "view_gantt" / "report_gantt" / "review_gantt_reports")`.
  `accounts` imports nothing from `projects` or `tasks`, so roles stay at the bottom with `common`.
* **`tasks` → `scheduling`: data coupling only.** The service passes plain `TaskNode` values
  and gets a plain `ScheduleResult` back. The engine never sees a Django model, so it can be
  unit-tested without a database and swapped or extended on its own.
* **`TaskService` receives its collaborators** (repository, scheduler, access, publisher, roles)
  through its constructor instead of creating them. Tests pass an `InMemoryPublisher`;
  production uses `ChannelsPublisher`. Neither change touches `services.py`.
* **The services depend on the `EventPublisher` interface**, not on Channels. If the team
  later swaps WebSockets for polling or Server-Sent Events, only `notifications/` changes.
* **Errors cross layers as domain exceptions** (`common/errors.py`). Only `common/api.py`
  turns them into 400/403/404, so the business logic never mentions HTTP.

## 4. How each story flows

**Story 1: add a task to the schedule**
`POST /api/projects/{id}/tasks/` → `views.ProjectTasksView.post` → `TaskService.add_task`
1. Check the user is a project member (`ProjectAccess`; clients never are).
2. Check the task has a name and valid dates (end ≥ start, start ≥ project start). The duration
   estimate is the number of days from start to end, both included.
3. Check the assignee (if any) is a member who isn't a client, and dependencies belong to the same project.
4. In one transaction: create the task → `_reschedule()` rebuilds the dependency graph →
   `Scheduler.compute()` → repository saves the new dates. A cycle rolls everything back.
5. After commit: publish `schedule.changed` to `project_{id}`; the clients re-fetch.

**Story 2: update status from the schedule view**
`PATCH /api/tasks/{id}/status/` → `views.TaskStatusView.patch` → `TaskService.update_status`
1. Check membership; skip if the status didn't actually change.
2. Save the status.
3. After commit: publish `task.status_changed`. Every member with `ws/projects/{id}/`
   open receives it immediately; outsiders can't connect (closed with code 4403).

## 5. Data requirements (Sprint 1)

| Entity | Fields | Rules |
|---|---|---|
| **User** | Django built-in (`username`, `password`, …) | |
| **Profile** | `user` (1:1 → User), `role` (`team_member` / `project_manager` / `admin` / `client`) | No profile means team member; superusers are always admins |
| **Project** | `name`, `start_date`, `members` (M:N → User), `owner` (FK User, optional) | Only members can view/change its tasks; members need `view_schedule`, so clients never count as members. The owner is a client, set by an admin |
| **ClientNote** | `project` (FK), `author` (FK User), `text`, `created_at` | Only the project's owner can leave one; the project's members see them |
| **Task** | `project` (FK), `title`, `description`, `assignee` (FK User, optional), `created_by`, `planned_start` (the start date the user picked), `duration_days` (≥ 1), `status` (`todo` = "Not started" / `in_progress` / `complete`), `depends_on` (M:N → Task), `scheduled_start`, `scheduled_end`, timestamps | Dependencies must be in the same project and form no cycle; assignee must be a member; scheduled dates are written by the engine only, never earlier than `planned_start` |
| **GanttReport** | `project` (FK), `reporter` (FK User), `message`, `created_at`, `resolved_by` (FK User, optional), `resolved_at` | Message required, at most 1000 characters; open while `resolved_at` is empty |

Relationships: Project 1─* Task · Project *─* User (members) · Project *─1 User (owner) ·
Project 1─* ClientNote · Project 1─* GanttReport · Task *─* Task (dependency).

## 6. PM story: dependency graph, cycles, ordering, critical path

> *As a project manager, I want the system to build a dependency graph … cycle detection,
> task ordering, and the critical path … to identify scheduling risks.*

Every time a task or a dependency is committed, `TaskService._reschedule()` runs the engine once:

| Piece | Where | What it does |
|---|---|---|
| Dependency graph | `scheduling/graph.py` | `DependencyGraph`, built by `Scheduler._build_graph()` |
| Cycle detection | `graph.py` `topological_order()` | Raises `CycleError` whose `nodes` are **only the loop** (`_find_cycle()`), not tasks downstream of it |
| Task ordering | `graph.py` (Kahn's algorithm) | `ScheduleResult.order` |
| Earliest start/finish | `scheduling/scheduler.py` | CPM forward pass |
| Latest start/finish, slack | `scheduling/critical_path.py` | CPM backward pass; slack 0 ⇒ critical |
| Critical path | `scheduler.py` | `ScheduleResult.critical_path`: the critical tasks in dependency order |

**Storage:** `Task.slack_days` and `Task.is_critical` are written by `TaskRepository.save_schedule()`,
next to the scheduled dates (migration `0003`).

**Cycles are rejected, not stored.** A change that creates a cycle raises `InvalidDependency`
inside the transaction, so it rolls back: the dependency isn't saved, the last valid dates and
critical path stay, and no `schedule.changed` event goes out. The error names the loop by task
title (e.g. *Circular dependency: Design → API → Design*). Because saved data can never contain a
cycle, ordering and critical path are never calculated on a looping schedule.

**Flow (risk view):** `GET /api/projects/{id}/risk/` → `views.ProjectRiskView` → `TaskService.risk_report`
1. Check membership, then `RoleService.can(user, "view_risk")` (project managers and admins), else `NotAllowed` (403).
2. Run the engine on the saved tasks and return the ordering, critical path and project end.

**Flow (change dependencies):** `PUT /api/tasks/{id}/dependencies/` → `views.TaskDependenciesView` →
`TaskService.set_dependencies`: same checks as story 1, then the same transaction-and-reschedule
path, so a cycle is rejected as above.

The schedule page (`/projects/{id}/`) shows a **Slack** column to users with `view_risk`, with
critical tasks marked, and has an **Edit dependencies** form (any member) that calls
`set_dependencies()`, so a cycle can be tried and flagged from the UI as well as the API.

## 7. Client dashboard story

> *As a client, I want my own dashboard that is view only so that I can submit new requests and
> view progress.*

**Client** is a fourth role (`accounts/`). Its only feature is `client_dashboard`; it has no
`view_schedule`, so `ProjectAccess.is_member()` is false for a client on every project, even one
they were added to before their role changed. That one check keeps the schedule page, the REST
API and the WebSocket closed to clients. An admin makes a client a project's **owner** on the
Projects page (`/projects/`, feature `set_project_owner`).

**Flow (view progress):** `GET /dashboard/{id}/` → `clients.views.project` → `ClientDashboardService.project`
1. Check the user has `client_dashboard` (else 403).
2. `ProjectAccess.require_owner()`: a project they don't own, or one that doesn't exist, raises
   `ProjectOutOfScope`. The view shows *That project is out of scope for your permissions* and
   redirects to `/dashboard/`, which goes to their own project (or lists them, if they own several).
3. Build a `ClientProject`: name, dates, and one `ClientTask` (title, status, start, end) per task.
   Those are the only fields the template gets, so internal details (assignees, descriptions,
   dependencies, slack, members) can't reach the page, even by accident.

**Flow (notes for the team):** `POST /dashboard/{id}/` → `ClientDashboardService.add_note`: same
ownership check, then save a `ClientNote`. The schedule page lists the project's notes under
**Notes from the client**. A client who opens `/projects/{id}/` is redirected to `/dashboard/{id}/`.

## 8. Gantt story: a chart for clients and team members

> *As a client, I want a Gantt chart to graphically see how the product is progressing.
> As a team member, I want a Gantt chart to easily see how the project is coming along and
> what I can expect in the coming days.*

One chart, two audiences, following the client model in §7: team members see it at
`/projects/{id}/gantt/` with assignees; the client who owns the project sees it on their dashboard
without them. Clients are never members, so the team's chart (and every change to the schedule)
stays closed to them through the same `ProjectAccess.is_member()` check as the rest of the team's pages.

| Piece | Where | What it does |
|---|---|---|
| Task order | `TaskService.tasks_in_dependency_order()` | Runs the engine on the saved tasks and returns them in `ScheduleResult.order`: each task after the ones it depends on. Callers check access first: `TaskService.gantt_tasks()` (member + `view_gantt`) for the team, `ClientDashboardService.project()` (owner) for the client |
| What a client sees | `ClientDashboardService.project()` → `ClientProject.gantt` | The same tasks in dependency order, as `ClientTask` values (title, status, dates). No assignee field exists on them, so the client's chart can't show one |
| Bar layout | `tasks/gantt.py` `build_chart()` | Pure date math: the timeline spans the first start to the last end; each bar's left edge and width are percentages of it. Daily ticks up to 21 days, weekly after that; a line for today if it's on the chart. It reads dates through a `dates` function, so it lays out a `Task` or a `ClientTask` |
| Chart markup | `tasks/templates/tasks/_gantt_chart.html` (+ `_gantt_styles.html`) | Shared by both pages. CSS bars, no chart library, and no links, buttons or inputs inside the chart for anyone. `show_assignees` is on only for the team's page; the critical outline only for `view_risk` |
| Live refresh | the team page's WebSocket script | On any project event, re-fetches the page and swaps in the new chart and reports. (Clients can't join the WebSocket, so their dashboard updates when reloaded) |

The bars use the saved `scheduled_start` / `scheduled_end`, the same dates as the schedule table,
so the views always agree.

**Reporting a wrong chart.** Either audience can say the chart looks wrong (`report_gantt`):
team members through `TaskService.report_gantt_problem()` (member check), the client through
`ClientDashboardService.report_gantt_problem()` (owner check). Both end in
`TaskService.file_gantt_report()`, which validates the message (required, at most 1000 characters),
saves a `GanttReport` and, after commit, publishes `gantt.reported`. There's no separate scrum
master role, so project managers and admins act as the scrum master: they have
`review_gantt_reports`, see open reports on the team's Gantt page (plus a count on the schedule
page), and `resolve_gantt_report()` marks one resolved.

**Flows:**
* `GET /projects/{id}/gantt/` → `pages.gantt` → `TaskService.gantt_tasks` → `build_chart` → `gantt.html`
* `POST /projects/{id}/gantt/` → `TaskService.report_gantt_problem`
* `POST /projects/{id}/gantt/reports/{report_id}/resolve/` → `TaskService.resolve_gantt_report`
* `GET /dashboard/{id}/` → `clients.views.project` → `ClientDashboardService.project` → `build_chart` → `clients/project.html`
* `POST /dashboard/{id}/gantt-report/` → `clients.views.gantt_report` → `ClientDashboardService.report_gantt_problem`

## 9. Design principles applied

* **High cohesion:** each module and file has one responsibility (tables in §2).
* **Low coupling:** one-way dependencies, data coupling to the engine, constructor-supplied collaborators, an interface for events.
* **Information hiding:** each module hides a decision likely to change (algorithm, storage, permissions, transport, what clients see).
* **Separation of concerns:** HTTP, business rules, persistence and real-time are in separate files.
* **DRY:** all membership checks go through `ProjectAccess`; all task queries through `TaskRepository`.
* **YAGNI:** notifications other than real-time are left as an extension point, not built yet.
