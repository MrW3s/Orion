"""Server-rendered project pages: a simple stand-in until the React UI exists.

    GET  /projects/<id>/        the project's schedule + an "Add a task" form
    POST /projects/<id>/        story 1: add a task from the form
                                PM story: change what a task depends on (cycles are rejected)
    GET  /projects/<id>/gantt/  Gantt story: one bar per task, in dependency order
    POST /projects/<id>/gantt/  Gantt story: report that the chart looks wrong
    POST /projects/<id>/gantt/reports/<report_id>/resolve/
                                Gantt story: a project manager marks a report resolved

Clients see the schedule and the Gantt chart but none of the editing forms.
Like views.py, every request goes through task_service(); the rules live in services.py.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from common.errors import DomainError, NotAllowed, NotAProjectMember

from .container import task_service
from .forms import AddTaskForm, EditDependenciesForm, GanttReportForm
from .gantt import build_chart
from .services import NewTask


@login_required
def schedule(request, project_id: int):
    service = task_service()
    try:
        project = service.get_project(request.user, project_id)
    except NotAProjectMember as exc:
        raise PermissionDenied(str(exc)) from exc
    tasks = service.list_schedule(request.user, project_id)
    can_edit = service.can_edit(request.user)
    if request.method == "POST" and not can_edit:
        raise PermissionDenied("Your role can view this project but not change it")

    # Two forms post to this page; the dependencies form's fields carry a "deps-" prefix.
    editing_deps = request.method == "POST" and "deps-task_id" in request.POST
    deps_form = EditDependenciesForm(request.POST if editing_deps else None,
                                     tasks=tasks, prefix="deps")
    form = AddTaskForm(request.POST if request.method == "POST" and not editing_deps else None,
                       members=service.assignable_members(project_id), tasks=tasks)

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
        "can_edit": can_edit,
        # So the page can tick a task's current dependencies when it's picked
        "current_deps": {t.pk: [d.pk for d in t.depends_on.all()] for t in tasks},
        "show_risk": service.can_view_risk(request.user),  # PM story: slack + critical path
        "open_reports": len(service.open_gantt_reports(request.user, project_id)) if can_review else 0,
    })


@login_required
def gantt(request, project_id: int):
    service = task_service()
    try:
        project = service.get_project(request.user, project_id)
        tasks = service.gantt_tasks(request.user, project_id)
    except (NotAProjectMember, NotAllowed) as exc:
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
        "can_edit": service.can_edit(request.user),
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
