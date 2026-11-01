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

Tests (110):

```bash
python manage.py test accounts projects scheduling tasks clients
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

Clients aren't project members, so every endpoint here returns 403 for them; they use `/dashboard/` instead.

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
| `/dashboard/{id}/` | the project's owner | view-only progress (% complete, each task's name, status and dates), the project's **Gantt chart**, and "Notes for the team". Internal details (assignees, descriptions, dependencies, slack, team members) are never shown, on the chart either. Below the chart, "Does something look wrong?" reports it to the scrum master. A project you don't own says it's out of scope for your permissions and takes you to yours |
| `/projects/{id}/` | project members | story 1: the schedule, plus a form to add a task (name, start date, end date, assignee, dependencies). Updates live when anyone changes the project. Below it, "Edit dependencies" changes what a task depends on; a circular dependency is flagged and nothing changes. Project managers and admins also see each task's slack, with critical tasks marked, and how many Gantt chart reports are open. If the project has an owner, "Notes from the client" lists the notes they've left |
| `/projects/{id}/gantt/` | project members | Gantt story: opened with the **Gantt chart** button on the schedule. One bar per task, in dependency order, with its name, assignee, status and dates, and a line for today; your own tasks are marked. Read-only, and it redraws live when the project changes. Below it, anyone can report that the chart looks wrong; project managers and admins (the scrum master) see the open reports there and mark them resolved |

### Roles

| Role | Can |
|---|---|
| Client | on their own dashboard: follow the progress and Gantt chart of the projects they own, leave notes for the team, and report a chart that looks wrong. Never sees the team's pages, can't change anything and can't be assigned tasks |
| Team member | view the schedule and Gantt chart of their projects, add tasks, edit dependencies, update task status, report a chart that looks wrong |
| Project manager | everything a team member can, plus create projects, see slack and the critical path, and read and resolve Gantt chart reports (acts as the scrum master) |
| Administrator | everything except the client dashboard, plus manage users and roles and set project owners |

Superusers are always administrators. Non-admins who open `/users/` or try to change a role get "Access denied" (403).
Clients who open a team page for a project (`/projects/{id}/` or `/projects/{id}/gantt/`) are sent to their own dashboard instead.
The exact feature list per role is `ROLE_FEATURES` in `accounts/services.py`; the table at `/users/` shows it.

To try the Gantt story as a client: an admin adds a user with the **Client** role at `/users/`,
makes them a project's owner at `/projects/`, and the client logs in; they land on that project's dashboard.

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
tasks/           models, repository, services, serializers, views, container; pages + forms (schedule
                 and Gantt pages); gantt.py lays out the chart's bars
notifications/   events, publisher (interface + Channels impl), WebSocket consumer
```
