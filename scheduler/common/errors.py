"""Domain errors shared across apps.

Services raise these; only the API layer (tasks/views.py) translates them
into HTTP responses. That way the business logic never knows about HTTP.
"""


class DomainError(Exception):
    """Base class for errors caused by a request that breaks a business rule."""


class NotAProjectMember(DomainError):
    pass


class InvalidTask(DomainError):
    """Task data breaks a rule (e.g. assignee isn't on the project)."""


class InvalidDependency(DomainError):
    """Dependency points outside the project, or would create a cycle."""


class TaskNotFound(DomainError):
    pass


class NotAnAdmin(DomainError):
    """Only administrators may do this (story 4)."""


class InvalidRoleChange(DomainError):
    """Unknown role, or a role that can't be changed (your own, a superuser's)."""


class UserNotFound(DomainError):
    pass
