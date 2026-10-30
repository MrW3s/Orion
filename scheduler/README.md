# Task Scheduler Backend (Sprint 1)

Django backend for a project-management tool for small agencies: team members add tasks,
a dependency-graph engine schedules them, and status changes appear live for the team.

See **ARCHITECTURE.md** for the design, module responsibilities, and coupling/cohesion rationale.

## Run it

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser        # the first admin (can create projects at /projects/new/)
python manage.py runserver              # serves HTTP and WebSockets (via daphne)
python manage.py test accounts projects scheduling tasks clients  # 87 tests
```

## API

| Method | URL | Story |
|---|---|---|
| GET | `/api/projects/{id}/tasks/` | view schedule |
| POST | `/api/projects/{id}/tasks/` | 1: add task `{title, start_date, end_date, depends_on_ids, assignee_id, description}` (title and both dates required) |
| PATCH | `/api/tasks/{id}/status/` | 2: `{status: "todo" \| "in_progress" \| "complete"}` |
| GET | `/api/projects/{id}/risk/` | PM: task ordering, critical path and project end (project managers and admins) |
| PUT | `/api/tasks/{id}/dependencies/` | PM: `{depends_on_ids}` replaces a task's dependencies; a cycle is rejected (400) and nothing changes |
| WS | `/ws/projects/{id}/` | live events: `schedule.changed`, `task.status_changed` |

## Pages

Open http://127.0.0.1:8000/ and log in.

| URL | Who | What |
|---|---|---|
| `/login/` | anyone | log in |
| `/` | any user | your role, what it lets you access, your projects (clients go to `/dashboard/`) |
| `/users/` | admins only | story 4: change any user's role (team member / project manager / administrator / client), and add new users with a password and role |
| `/password/` | any user | change your own password |
| `/projects/new/` | project managers, admins | create a project and pick its members (you're added automatically; clients can't be members) |
| `/projects/` | admins only | every project, and which client owns it (pick a user with the Client role, or no owner) |
| `/dashboard/` | clients | client dashboard: goes straight to your project, or lists them if you own several |
| `/dashboard/{id}/` | the project's owner | view-only progress (% complete, each task's name, status and dates) and "Notes for the team". Internal details (assignees, descriptions, dependencies, slack, team members) are never shown. A project you don't own says it's out of scope for your permissions and takes you to yours |
| `/projects/{id}/` | project members | story 1: the schedule, plus a form to add a task (name, start date, end date, assignee, dependencies). Updates live when anyone changes the project. Below it, "Edit dependencies" changes what a task depends on; a circular dependency is flagged and nothing changes. Project managers and admins also see each task's slack, with critical tasks marked. If the project has an owner, "Notes from the client" lists the notes they've left |

Superusers are always administrators. Non-admins who open `/users/` or try to change a role get "Access denied" (403).
Clients who open a team page for a project (`/projects/{id}/`) are sent to their own dashboard instead.

A task's start date is the earliest it can start. If a task it depends on isn't finished by then,
the engine moves it later (keeping its length) and the schedule says so.

## Layout

```
config/          settings, urls, asgi (HTTP + WebSocket routing)
accounts/        roles (story 4): Profile model, RoleService (who can use what), login/home/manage-users pages
common/          domain errors + HTTP error mapping
projects/        Project + ClientNote models, membership and owner rules (access.py), New project + Projects pages
clients/         client dashboard: what a client may see (services.py), progress + notes pages
scheduling/      pure-Python engine: graph.py, scheduler.py, critical_path.py   (no Django)
tasks/           models, repository, services, serializers, views, container; pages + forms (schedule page)
notifications/   events, publisher (interface + Channels impl), WebSocket consumer
```
