"""Server-side input checks against script injection (security story 1).

Given someone bypasses the frontend, when the server receives invalid or
malicious input, then it rejects it with an error and saves nothing.

The services call these before saving, so every way in (the pages, the REST
API, anything else) goes through the same checks. They reject instead of
"cleaning" the input: silently rewriting what someone typed is easy to get
wrong, and the story asks for an error.

This is one of two layers. The other is output escaping: Django templates
escape everything they show, so even text saved before these checks existed
is displayed as plain text, never run.

The rules are deliberately narrow so normal input still works:
  * names (task titles, project names) may contain anything except < and >
    and invisible control characters, so "Q&A prep", "Phase 2 (beta)" and
    "Café launch" are all fine;
  * usernames follow Django's own username rule (letters, digits, @ . + - _),
    the same rule the Add user form and createsuperuser already apply;
  * longer text (descriptions, notes, reports) may use < and > on their own
    ("a < b", "<3", "-> next"), but not HTML tags like <script> or <img ...>.
"""
import re

from django.contrib.auth.validators import UnicodeUsernameValidator

# Control characters (null byte etc.), excluding tab and newlines in free text.
_NAME_FORBIDDEN = re.compile(r"[<>\x00-\x1f\x7f]")
_TEXT_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# "<" immediately followed by a letter, "/", "!" or "?" is how every HTML tag,
# closing tag, comment and processing instruction starts. Browsers treat "<"
# followed by a space as plain text, so "Costs < budget" is allowed.
_HTML_TAG = re.compile(r"<[a-zA-Z/!?]")
_USERNAME = re.compile(UnicodeUsernameValidator.regex)

INVALID_CHARACTERS = "{field} contains invalid characters"
HTML_NOT_ALLOWED = "{field} can't contain HTML or script tags"


def check_name(value: str, error: type[Exception], field: str = "Name") -> None:
    """A short single-line name: no < or >, no control characters."""
    if _NAME_FORBIDDEN.search(value):
        raise error(INVALID_CHARACTERS.format(field=field))


def check_username(value: str, error: type[Exception]) -> None:
    if not _USERNAME.match(value):
        raise error(INVALID_CHARACTERS.format(field="Username"))


def check_text(value: str, error: type[Exception], field: str) -> None:
    """Free text that may span lines: no HTML tags, no control characters."""
    if _TEXT_CONTROL.search(value):
        raise error(INVALID_CHARACTERS.format(field=field))
    if _HTML_TAG.search(value):
        raise error(HTML_NOT_ALLOWED.format(field=field))
