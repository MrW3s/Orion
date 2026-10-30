"""Server-rendered schedule page for story 1: a simple stand-in until the React UI exists.

    GET  /projects/<id>/   the project's schedule + an "Add a task" form
    POST /projects/<id>/   story 1: add a task from the form
                           PM story: change what a task depends on (cycles are rejected)

The page also lists the notes the project's client has left (client dashboard story).
A client who opens this URL is sent to their own view-only dashboard instead.

Like views.py, every request goes through task_service(); the rules live in services.py.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render

from accounts.services import RoleService
from common.errors import DomainError, NotAProjectMember

from .container import task_service
from .forms import AddTaskForm, EditDependenciesForm
from .services import NewTask


@login_required
def schedule(request, project_id: int):
    service = task_service()
    try:
        project = service.get_project(request.user, project_id)
    except NotAProjectMember as exc:
        if RoleService().can(request.user, "client_dashboard"):
            # Clients get the view-only version, which also turns away projects they don't own.
            return redirect("client-project", project_id=project_id)
        raise PermissionDenied(str(exc)) from exc
    tasks = service.list_schedule(request.user, project_id)

    # Two forms post to this page; the dependencies form's fields carry a "deps-" prefix.
    editing_deps = request.method == "POST" and "deps-task_id" in request.POST
    deps_form = EditDependenciesForm(request.POST if editing_deps else None,
                                     tasks=tasks, prefix="deps")
    form = AddTaskForm(request.POST if request.method == "POST" and not editing_deps else None,
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
    })
