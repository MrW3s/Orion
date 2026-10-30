"""Translates domain errors into HTTP responses. This is the only place in
the code base where business rules meet HTTP status codes."""
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler

from .errors import (
    DomainError, InvalidDependency, InvalidNote, InvalidProject, InvalidRoleChange, InvalidTask,
    InvalidUser, NotAllowed, NotAnAdmin, NotAProjectMember, ProjectNotFound, ProjectOutOfScope,
    TaskNotFound, UserNotFound,
)

STATUS_FOR = {
    NotAProjectMember: status.HTTP_403_FORBIDDEN,
    TaskNotFound: status.HTTP_404_NOT_FOUND,
    InvalidDependency: status.HTTP_400_BAD_REQUEST,
    InvalidTask: status.HTTP_400_BAD_REQUEST,
    NotAnAdmin: status.HTTP_403_FORBIDDEN,
    InvalidRoleChange: status.HTTP_400_BAD_REQUEST,
    UserNotFound: status.HTTP_404_NOT_FOUND,
    NotAllowed: status.HTTP_403_FORBIDDEN,
    InvalidProject: status.HTTP_400_BAD_REQUEST,
    InvalidUser: status.HTTP_400_BAD_REQUEST,
    ProjectNotFound: status.HTTP_404_NOT_FOUND,
    ProjectOutOfScope: status.HTTP_403_FORBIDDEN,
    InvalidNote: status.HTTP_400_BAD_REQUEST,
}


def domain_exception_handler(exc, context):
    if isinstance(exc, DomainError):
        code = STATUS_FOR.get(type(exc), status.HTTP_400_BAD_REQUEST)
        return Response({"error": type(exc).__name__, "detail": str(exc)}, status=code)
    return exception_handler(exc, context)
