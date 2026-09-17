import re
import uuid
from rest_framework import serializers
from django.utils.translation import gettext_lazy as _

from bop_integration.constants import (
    ALLOWED_PAYLOAD_KEYS_PROSPECT_READY_FOR_CRM_V1,
    ALLOWED_PAYLOAD_KEYS_PROSPECT_READY_FOR_CRM_V2,
    ALLOWED_TOP_LEVEL_KEYS,
    CANONICAL_SOURCE_APPS,
    PROHIBITED_PII_KEYS,
    RECOGNIZED_SOURCE_APPS,
    normalize_source_app,
)

EVENT_TYPE_REGEX = re.compile(r"^[a-z0-9_]+(?:\.[a-z0-9_]+)+$")


class BopSubjectSerializer(serializers.Serializer):
    """
    Serializer for the canonical BopEntityRef subject object.
    """
    bop_organization_id = serializers.UUIDField(required=True)
    application_id = serializers.CharField(max_length=64, required=True)
    entity_type = serializers.CharField(max_length=64, required=True)
    entity_id = serializers.CharField(max_length=128, required=True)

    def validate_application_id(self, value):
        normalized = (value or "").strip().lower()
        if not normalized:
            raise serializers.ValidationError("subject.application_id cannot be empty.")
        return normalized

    def validate_entity_type(self, value):
        normalized = (value or "").strip().lower()
        if not normalized:
            raise serializers.ValidationError("subject.entity_type cannot be empty.")
        return normalized

    def validate_entity_id(self, value):
        raw = str(value or "")
        if not raw or not raw.strip():
            raise serializers.ValidationError("subject.entity_id cannot be empty or whitespace-only.")
        if len(raw) > 128:
            raise serializers.ValidationError("subject.entity_id exceeds maximum length of 128 characters.")
        return raw


class BopEventEnvelopeSerializer(serializers.Serializer):
    """
    Validation serializer for inbound Bop Universe event envelopes.
    Enforces canonical Bop Clients schema, alias normalization, strict top-level
    property whitelisting, subject validation, and version-specific payload contracts.
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
    event_version = serializers.IntegerField(
        required=False,
        default=None,
        min_value=1,
        help_text=_("Schema version integer (e.g., 2)"),
    )
    occurred_at = serializers.DateTimeField(
        required=False,
        allow_null=True,
        default=None,
    )
    producer_app = serializers.CharField(
        max_length=64,
        required=False,
        allow_blank=True,
        allow_null=True,
        default=None,
        help_text=_("Canonical producer application (e.g., 'bopclients')"),
    )
    source_app = serializers.CharField(
        max_length=64,
        required=False,
        allow_blank=True,
        allow_null=True,
        default=None,
        help_text=_("Legacy origin application alias (e.g., 'bop_clients')"),
    )
    bop_organization_id = serializers.UUIDField(
        required=True,
        help_text=_("Target organization Bop UUID"),
    )
    subject = BopSubjectSerializer(
        required=False,
        allow_null=True,
        default=None,
    )
    correlation_id = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        allow_null=True,
        default=None,
    )
    causation_id = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        allow_null=True,
        default=None,
    )
    payload = serializers.JSONField(
        required=False,
        default=dict,
    )
    metadata = serializers.JSONField(
        required=False,
        default=dict,
    )
    external_entity_id = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        allow_null=True,
        default="",
    )
    external_entity_type = serializers.CharField(
        max_length=64,
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

    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError({"detail": "Invalid JSON object structure."})

        # Guard against undocumented/arbitrary top-level fields
        extra_keys = set(data.keys()) - ALLOWED_TOP_LEVEL_KEYS
        if extra_keys:
            raise serializers.ValidationError(
                {key: "Undocumented top-level field is not permitted." for key in extra_keys}
            )

        if "metadata" in data and data["metadata"] is not None and not isinstance(data["metadata"], dict):
            raise serializers.ValidationError({"metadata": "metadata must be a JSON object."})

        if "payload" in data and data["payload"] is not None and not isinstance(data["payload"], dict):
            raise serializers.ValidationError({"payload": "payload must be a JSON object/dict."})

        return super().to_internal_value(data)

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
            u = uuid.UUID(normalized)
            if u.version != 4:
                raise serializers.ValidationError("event_id must be a valid UUIDv4 string.")
        except (ValueError, AttributeError, TypeError):
            raise serializers.ValidationError("event_id must be a valid UUID string.")
        return normalized

    def validate(self, data):
        # 1. Resolve and validate producer_app / source_app
        prod = data.get("producer_app")
        src = data.get("source_app")

        if not prod and not src:
            raise serializers.ValidationError(
                {"producer_app": "Either 'producer_app' or 'source_app' must be provided."}
            )

        if prod and src:
            norm_prod = normalize_source_app(prod)
            norm_src = normalize_source_app(src)
            if norm_prod != norm_src:
                raise serializers.ValidationError(
                    {"producer_app": f"Contradictory producer_app ('{prod}') and source_app ('{src}') aliases."}
                )
            canonical_app = norm_prod
        else:
            raw_app = prod or src
            canonical_app = normalize_source_app(raw_app)

        error_field = "producer_app" if prod else "source_app"
        if canonical_app not in CANONICAL_SOURCE_APPS:
            raise serializers.ValidationError(
                {
                    error_field: f"Unsupported {error_field} '{raw_app}'. Must be one of: {', '.join(sorted(RECOGNIZED_SOURCE_APPS))}"
                }
            )

        data["canonical_producer_app"] = canonical_app
        data["source_app"] = canonical_app
        data["producer_app"] = canonical_app

        # 2. Validate correlation_id
        corr = data.get("correlation_id")
        event_version = data.get("event_version")
        subject = data.get("subject")

        # Canonical Bop Clients event (emits producer_app=bopclients or subject or v2) requires correlation_id
        is_canonical_bopclients = (prod is not None) or (subject is not None) or (event_version == 2)
        if is_canonical_bopclients and canonical_app == "bopclients":
            if not corr or not str(corr).strip():
                raise serializers.ValidationError(
                    {"correlation_id": "Canonical Bop Clients event requires non-empty correlation_id."}
                )

        if corr and str(corr).strip():
            try:
                u = uuid.UUID(str(corr).strip())
                if u.version != 4:
                    raise serializers.ValidationError(
                        {"correlation_id": "correlation_id must be a valid UUIDv4 string."}
                    )
                data["correlation_id"] = str(u)
            except (ValueError, AttributeError, TypeError):
                raise serializers.ValidationError(
                    {"correlation_id": "correlation_id must be a valid UUID string."}
                )
        else:
            data["correlation_id"] = ""

        # 3. Validate causation_id
        caus = data.get("causation_id")
        if caus is not None and str(caus).strip():
            try:
                u = uuid.UUID(str(caus).strip())
                if u.version != 4:
                    raise serializers.ValidationError(
                        {"causation_id": "causation_id must be a valid UUIDv4 string."}
                    )
                data["causation_id"] = str(u)
            except (ValueError, AttributeError, TypeError):
                raise serializers.ValidationError(
                    {"causation_id": "causation_id must be a valid UUID string."}
                )
        else:
            data["causation_id"] = None

        # 4. Validate metadata
        meta = data.get("metadata")
        if meta is None:
            data["metadata"] = {}
        elif not isinstance(meta, dict):
            raise serializers.ValidationError({"metadata": "metadata must be a JSON object."})

        # 5. Validate subject and resolve external_entity_id / external_entity_type
        ext_id = data.get("external_entity_id")
        ext_type = data.get("external_entity_type")

        if subject:
            subj_org = str(subject["bop_organization_id"])
            env_org = str(data["bop_organization_id"])
            if subj_org != env_org:
                raise serializers.ValidationError(
                    {"subject": f"Tenant mismatch: subject bop_organization_id '{subj_org}' does not match envelope '{env_org}'."}
                )

            subj_app = normalize_source_app(subject["application_id"])
            if subj_app != canonical_app:
                raise serializers.ValidationError(
                    {"subject": f"Application mismatch: subject application_id '{subject['application_id']}' does not match producer '{canonical_app}'."}
                )

            subj_entity_id = str(subject["entity_id"]).strip()
            if not subj_entity_id:
                raise serializers.ValidationError(
                    {"subject": "subject.entity_id cannot be empty or whitespace-only."}
                )
            if len(subj_entity_id) > 128:
                raise serializers.ValidationError(
                    {"subject": "subject.entity_id exceeds maximum length of 128 characters."}
                )

            subj_entity_type = str(subject["entity_type"]).strip().lower()

            if ext_id and str(ext_id).strip() != subj_entity_id:
                raise serializers.ValidationError(
                    {"external_entity_id": f"Conflict: external_entity_id '{ext_id}' does not match subject.entity_id '{subj_entity_id}'."}
                )

            if ext_type and str(ext_type).strip().lower() != subj_entity_type:
                raise serializers.ValidationError(
                    {"external_entity_type": f"Conflict: external_entity_type '{ext_type}' does not match subject.entity_type '{subj_entity_type}'."}
                )

            data["external_entity_id"] = subj_entity_id
            data["external_entity_type"] = subj_entity_type
        else:
            if ext_id:
                data["external_entity_id"] = str(ext_id).strip()
            if ext_type:
                data["external_entity_type"] = str(ext_type).strip().lower()

        # 6. Event type & version specific validation
        event_type = data["event_type"]
        resolved_version = event_version if event_version is not None else 1
        data["event_version"] = resolved_version
        payload = data.get("payload") or {}

        if event_type == "prospect.ready_for_crm":
            if resolved_version not in (1, 2):
                raise serializers.ValidationError(
                    {"event_version": f"Unsupported event_version {resolved_version} for 'prospect.ready_for_crm'. Supported versions: 1, 2."}
                )

            if subject:
                if subject["entity_type"] != "prospect":
                    raise serializers.ValidationError(
                        {"subject": f"prospect.ready_for_crm requires subject.entity_type='prospect', got '{subject['entity_type']}'."}
                    )
                if "prospect_id" in payload:
                    if str(payload["prospect_id"]) != str(subject["entity_id"]):
                        raise serializers.ValidationError(
                            {"subject": f"Subject entity_id '{subject['entity_id']}' does not match payload prospect_id '{payload['prospect_id']}'."}
                        )
                else:
                    raise serializers.ValidationError(
                        {"payload": "prospect.ready_for_crm requires 'prospect_id' in payload matching subject.entity_id."}
                    )

            if resolved_version == 2:
                # Prohibit PII keys
                pii_keys = set(payload.keys()) & PROHIBITED_PII_KEYS
                if pii_keys:
                    raise serializers.ValidationError(
                        {"payload": f"prospect.ready_for_crm v2 contains prohibited PII keys: {sorted(pii_keys)}."}
                    )

                # Reject unexpected fields
                extra_payload = set(payload.keys()) - ALLOWED_PAYLOAD_KEYS_PROSPECT_READY_FOR_CRM_V2
                if extra_payload:
                    raise serializers.ValidationError(
                        {"payload": f"prospect.ready_for_crm v2 contains unauthorized fields: {sorted(extra_payload)}."}
                    )

                # Required fields
                if not isinstance(payload.get("prospect_id"), str) or not payload["prospect_id"].strip():
                    raise serializers.ValidationError(
                        {"payload": "prospect.ready_for_crm v2 requires non-empty string 'prospect_id'."}
                    )
                if not isinstance(payload.get("company_name"), str) or not payload["company_name"].strip():
                    raise serializers.ValidationError(
                        {"payload": "prospect.ready_for_crm v2 requires non-empty string 'company_name'."}
                    )

                # Optional field constraints
                lead_score = payload.get("lead_score")
                if lead_score is not None:
                    if not isinstance(lead_score, (int, float)) or isinstance(lead_score, bool):
                        raise serializers.ValidationError(
                            {"payload": "prospect.ready_for_crm v2 'lead_score' must be numeric if provided."}
                        )
                    if lead_score < 0 or lead_score > 100:
                        raise serializers.ValidationError(
                            {"payload": f"prospect.ready_for_crm v2 'lead_score' must be between 0 and 100, got {lead_score}."}
                        )

                priority = payload.get("priority")
                if priority is not None and (not isinstance(priority, str) or not priority.strip()):
                    raise serializers.ValidationError(
                        {"payload": "prospect.ready_for_crm v2 'priority' must be non-empty string if provided."}
                    )

                for str_fld in ("website", "industry", "location", "campaign_id", "source", "prospect_url", "handoff_requested_by", "handoff_requested_at", "recommended_action"):
                    v = payload.get(str_fld)
                    if v is not None and not isinstance(v, str):
                        raise serializers.ValidationError(
                            {"payload": f"prospect.ready_for_crm v2 '{str_fld}' must be a string if provided."}
                        )

                hr = payload.get("human_review_required")
                if hr is not None and not isinstance(hr, bool):
                    raise serializers.ValidationError(
                        {"payload": "prospect.ready_for_crm v2 'human_review_required' must be boolean if provided."}
                    )

            elif resolved_version == 1 and (event_version is not None or subject is not None):
                extra_v1 = set(payload.keys()) - ALLOWED_PAYLOAD_KEYS_PROSPECT_READY_FOR_CRM_V1
                if extra_v1:
                    raise serializers.ValidationError(
                        {"payload": f"prospect.ready_for_crm v1 contains unauthorized fields: {sorted(extra_v1)}."}
                    )
                if not isinstance(payload.get("prospect_id"), str) or not payload["prospect_id"].strip():
                    raise serializers.ValidationError(
                        {"payload": "prospect.ready_for_crm v1 requires non-empty string 'prospect_id'."}
                    )
                lead_score = payload.get("lead_score")
                if not isinstance(lead_score, (int, float)) or isinstance(lead_score, bool):
                    raise serializers.ValidationError(
                        {"payload": "prospect.ready_for_crm v1 requires numeric 'lead_score'."}
                    )
                if lead_score < 0 or lead_score > 100:
                    raise serializers.ValidationError(
                        {"payload": f"prospect.ready_for_crm v1 'lead_score' must be between 0 and 100, got {lead_score}."}
                    )
                if not isinstance(payload.get("priority"), str) or not payload["priority"].strip():
                    raise serializers.ValidationError(
                        {"payload": "prospect.ready_for_crm v1 requires non-empty string 'priority'."}
                    )
                if not isinstance(payload.get("recommended_action"), str) or not payload["recommended_action"].strip():
                    raise serializers.ValidationError(
                        {"payload": "prospect.ready_for_crm v1 requires non-empty string 'recommended_action'."}
                    )
                if not isinstance(payload.get("human_review_required"), bool):
                    raise serializers.ValidationError(
                        {"payload": "prospect.ready_for_crm v1 requires boolean 'human_review_required'."}
                    )

        return data
