# Sprint 1 Architecture: Task Scheduling Backend

Stack: **React** (frontend, not in this repo) · **Django + Django REST Framework** (backend) ·
**SQLite** (database) · **Django Channels** (WebSockets for real-time updates).

## 1. Architecture style

A **client-server** system using a **thin client**:

| Layer | Where | In this repo |
|---|---|---|
| Presentation | React in the browser | (not included); talks to the REST API and the WebSocket. Story 4 has simple Django-rendered pages in `accounts/templates/` for now |
| Application processing | Django server | `tasks/services.py`, `scheduling/` |
| Data management | Django server + SQLite | `*/models.py`, `tasks/repository.py` |

Inside the server the code follows **MVC**:

* **Model:** Django models (`Project`, `Task`) plus the scheduling engine
* **View:** the React screens (the JSON from `serializers.py` is what they display)
* **Controller:** `tasks/views.py` (REST) and `notifications/consumers.py` (WebSocket)

Requests flow one way: **controller → service → (repository | engine | access | publisher)**.

## 2. Modules

| Module | Single responsibility (cohesion) | Hides this design decision (information hiding) |
|---|---|---|
| `scheduling/` | Given tasks and dependencies, work out the schedule (graph, cycle detection, ordering, dates, slack, critical path) | The scheduling algorithm. **Imports nothing from Django** |
| `tasks/` | The task use cases (stories 1 & 2, PM story) and their API | How tasks are stored and which concrete collaborators are used |
| `accounts/` | Users' roles and the pages for managing them (story 4) | Which role may use which feature (`ROLE_FEATURES` in `services.py`) |
| `projects/` | Projects, who belongs to them, and creating them | The membership rules |
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
| `container.py` | Wires concrete classes into `TaskService` | no | no |
| `models.py` | Task table + `TaskStatus` | no | yes |

## 3. Dependencies (coupling)

```
            config
              │
            tasks ─────────────┬──────────────┬─────────────┐
              │                │              │             │
              ▼                ▼              ▼             ▼
         scheduling      notifications ──► projects ──► common
         (pure Python)
```

* **No cycles** between modules (checked: `scheduling` and `common` import nothing from the others).
* **`projects` → `accounts` and `tasks` → `accounts`:** creating a project asks
  `RoleService.can(user, "create_projects")`, and the PM risk view asks `can(user, "view_risk")`.
  `accounts` imports nothing from `projects` or `tasks`, so roles stay at the bottom with `common`.
* **`tasks` → `scheduling`: data coupling only.** The service passes plain `TaskNode` values
  and gets a plain `ScheduleResult` back. The engine never sees a Django model, so it can be
  unit-tested without a database and swapped or extended on its own.
* **`TaskService` receives its collaborators** (repository, scheduler, access, publisher)
  through its constructor instead of creating them. Tests pass an `InMemoryPublisher`;
  production uses `ChannelsPublisher`. Neither change touches `services.py`.
* **The services depend on the `EventPublisher` interface**, not on Channels. If the team
  later swaps WebSockets for polling or Server-Sent Events, only `notifications/` changes.
* **Errors cross layers as domain exceptions** (`common/errors.py`). Only `common/api.py`
  turns them into 400/403/404, so the business logic never mentions HTTP.

## 4. How each story flows

**Story 1: add a task to the schedule**
`POST /api/projects/{id}/tasks/` → `views.ProjectTasksView.post` → `TaskService.add_task`
1. Check the user is a project member (`ProjectAccess`).
2. Check the task has a name and valid dates (end ≥ start, start ≥ project start). The duration
   estimate is the number of days from start to end, both included.
3. Check dependencies belong to the same project.
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
| **Project** | `name`, `start_date`, `members` (M:N → User) | Only members can view/change its tasks |
| **Task** | `project` (FK), `title`, `description`, `assignee` (FK User, optional), `created_by`, `planned_start` (the start date the user picked), `duration_days` (≥ 1), `status` (`todo` = "Not started" / `in_progress` / `complete`), `depends_on` (M:N → Task), `scheduled_start`, `scheduled_end`, timestamps | Dependencies must be in the same project and form no cycle; assignee must be a member; scheduled dates are written by the engine only, never earlier than `planned_start` |

Relationships: Project 1─* Task · Project *─* User · Task *─* Task (dependency).

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

## 7. Design principles applied

* **High cohesion:** each module and file has one responsibility (tables in §2).
* **Low coupling:** one-way dependencies, data coupling to the engine, constructor-supplied collaborators, an interface for events.
* **Information hiding:** each module hides a decision likely to change (algorithm, storage, permissions, transport).
* **Separation of concerns:** HTTP, business rules, persistence and real-time are in separate files.
* **DRY:** all membership checks go through `ProjectAccess`; all task queries through `TaskRepository`.
* **YAGNI:** notifications other than real-time are left as an extension point, not built yet.
