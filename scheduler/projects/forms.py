"""The "New project" form. Shape checks only; the rules are in services.py."""
from django import forms


class NewProjectForm(forms.Form):
    name = forms.CharField(label="Project name", max_length=200,
                           error_messages={"required": "Give the project a name."})
    start_date = forms.DateField(label="Start date",
                                 widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
                                 error_messages={"required": "Pick a start date."})
    member_ids = forms.TypedMultipleChoiceField(label="Team members", coerce=int, required=False,
                                                widget=forms.CheckboxSelectMultiple)

    def __init__(self, *args, users=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["member_ids"].choices = [(u.pk, u.get_username()) for u in users]


class OwnerForm(forms.Form):
    """One row of the admin Projects page: which client owns the project."""

    owner_id = forms.TypedChoiceField(coerce=int, required=False, empty_value=None)

    def __init__(self, *args, owners=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["owner_id"].choices = (
            [("", "No owner")] + [(u.pk, u.get_username()) for u in owners]
        )
