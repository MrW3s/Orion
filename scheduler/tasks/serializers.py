"""Converts between JSON and Python. Shape checks only, no business rules
(those live in services.py)."""
from rest_framework import serializers

from .models import Task, TaskKind, TaskStatus
from .standup import WINDOWS
from .standup_service import SECTIONS


class TaskSerializer(serializers.ModelSerializer):
    depends_on = serializers.PrimaryKeyRelatedField(many=True, read_only=True)

    class Meta:
        model = Task
        fields = [
            "id", "project", "title", "description", "assignee", "status",
            "duration_days", "planned_start", "depends_on", "scheduled_start", "scheduled_end",
            "slack_days", "is_critical", "kind", "blocked_since", "blocked_reason",
            "created_by", "updated_at",
        ]
        read_only_fields = fields


class CreateTaskSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    start_date = serializers.DateField()
    end_date = serializers.DateField()  # with start_date, this is the duration estimate
    assignee_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    depends_on_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, default=list,
    )
    kind = serializers.ChoiceField(choices=TaskKind.choices, required=False, default=TaskKind.TASK)


class DependenciesSerializer(serializers.Serializer):
    depends_on_ids = serializers.ListField(child=serializers.IntegerField(), allow_empty=True)


class StatusUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=TaskStatus.choices)


class BlockSerializer(serializers.Serializer):
    reason = serializers.CharField()


class AssigneeSerializer(serializers.Serializer):
    assignee_id = serializers.IntegerField(allow_null=True)


class StandupQuerySerializer(serializers.Serializer):
    """?window=since_last|today|24h|custom&from=YYYY-MM-DD&to=YYYY-MM-DD&sections=tiles,people"""

    window = serializers.ChoiceField(choices=list(WINDOWS), required=False)
    to = serializers.DateField(required=False)
    sections = serializers.CharField(required=False)

    def get_fields(self):
        fields = super().get_fields()
        fields["from"] = serializers.DateField(required=False)  # "from" can't be an attribute name
        return fields

    def validate_sections(self, value):
        wanted = [s for s in value.split(",") if s]
        unknown = set(wanted) - set(SECTIONS)
        if unknown:
            raise serializers.ValidationError(f"Unknown sections: {', '.join(sorted(unknown))}")
        return wanted


class StandupOrderSerializer(serializers.Serializer):
    user_ids = serializers.ListField(child=serializers.IntegerField(), allow_empty=True)
