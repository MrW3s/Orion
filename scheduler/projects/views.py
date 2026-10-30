"""Server-rendered project pages: a simple stand-in until the React UI exists.

    GET  /projects/new/              the form (project managers and admins only)
    POST /projects/new/              create the project, then go to its schedule
    GET  /projects/                  admins only: every project and the client who owns it
    POST /projects/<id>/owner/       admins only: set (or clear) a project's owner
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from common.errors import DomainError, NotAllowed

from .forms import NewProjectForm, OwnerForm
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


@login_required
def manage_projects(request):
    service = ProjectService()
    try:
        projects = service.list_projects(request.user)
    except NotAllowed as exc:
        raise PermissionDenied(str(exc)) from exc
    return render(request, "projects/manage_projects.html", {
        "projects": projects, "owners": service.possible_owners(),
    })


@login_required
@require_POST
def set_owner(request, project_id: int):
    service = ProjectService()
    if not service.can_set_owner(request.user):
        raise PermissionDenied("Only administrators can set a project's owner")

    form = OwnerForm(request.POST, owners=service.possible_owners())
    if not form.is_valid():
        messages.error(request, "Pick the owner from the list.")
        return redirect("manage-projects")
    try:
        project = service.set_owner(request.user, project_id, form.cleaned_data["owner_id"])
    except DomainError as exc:
        messages.error(request, str(exc))
    else:
        if project.owner:
            messages.success(request, f"{project.owner.username} now owns “{project.name}”.")
        else:
            messages.success(request, f"“{project.name}” no longer has an owner.")
    return redirect("manage-projects")
