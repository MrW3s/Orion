"""Server-rendered project pages: a simple stand-in until the React UI exists.

    GET  /projects/<id>/        the project's schedule + an "Add a task" form
    POST /projects/<id>/        story 1: add a task from the form
                                PM story: change what a task depends on (cycles are rejected)
                                standup story: change a task's status, assignee or blocked state
    GET  /projects/<id>/gantt/  Gantt story: one bar per task, in dependency order
    POST /projects/<id>/gantt/  Gantt story: report that the chart looks wrong
    POST /projects/<id>/gantt/reports/<report_id>/resolve/
                                Gantt story: a project manager marks a report resolved

The schedule page also lists the notes the project's client has left (client
dashboard story). A client who opens either page is sent to their own
view-only dashboard instead, which has its own Gantt chart without assignees.

Like views.py, every request goes through task_service(); the rules live in services.py.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.services import RoleService
from common.errors import DomainError, NotAllowed, NotAProjectMember

from .container import task_service
from .forms import AddTaskForm, EditDependenciesForm, GanttReportForm, UpdateTaskForm
from .gantt import build_chart
from .services import NewTask


def _turn_away(request, project_id: int, exc: Exception):
    if RoleService().can(request.user, "client_dashboard"):
        # Clients get the view-only version, which also turns away projects they don't own.
        return redirect("client-project", project_id=project_id)
    raise PermissionDenied(str(exc)) from exc


@login_required
def schedule(request, project_id: int):
    service = task_service()
    try:
        project = service.get_project(request.user, project_id)
    except NotAProjectMember as exc:
        return _turn_away(request, project_id, exc)
    tasks = service.list_schedule(request.user, project_id)

    # Three forms post to this page; the other two forms' fields carry a "deps-" / "upd-" prefix.
    posted = request.POST if request.method == "POST" else {}
    editing_deps, updating = "deps-task_id" in posted, "upd-task_id" in posted
    members = service.assignable_members(project_id)
    deps_form = EditDependenciesForm(posted if editing_deps else None, tasks=tasks, prefix="deps")
    update_form = UpdateTaskForm(posted if updating else None, members=members, tasks=tasks,
                                 prefix="upd")
    form = AddTaskForm(posted if posted and not (editing_deps or updating) else None,
                       members=members, tasks=tasks)

    if update_form.is_valid():
        try:
            task = _apply_update(service, request.user, update_form.cleaned_data)
        except DomainError as exc:
            update_form.add_error(None, str(exc))
        else:
            messages.success(request, f"Updated “{task.title}”.")
            return redirect("project-schedule", project_id=project_id)

    if deps_form.is_valid():
        try:
            task = service.set_dependencies(request.user, deps_form.cleaned_data["task_id"],
                                            deps_form.cleaned_data["depends_on_ids"])
        except DomainError as exc:  # e.g. a circular dependency
            deps_form.add_error(None, str(exc))
        else:
            messages.success(request, f"Updated what “{task.title}” depends on.")
            return redirect("project-schedule", project_id=project_id)

    if form.is_valid():
        try:
            task = service.add_task(request.user, project_id, NewTask(**form.cleaned_data))
        except DomainError as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, f"Added “{task.title}” to the schedule.")
            return redirect("project-schedule", project_id=project_id)

    can_review = service.can_review_gantt_reports(request.user)
    return render(request, "tasks/schedule.html", {
        "project": project, "tasks": tasks, "form": form, "deps_form": deps_form,
        "update_form": update_form,
        # So the page can tick a task's current dependencies when it's picked
        "current_deps": {t.pk: [d.pk for d in t.depends_on.all()] for t in tasks},
        # ...and fill in the update form with a task's current state
        "current_state": {t.pk: {"status": t.status, "assignee_id": t.assignee_id,
                                 "blocked": t.is_blocked, "blocked_reason": t.blocked_reason}
                          for t in tasks},
        "show_risk": service.can_view_risk(request.user),  # PM story: slack + critical path
        "open_reports": len(service.open_gantt_reports(request.user, project_id)) if can_review else 0,
    })


def _apply_update(service, user, data):
    """Save only what changed; each service call is a no-op when nothing did."""
    task_id = data["task_id"]
    service.update_status(user, task_id, data["status"])
    service.reassign(user, task_id, data["assignee_id"])
    if data["blocked"]:
        return service.set_blocked(user, task_id, data["blocked_reason"])
    return service.unblock(user, task_id)


@login_required
def gantt(request, project_id: int):
    service = task_service()
    try:
        project = service.get_project(request.user, project_id)
        tasks = service.gantt_tasks(request.user, project_id)
    except NotAProjectMember as exc:
        return _turn_away(request, project_id, exc)
    except NotAllowed as exc:
        raise PermissionDenied(str(exc)) from exc

    form = GanttReportForm(request.POST if request.method == "POST" else None)
    if form.is_valid():
        try:
            service.report_gantt_problem(request.user, project_id, form.cleaned_data["message"])
        except NotAllowed as exc:
            raise PermissionDenied(str(exc)) from exc
        except DomainError as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, "Thanks. Your report was sent to the project's scrum master.")
            return redirect("project-gantt", project_id=project_id)

    can_review = service.can_review_gantt_reports(request.user)
    return render(request, "tasks/gantt.html", {
        "project": project,
        "chart": build_chart(tasks, timezone.localdate()),
        "form": form,
        "show_assignees": True,
        "show_risk": service.can_view_risk(request.user),
        "can_review": can_review,
        "reports": service.open_gantt_reports(request.user, project_id) if can_review else [],
    })


@login_required
@require_POST
def resolve_gantt_report(request, project_id: int, report_id: int):
    try:
        service = task_service()
        report = service.resolve_gantt_report(request.user, report_id)
    except (NotAProjectMember, NotAllowed) as exc:
        raise PermissionDenied(str(exc)) from exc
    except DomainError as exc:
        messages.error(request, str(exc))
    else:
        reporter = report.reporter.username if report.reporter else "a former user"
        messages.success(request, f"Marked {reporter}’s report as resolved.")
    return redirect("project-gantt", project_id=project_id)
