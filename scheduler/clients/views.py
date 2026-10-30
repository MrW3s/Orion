"""Server-rendered client dashboard: a simple stand-in until the React UI exists.

    GET  /dashboard/        your project (or a list, if you own several)
    GET  /dashboard/<id>/   one project's progress, plus the notes you've left
    POST /dashboard/<id>/   leave a note for the team

A project the client doesn't own sends them back to /dashboard/ with an
"out of scope" message, which in turn lands them on their own project.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render

from common.errors import DomainError, NotAllowed, ProjectOutOfScope

from .forms import NoteForm
from .services import ClientDashboardService


@login_required
def dashboard(request):
    try:
        projects = ClientDashboardService().projects(request.user)
    except NotAllowed as exc:
        raise PermissionDenied(str(exc)) from exc
    if len(projects) == 1:
        return redirect("client-project", project_id=projects[0].pk)
    return render(request, "clients/dashboard.html", {"projects": projects})


@login_required
def project(request, project_id: int):
    service = ClientDashboardService()
    try:
        progress = service.project(request.user, project_id)
    except NotAllowed as exc:
        raise PermissionDenied(str(exc)) from exc
    except ProjectOutOfScope as exc:
        messages.error(request, f"{exc}.")
        return redirect("client-dashboard")

    form = NoteForm(request.POST if request.method == "POST" else None)
    if form.is_valid():
        try:
            service.add_note(request.user, project_id, form.cleaned_data["text"])
        except DomainError as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, "Your note was sent to the project team.")
            return redirect("client-project", project_id=project_id)

    return render(request, "clients/project.html", {"progress": progress, "form": form})
