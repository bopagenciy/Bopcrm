import re
import uuid
from rest_framework import serializers
from django.utils.translation import gettext_lazy as _

from bop_integration.constants import RECOGNIZED_SOURCE_APPS

EVENT_TYPE_REGEX = re.compile(r"^[a-z0-9_]+(?:\.[a-z0-9_]+)+$")

ALLOWED_TOP_LEVEL_KEYS = frozenset({
    "event_id",
    "event_type",
    "source_app",
    "bop_organization_id",
    "external_entity_id",
    "idempotency_key",
    "occurred_at",
    "payload",
})


class BopEventEnvelopeSerializer(serializers.Serializer):
    """
    Validation serializer for generic inbound Bop Universe event envelopes.
    Enforces required envelope fields, normalized source_app registry validation,
    and strict top-level property boundaries.
    """

    event_id = serializers.CharField(
        max_length=255,
        required=True,
        help_text=_("Unique event UUID string sent by Bop source app"),
    )
    event_type = serializers.CharField(
        max_length=128,
        required=True,
        help_text=_("Domain event name (e.g., 'prospect.ready_for_crm')"),
    )
    source_app = serializers.CharField(
        max_length=64,
        required=True,
        help_text=_("Origin application name (e.g., 'bop_clients')"),
    )
    bop_organization_id = serializers.UUIDField(
        required=True,
        help_text=_("Target organization Bop UUID"),
    )
    external_entity_id = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        allow_null=True,
        default="",
    )
    idempotency_key = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        allow_null=True,
        default="",
    )
    occurred_at = serializers.DateTimeField(
        required=False,
        allow_null=True,
        default=None,
    )
    payload = serializers.JSONField(
        required=False,
        default=dict,
    )

    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError({"detail": "Invalid JSON object structure."})

        # Guard against undocumented/arbitrary top-level fields
        extra_keys = set(data.keys()) - ALLOWED_TOP_LEVEL_KEYS
        if extra_keys:
            raise serializers.ValidationError(
                {key: "Undocumented top-level field is not permitted." for key in extra_keys}
            )
        return super().to_internal_value(data)

    def validate_source_app(self, value):
        normalized = (value or "").strip().lower()
        if normalized not in RECOGNIZED_SOURCE_APPS:
            raise serializers.ValidationError(
                f"Unsupported source_app '{value}'. Must be one of: {', '.join(sorted(RECOGNIZED_SOURCE_APPS))}"
            )
        return normalized

    def validate_event_type(self, value):
        normalized = (value or "").strip().lower()
        if not normalized:
            raise serializers.ValidationError("event_type cannot be empty.")
        if not EVENT_TYPE_REGEX.match(normalized):
            raise serializers.ValidationError(
                "event_type must follow normalized namespaced dot notation (e.g., 'domain.entity.action')."
            )
        return normalized

    def validate_event_id(self, value):
        normalized = (value or "").strip()
        if not normalized:
            raise serializers.ValidationError("event_id cannot be empty.")
        try:
            uuid.UUID(normalized)
        except (ValueError, AttributeError, TypeError):
            raise serializers.ValidationError("event_id must be a valid UUID string.")
        return normalized

    def validate_payload(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("payload must be a JSON object/dict.")
        return value
