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
| `scheduling/` | Given tasks and dependencies, work out the schedule (graph, cycle detection, ordering, dates) | The scheduling algorithm. **Imports nothing from Django** |
| `tasks/` | The task use cases (stories 1 & 2) and their API | How tasks are stored and which concrete collaborators are used |
| `accounts/` | Users' roles and the pages for managing them (story 4) | Which role may use which feature (`ROLE_FEATURES` in `services.py`) |
| `projects/` | Projects and who belongs to them | The membership rules |
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
2. Check dependencies belong to the same project.
3. In one transaction: create the task → `_reschedule()` rebuilds the dependency graph →
   `Scheduler.compute()` → repository saves the new dates. A cycle rolls everything back.
4. After commit: publish `schedule.changed` to `project_{id}`; the clients re-fetch.

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
| **Task** | `project` (FK), `title`, `description`, `assignee` (FK User, optional), `created_by`, `duration_days` (≥ 1), `status` (`todo` / `in_progress` / `complete`), `depends_on` (M:N → Task), `scheduled_start`, `scheduled_end`, timestamps | Dependencies must be in the same project and form no cycle; assignee must be a member; scheduled dates are written by the engine only |

Relationships: Project 1─* Task · Project *─* User · Task *─* Task (dependency).

## 6. Built for the next story: critical path for the PM

> *As a project manager, I want the system to build a dependency graph … cycle detection,
> task ordering, and the critical path … to identify scheduling risks.*

Already in place:
* **Dependency graph**, **cycle detection** and **task ordering**: `scheduling/graph.py`
  (`topological_order()` raises `CycleError`). `ScheduleResult.order` exposes the ordering.
* **Earliest start/finish** (the CPM forward pass): `scheduling/scheduler.py`.
* **Single trigger point:** every time a task is committed, `TaskService._reschedule()` runs the engine.

To add later, without changing existing callers:
1. `scheduling/critical_path.py`: backward pass → latest start/finish → `slack = latest − earliest`; slack 0 ⇒ critical.
2. Add `slack_days`, `is_critical` to `ScheduledTask` and `critical_path` to `ScheduleResult`
   (spots are marked `FUTURE:` in the code).
3. Add `slack_days` / `is_critical` columns to `Task` and save them in `TaskRepository.save_schedule()`.
4. A PM-only endpoint (e.g. `GET /api/projects/{id}/risk/`) that reads them, guarded by `RoleService().can(user, "view_risk")` from `accounts/` (project managers and admins).

Because the engine is isolated behind `ScheduleResult`, steps 1–2 don't touch Django at all,
and `services.py` doesn't change.

## 7. Design principles applied

* **High cohesion:** each module and file has one responsibility (tables in §2).
* **Low coupling:** one-way dependencies, data coupling to the engine, constructor-supplied collaborators, an interface for events.
* **Information hiding:** each module hides a decision likely to change (algorithm, storage, permissions, transport).
* **Separation of concerns:** HTTP, business rules, persistence and real-time are in separate files.
* **DRY:** all membership checks go through `ProjectAccess`; all task queries through `TaskRepository`.
* **YAGNI:** critical path and notifications other than real-time are left as marked extension points, not built yet.
