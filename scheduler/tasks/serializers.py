"""Converts between JSON and Python. Shape checks only, no business rules
(those live in services.py)."""
from rest_framework import serializers

from .models import Task, TaskStatus


class TaskSerializer(serializers.ModelSerializer):
    depends_on = serializers.PrimaryKeyRelatedField(many=True, read_only=True)

    class Meta:
        model = Task
        fields = [
            "id", "project", "title", "description", "assignee", "status",
            "duration_days", "depends_on", "scheduled_start", "scheduled_end",
            "created_by", "updated_at",
        ]
        read_only_fields = fields


class CreateTaskSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    duration_days = serializers.IntegerField(min_value=1, default=1)
    assignee_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    depends_on_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, default=list,
    )


class StatusUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=TaskStatus.choices)
