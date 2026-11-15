-- Orion database schema (SQLite), for reference.
-- The real tables are created by the Django migrations (python manage.py migrate);
-- this file shows the same structure with readable names. Django prefixes each
-- table with its app (e.g. users -> auth_user, tasks -> tasks_task).

-- foreign keys must be kept on to avoid breaking relationships
PRAGMA foreign_keys = ON;

-- users (Django's built-in auth_user, trimmed to the columns Orion uses)
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password TEXT NOT NULL              -- a hash, never the plain password
);

-- each user's role (Team member, Project manager, Administrator)
-- a user with no row here is a team member
CREATE TABLE profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL UNIQUE REFERENCES users (id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'team_member'
        CHECK (role IN ('team_member', 'project_manager', 'admin'))
);

-- projects (name, start date)
CREATE TABLE projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    start_date DATE NOT NULL
);

-- who belongs to which project (only members can see and change its tasks)
CREATE TABLE project_members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    UNIQUE (project_id, user_id)
);

-- tasks (ID#, title, description, status, created by, ...)
CREATE TABLE tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    assignee_id INTEGER REFERENCES users (id) ON DELETE SET NULL,
    created_by_id INTEGER REFERENCES users (id) ON DELETE SET NULL,
    duration_days INTEGER NOT NULL DEFAULT 1 CHECK (duration_days >= 0),
    planned_start DATE,                 -- the start date the user picked
    status TEXT NOT NULL DEFAULT 'todo'
        CHECK (status IN ('todo', 'in_progress', 'complete')),
    kind TEXT NOT NULL DEFAULT 'task' CHECK (kind IN ('task', 'bug')),
    blocked_since DATETIME,             -- blocked while this is set
    blocked_reason TEXT NOT NULL DEFAULT '',
    -- written by the scheduling engine, never by users directly
    scheduled_start DATE,
    scheduled_end DATE,
    slack_days INTEGER,                 -- days it can slip without delaying the project
    is_critical BOOLEAN NOT NULL DEFAULT 0,  -- on the critical path (slack 0)
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- "this task can't start until that one is done"
-- the app rejects any dependency that would create a cycle
CREATE TABLE task_dependencies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES tasks (id) ON DELETE CASCADE,
    depends_on_id INTEGER NOT NULL REFERENCES tasks (id) ON DELETE CASCADE,
    UNIQUE (task_id, depends_on_id)
);

-- activity log: who changed what on a task, and when (standup story)
-- written in the same transaction as the change; no history before it existed
CREATE TABLE task_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    task_id INTEGER NOT NULL REFERENCES tasks (id) ON DELETE CASCADE,
    actor_id INTEGER REFERENCES users (id) ON DELETE SET NULL,
    kind TEXT NOT NULL CHECK (kind IN ('created', 'in_progress', 'done', 'reopened',
                                       'blocked', 'unblocked', 'reassigned', 'rescheduled')),
    old_value TEXT NOT NULL DEFAULT '',
    new_value TEXT NOT NULL DEFAULT '',
    created_at DATETIME NOT NULL
);
CREATE INDEX taskevent_project_time ON task_events (project_id, created_at);
CREATE INDEX taskevent_task_time ON task_events (task_id, created_at);

-- each project's standup speaking order, shared by the team
CREATE TABLE standup_order (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    UNIQUE (project_id, user_id)
);
