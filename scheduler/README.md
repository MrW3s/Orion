# Task Scheduler Backend (Sprint 1)

Django backend for a project-management tool for small agencies: team members add tasks,
a dependency-graph engine schedules them, and status changes appear live for the team.
Clients and team members follow progress on a Gantt chart.

See **ARCHITECTURE.md** for the design, module responsibilities, and coupling/cohesion rationale.

## Run it

Run these from the `scheduler/` folder, one line at a time. Copy only the command itself:
in a PyCharm run configuration, anything after it (such as a `#` comment) is passed to the
command as extra arguments.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

* On Windows, activate with `.venv\Scripts\activate`.
* `createsuperuser` makes the first admin, who can add users at `/users/` and create projects at `/projects/new/`.
  Forgot a password? `python manage.py changepassword <username>`.
* `runserver` serves HTTP and WebSockets (via daphne) on http://127.0.0.1:8000/. If it says
  *Address already in use*, a server is already running: use it, or stop it with Ctrl+C first.
* After pulling new code, run `python manage.py migrate` again.

Tests (86):

```bash
python manage.py test accounts projects scheduling tasks
```

## API

| Method | URL | Story |
|---|---|---|
| GET | `/api/projects/{id}/tasks/` | view schedule |
| POST | `/api/projects/{id}/tasks/` | 1: add task `{title, start_date, end_date, depends_on_ids, assignee_id, description}` (title and both dates required) |
| PATCH | `/api/tasks/{id}/status/` | 2: `{status: "todo" \| "in_progress" \| "complete"}` |
| GET | `/api/projects/{id}/risk/` | PM: task ordering, critical path and project end (project managers and admins) |
| PUT | `/api/tasks/{id}/dependencies/` | PM: `{depends_on_ids}` replaces a task's dependencies; a cycle is rejected (400) and nothing changes |
| WS | `/ws/projects/{id}/` | live events: `schedule.changed`, `task.status_changed`, `gantt.reported` |

Clients can `GET` the schedule but get 403 from every endpoint that changes it.

## Pages

Open http://127.0.0.1:8000/ and log in.

| URL | Who | What |
|---|---|---|
| `/login/` | anyone | log in |
| `/` | any user | your role, what it lets you access, your projects |
| `/users/` | admins only | story 4: change any user's role (client / team member / project manager / administrator), and add new users with a password and role |
| `/password/` | any user | change your own password |
| `/projects/new/` | project managers, admins | create a project and pick its members (you're added automatically) |
| `/projects/{id}/` | project members | story 1: the schedule, plus a form to add a task (name, start date, end date, assignee, dependencies). Updates live when anyone changes the project. Below it, "Edit dependencies" changes what a task depends on; a circular dependency is flagged and nothing changes. Project managers and admins also see each task's slack, with critical tasks marked, and how many Gantt chart reports are open. Clients see the schedule only, without the forms |
| `/projects/{id}/gantt/` | project members | Gantt story: opened with the **Gantt chart** button on the schedule. One bar per task, in dependency order, with its name, assignee, status and dates, and a line for today; your own tasks are marked. Read-only for everyone, and it redraws live when the project changes. Below it, anyone can report that the chart looks wrong; project managers and admins (the scrum master) see the open reports there and mark them resolved |

### Roles

| Role | Can |
|---|---|
| Client | view their projects' schedules and Gantt charts, and report a chart that looks wrong. Can't change anything or be assigned tasks |
| Team member | everything a client can, plus add tasks, edit dependencies and update task status |
| Project manager | everything a team member can, plus create projects, see slack and the critical path, and read and resolve Gantt chart reports (acts as the scrum master) |
| Administrator | everything, plus manage users and roles |

Superusers are always administrators. Non-admins who open `/users/` or try to change a role get "Access denied" (403).
The exact feature list per role is `ROLE_FEATURES` in `accounts/services.py`; the table at `/users/` shows it.

To try the Gantt story as a client: an admin adds a user with the **Client** role at `/users/`,
a project manager ticks them as a member when creating a project at `/projects/new/` (members
are picked when the project is created), and the client logs in and opens that project.

A task's start date is the earliest it can start. If a task it depends on isn't finished by then,
the engine moves it later (keeping its length) and the schedule says so.

## Layout

```
config/          settings, urls, asgi (HTTP + WebSocket routing)
accounts/        roles (story 4): Profile model, RoleService (who can use what), login/home/manage-users pages
common/          domain errors + HTTP error mapping
projects/        Project model, membership rules (access.py), New project page (services, forms, views)
scheduling/      pure-Python engine: graph.py, scheduler.py, critical_path.py   (no Django)
tasks/           models, repository, services, serializers, views, container; pages + forms (schedule
                 and Gantt pages); gantt.py lays out the chart's bars
notifications/   events, publisher (interface + Channels impl), WebSocket consumer
```
