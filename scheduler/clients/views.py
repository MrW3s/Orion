"""Server-rendered client dashboard: a simple stand-in until the React UI exists.

    GET  /dashboard/        your project (or a list, if you own several)
    GET  /dashboard/<id>/   one project's progress and Gantt chart, plus the notes you've left
    POST /dashboard/<id>/   leave a note for the team
    POST /dashboard/<id>/gantt-report/
                            Gantt story: tell the scrum master the chart looks wrong

A project the client doesn't own sends them back to /dashboard/ with an
"out of scope" message, which in turn lands them on their own project.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from common.errors import DomainError, NotAllowed, ProjectOutOfScope
from tasks.forms import GanttReportForm
from tasks.gantt import build_chart

from .forms import NoteForm
from .services import ClientDashboardService


def _client_task_dates(task):
    return task.start, task.end


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
def project(request, project_id: int, report_form=None):
    service = ClientDashboardService()
    try:
        progress = service.project(request.user, project_id)
    except NotAllowed as exc:
        raise PermissionDenied(str(exc)) from exc
    except ProjectOutOfScope as exc:
        messages.error(request, f"{exc}.")
        return redirect("client-dashboard")

    form = NoteForm(request.POST if request.method == "POST" and report_form is None else None)
    if form.is_valid():
        try:
            service.add_note(request.user, project_id, form.cleaned_data["text"])
        except DomainError as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, "Your note was sent to the project team.")
            return redirect("client-project", project_id=project_id)

    return render(request, "clients/project.html", {
        "progress": progress, "form": form,
        "chart": build_chart(progress.gantt, timezone.localdate(), dates=_client_task_dates),
        "report_form": report_form or GanttReportForm(),
    })


@login_required
@require_POST
def gantt_report(request, project_id: int):
    form = GanttReportForm(request.POST)
    if form.is_valid():
        try:
            ClientDashboardService().report_gantt_problem(request.user, project_id,
                                                          form.cleaned_data["message"])
        except NotAllowed as exc:
            raise PermissionDenied(str(exc)) from exc
        except ProjectOutOfScope as exc:
            messages.error(request, f"{exc}.")
            return redirect("client-dashboard")
        except DomainError as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, "Thanks. Your report was sent to the project's scrum master.")
            return redirect("client-project", project_id=project_id)
    # Show the dashboard again with the report form's errors.
    return project(request, project_id, report_form=form)
