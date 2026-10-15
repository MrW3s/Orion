"""Composition root: the ONE place that decides which concrete classes
TaskService gets. Views call task_service(); tests build TaskService
themselves with fakes (e.g. InMemoryPublisher)."""
from notifications.publisher import ChannelsPublisher
from projects.access import ProjectAccess
from scheduling import Scheduler

from .repository import TaskRepository
from .services import TaskService


def task_service() -> TaskService:
    return TaskService(
        repository=TaskRepository(),
        scheduler=Scheduler(),
        access=ProjectAccess(),
        publisher=ChannelsPublisher(),
    )
