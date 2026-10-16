"""Server-rendered schedule page for story 1: a simple stand-in until the React UI exists.

    GET  /projects/<id>/   the project's schedule + an "Add a task" form
    POST /projects/<id>/   story 1: add a task from the form

Like views.py, every request goes through task_service(); the rules live in services.py.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render

from common.errors import DomainError, NotAProjectMember

from .container import task_service
from .forms import AddTaskForm
from .services import NewTask


@login_required
def schedule(request, project_id: int):
    service = task_service()
    try:
        project = service.get_project(request.user, project_id)
    except NotAProjectMember as exc:
        raise PermissionDenied(str(exc)) from exc
    tasks = service.list_schedule(request.user, project_id)

    form = AddTaskForm(request.POST if request.method == "POST" else None,
                       members=project.members.order_by("username"), tasks=tasks)
    if form.is_valid():
        try:
            task = service.add_task(request.user, project_id, NewTask(**form.cleaned_data))
        except DomainError as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, f"Added “{task.title}” to the schedule.")
            return redirect("project-schedule", project_id=project_id)

    return render(request, "tasks/schedule.html", {"project": project, "tasks": tasks, "form": form})
