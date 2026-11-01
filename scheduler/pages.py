"""Server-rendered schedule page for story 1: a simple stand-in until the React UI exists.

    GET  /projects/<id>/   the project's schedule + an "Add a task" form
    POST /projects/<id>/   story 1: add a task from the form
                           PM story: change what a task depends on (cycles are rejected)

Like views.py, every request goes through task_service(); the rules live in services.py.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render

from common.errors import DomainError, NotAProjectMember

from .container import task_service
from .forms import AddTaskForm, EditDependenciesForm, StatusForm
from .models import TaskStatus
from .services import NewTask


@login_required
def schedule(request, project_id: int):
    service = task_service()
    try:
        project = service.get_project(request.user, project_id)
    except NotAProjectMember as exc:
        raise PermissionDenied(str(exc)) from exc
    tasks = service.list_schedule(request.user, project_id)

    # Three forms post to this page; the dependencies and status forms' fields carry
    # "deps-" and "status-" prefixes so we can tell which one was submitted.
    posted = request.POST if request.method == "POST" else None
    editing_deps = posted is not None and "deps-task_id" in posted
    changing_status = posted is not None and "status-task_id" in posted
    adding_task = posted is not None and not editing_deps and not changing_status

    if changing_status:  # story 2: change a task's status from its row
        status_form = StatusForm(posted, prefix="status")
        if status_form.is_valid():
            try:
                task = service.update_status(request.user, status_form.cleaned_data["task_id"],
                                             status_form.cleaned_data["status"])
            except DomainError as exc:
                messages.error(request, str(exc))
            else:
                messages.success(request, f"“{task.title}” is now {task.get_status_display().lower()}.")
        else:
            messages.error(request, "The status wasn't changed. Pick a valid status.")
        return redirect("project-schedule", project_id=project_id)

    deps_form = EditDependenciesForm(posted if editing_deps else None,
                                     tasks=tasks, prefix="deps")
    form = AddTaskForm(posted if adding_task else None,
                       members=project.members.order_by("username"), tasks=tasks)

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

    return render(request, "tasks/schedule.html", {
        "project": project, "tasks": tasks, "form": form, "deps_form": deps_form,
        # So the page can tick a task's current dependencies when it's picked
        "current_deps": {t.pk: [d.pk for d in t.depends_on.all()] for t in tasks},
        "show_risk": service.can_view_risk(request.user),  # PM story: slack + critical path
        "status_choices": TaskStatus.choices,  # story 2: the status picker on each row
    })
