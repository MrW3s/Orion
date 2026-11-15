"""The forms on the schedule and Gantt pages. Shape checks only, like
serializers.py; the business rules (end after start, dependencies in the
project, ...) are in services.py."""
from django import forms

from .models import TaskKind, TaskStatus

DATE = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


class AddTaskForm(forms.Form):
    title = forms.CharField(label="Name", max_length=200,
                            error_messages={"required": "Give the task a name."})
    start_date = forms.DateField(label="Start date", widget=DATE,
                                 error_messages={"required": "Pick a start date."})
    end_date = forms.DateField(label="End date", widget=DATE,
                               error_messages={"required": "Pick an end date."})
    assignee_id = forms.TypedChoiceField(label="Assignee", coerce=int, required=False,
                                         empty_value=None)
    depends_on_ids = forms.TypedMultipleChoiceField(label="Depends on", coerce=int, required=False,
                                                    widget=forms.CheckboxSelectMultiple)
    description = forms.CharField(label="Description (optional)", required=False,
                                  widget=forms.Textarea(attrs={"rows": 2}))
    kind = forms.ChoiceField(label="Type", choices=TaskKind.choices, initial=TaskKind.TASK,
                             required=False)

    def __init__(self, *args, members=(), tasks=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assignee_id"].choices = (
            [("", "Unassigned")] + [(u.pk, u.get_username()) for u in members]
        )
        self.fields["depends_on_ids"].choices = [(t.pk, t.title) for t in tasks]

    def clean_kind(self):
        return self.cleaned_data["kind"] or TaskKind.TASK


class GanttReportForm(forms.Form):
    """'This chart looks wrong' (Gantt story). The length rule is in services.py."""

    message = forms.CharField(
        label="What looks wrong?",
        widget=forms.Textarea(attrs={"rows": 3, "placeholder":
                                     "e.g. “Launch” should finish on Nov 14, not Nov 21"}),
        error_messages={"required": "Say what looks wrong on the chart."},
    )


class EditDependenciesForm(forms.Form):
    """Change what an existing task depends on (PM story). Uses prefix="deps" on the
    page so its fields don't clash with the "Add a task" form's."""

    task_id = forms.TypedChoiceField(label="Task", coerce=int,
                                     error_messages={"required": "Pick a task."})
    depends_on_ids = forms.TypedMultipleChoiceField(label="Depends on", coerce=int, required=False,
                                                    widget=forms.CheckboxSelectMultiple)

    def __init__(self, *args, tasks=(), **kwargs):
        super().__init__(*args, **kwargs)
        choices = [(t.pk, t.title) for t in tasks]
        self.fields["task_id"].choices = [("", "Choose a task")] + choices
        self.fields["depends_on_ids"].choices = choices


class UpdateTaskForm(forms.Form):
    """Change a task's status, assignee or blocked state (standup story). Uses
    prefix="upd" on the page. Only what actually changed is saved and logged."""

    task_id = forms.TypedChoiceField(label="Task", coerce=int,
                                     error_messages={"required": "Pick a task."})
    status = forms.ChoiceField(label="Status", choices=TaskStatus.choices)
    assignee_id = forms.TypedChoiceField(label="Assignee", coerce=int, required=False,
                                         empty_value=None)
    blocked = forms.BooleanField(label="Blocked", required=False)
    blocked_reason = forms.CharField(label="Blocked on (required when blocked)", required=False,
                                     max_length=500)

    def __init__(self, *args, members=(), tasks=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["task_id"].choices = [("", "Choose a task")] + [(t.pk, t.title) for t in tasks]
        self.fields["assignee_id"].choices = (
            [("", "Unassigned")] + [(u.pk, u.get_username()) for u in members]
        )

    def clean(self):
        data = super().clean()
        if data.get("blocked") and not (data.get("blocked_reason") or "").strip():
            self.add_error("blocked_reason", "Say what the task is blocked on.")
        return data
