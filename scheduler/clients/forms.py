"""The "Notes for the team" form on the client dashboard. Shape checks only;
the rules are in services.py."""
from django import forms


class NoteForm(forms.Form):
    text = forms.CharField(label="Leave a note for the team", max_length=2000,
                           widget=forms.Textarea(attrs={"rows": 3}),
                           error_messages={"required": "Write a note first."})
