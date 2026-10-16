"""Server-rendered "New project" page: a simple stand-in until the React UI exists.

    GET  /projects/new/   the form (project managers and admins only)
    POST /projects/new/   create the project, then go to its schedule
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render

from common.errors import DomainError, NotAllowed

from .forms import NewProjectForm
from .services import NewProject, ProjectService


@login_required
def new_project(request):
    service = ProjectService()
    if not service.can_create(request.user):
        raise PermissionDenied("Your role can't create projects")

    form = NewProjectForm(request.POST if request.method == "POST" else None,
                          users=service.possible_members(request.user))
    if form.is_valid():
        try:
            project = service.create_project(request.user, NewProject(**form.cleaned_data))
        except NotAllowed as exc:
            raise PermissionDenied(str(exc)) from exc
        except DomainError as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, f"Created “{project.name}”. Add its first task below.")
            return redirect("project-schedule", project_id=project.pk)

    return render(request, "projects/new_project.html", {"form": form})
