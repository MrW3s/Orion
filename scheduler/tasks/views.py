"""HTTP controllers for the task stories (the C in MVC; React is the V).

Each view: parse the request -> call ONE service method -> serialize the
result. No business rules here, so the views stay thin and highly cohesive.

    GET   /api/projects/<project_id>/tasks/   the schedule (ordered by date)
    POST  /api/projects/<project_id>/tasks/   story 1: add a task
    PATCH /api/tasks/<task_id>/status/        story 2: change status
"""
from rest_framework import status as http
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .container import task_service
from .serializers import CreateTaskSerializer, StatusUpdateSerializer, TaskSerializer
from .services import NewTask


class ProjectTasksView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, project_id: int):
        tasks = task_service().list_schedule(request.user, project_id)
        return Response(TaskSerializer(tasks, many=True).data)

    def post(self, request, project_id: int):
        body = CreateTaskSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        task = task_service().add_task(request.user, project_id, NewTask(**body.validated_data))
        return Response(TaskSerializer(task).data, status=http.HTTP_201_CREATED)


class TaskStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, task_id: int):
        body = StatusUpdateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        task = task_service().update_status(request.user, task_id, body.validated_data["status"])
        return Response(TaskSerializer(task).data)
