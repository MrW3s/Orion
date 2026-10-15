"""How events reach connected clients.

EventPublisher is the interface the services depend on. ChannelsPublisher is
the real implementation (Django Channels / WebSockets); InMemoryPublisher
just records events, which is handy in tests. The services never know which
one they have (dependency inversion, which keeps the coupling low).
"""
from __future__ import annotations

from typing import Protocol

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from .events import ProjectEvent


class EventPublisher(Protocol):
    def publish(self, event: ProjectEvent) -> None: ...


class ChannelsPublisher:
    def publish(self, event: ProjectEvent) -> None:
        layer = get_channel_layer()
        if layer is None:  # real-time not configured; the data is still saved
            return
        async_to_sync(layer.group_send)(
            event.group_name,
            {"type": "project.event", "event": event.to_message()},
        )


class InMemoryPublisher:
    def __init__(self) -> None:
        self.events: list[ProjectEvent] = []

    def publish(self, event: ProjectEvent) -> None:
        self.events.append(event)
