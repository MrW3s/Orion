"""The "Add a user" form on the Manage users page. Shape checks only; the
rules (username taken, password strength) are in services.py."""
from django import forms
from django.contrib.auth.validators import UnicodeUsernameValidator

from .models import Availability, Role

PASSWORD = forms.PasswordInput(attrs={"autocomplete": "new-password"})


class NewUserForm(forms.Form):
    username = forms.CharField(max_length=150,
                               validators=[UnicodeUsernameValidator(
                                   message="Username contains invalid characters. Use letters, "
                                           "numbers and @ . + - _ only.")],
                               error_messages={"required": "Enter a username."})
    role = forms.ChoiceField(choices=Role.choices, initial=Role.TEAM_MEMBER)
    password1 = forms.CharField(label="Password", widget=PASSWORD, strip=False,
                                error_messages={"required": "Enter a password."})
    password2 = forms.CharField(label="Confirm password", widget=PASSWORD, strip=False,
                                error_messages={"required": "Enter the password again."})

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("password1") and cleaned.get("password2") \
                and cleaned["password1"] != cleaned["password2"]:
            self.add_error("password2", "The passwords don't match.")
        return cleaned


class EmployeeDetailsForm(forms.Form):
    """Admins: the details the employee list searches and filters on."""
    first_name = forms.CharField(max_length=150, required=False)
    last_name = forms.CharField(max_length=150, required=False)
    email = forms.EmailField(required=False, error_messages={"invalid": "Enter a valid email address."})
    department = forms.CharField(max_length=60, required=False)
    availability = forms.ChoiceField(choices=Availability.choices, initial=Availability.AVAILABLE)
