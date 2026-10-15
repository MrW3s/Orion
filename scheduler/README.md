# Task Scheduler Backend (Sprint 1)

Django backend for a project-management tool for small agencies: team members add tasks,
a dependency-graph engine schedules them, and status changes appear live for the team.

See **ARCHITECTURE.md** for the design, module responsibilities, and coupling/cohesion rationale.

## Run it

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser        # then add a Project + members in /admin/
python manage.py runserver              # serves HTTP and WebSockets (via daphne)
python manage.py test scheduling tasks  # 12 tests
```

## API

| Method | URL | Story |
|---|---|---|
| GET | `/api/projects/{id}/tasks/` | view schedule |
| POST | `/api/projects/{id}/tasks/` | 1: add task `{title, duration_days, depends_on_ids, assignee_id, description}` |
| PATCH | `/api/tasks/{id}/status/` | 2: `{status: "todo" \| "in_progress" \| "complete"}` |
| WS | `/ws/projects/{id}/` | live events: `schedule.changed`, `task.status_changed` |

## Layout

```
config/          settings, urls, asgi (HTTP + WebSocket routing)
common/          domain errors + HTTP error mapping
projects/        Project model, membership rules (access.py)
scheduling/      pure-Python engine: graph.py, scheduler.py   (no Django)
tasks/           models, repository, services, serializers, views, container
notifications/   events, publisher (interface + Channels impl), WebSocket consumer
```
