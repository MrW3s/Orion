"""WebSocket endpoint: ws/projects/<project_id>/

A team member's schedule view opens this socket. Only project members may
join, and once joined they receive every ProjectEvent for that project.
This is what makes status changes show up "immediately for all relevant
team members" (story 2).
"""
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from projects.access import ProjectAccess


class ProjectConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.project_id = int(self.scope["url_route"]["kwargs"]["project_id"])
        self.group_name = f"project_{self.project_id}"
        user = self.scope.get("user")

        allowed = await database_sync_to_async(ProjectAccess().is_member)(user, self.project_id)
        if not allowed:
            await self.close(code=4403)
            return

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    # Called for messages sent with {"type": "project.event"}
    async def project_event(self, message):
        await self.send_json(message["event"])
