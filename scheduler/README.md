# Task Scheduler Backend (Sprint 1)

Django backend for a project-management tool for small agencies: team members add tasks,
a dependency-graph engine schedules them, and status changes appear live for the team.

See **ARCHITECTURE.md** for the design, module responsibilities, and coupling/cohesion rationale.

## Run it

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser        # the first admin; add a Project + members in /admin/
python manage.py runserver              # serves HTTP and WebSockets (via daphne)
python manage.py test accounts scheduling tasks  # 24 tests
```

## API

| Method | URL | Story |
|---|---|---|
| GET | `/api/projects/{id}/tasks/` | view schedule |
| POST | `/api/projects/{id}/tasks/` | 1: add task `{title, duration_days, depends_on_ids, assignee_id, description}` |
| PATCH | `/api/tasks/{id}/status/` | 2: `{status: "todo" \| "in_progress" \| "complete"}` |
| WS | `/ws/projects/{id}/` | live events: `schedule.changed`, `task.status_changed` |

## Pages (story 4: role-based permissions)

Open http://127.0.0.1:8000/ and log in.

| URL | Who | What |
|---|---|---|
| `/login/` | anyone | log in |
| `/` | any user | your role, what it lets you access, your projects |
| `/users/` | admins only | change any user's role (team member / project manager / administrator) |

Superusers are always administrators. Non-admins who open `/users/` or try to change a role get "Access denied" (403).

## Layout

```
config/          settings, urls, asgi (HTTP + WebSocket routing)
accounts/        roles (story 4): Profile model, RoleService (who can use what), login/home/manage-users pages
common/          domain errors + HTTP error mapping
projects/        Project model, membership rules (access.py)
scheduling/      pure-Python engine: graph.py, scheduler.py   (no Django)
tasks/           models, repository, services, serializers, views, container
notifications/   events, publisher (interface + Channels impl), WebSocket consumer
```
