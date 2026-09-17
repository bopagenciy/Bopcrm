from typing import Optional

CANONICAL_SOURCE_APPS = frozenset({
    "bopclients",
    "bop_social",
    "bop_erp",
    "bop_chatbot",
    "bop_assistant",
})

SOURCE_APP_ALIASES = {
    "bop_clients": "bopclients",
    "bopsocial": "bop_social",
    "boperp": "bop_erp",
    "bopchatbot": "bop_chatbot",
    "bopassistant": "bop_assistant",
}

RECOGNIZED_SOURCE_APPS = frozenset(CANONICAL_SOURCE_APPS | set(SOURCE_APP_ALIASES.keys()))

BOP_SOURCE_APP_CHOICES = tuple(
    (app, app) for app in sorted(RECOGNIZED_SOURCE_APPS)
)


def normalize_source_app(value: Optional[str]) -> str:
    """
    Normalize any recognized Bop source application name or legacy alias
    to its canonical identifier (e.g. 'bop_clients' -> 'bopclients').
    """
    if not value or not isinstance(value, str):
        return ""
    cleaned = value.strip().lower()
    return SOURCE_APP_ALIASES.get(cleaned, cleaned)


ALLOWED_TOP_LEVEL_KEYS = frozenset({
    "event_id",
    "event_type",
    "event_version",
    "occurred_at",
    "producer_app",
    "source_app",
    "bop_organization_id",
    "subject",
    "correlation_id",
    "causation_id",
    "payload",
    "metadata",
    "external_entity_id",
    "external_entity_type",
    "idempotency_key",
})

ALLOWED_PAYLOAD_KEYS_PROSPECT_READY_FOR_CRM_V2 = frozenset({
    "prospect_id",
    "company_name",
    "website",
    "industry",
    "location",
    "lead_score",
    "priority",
    "campaign_id",
    "signal_summary",
    "source",
    "prospect_url",
    "handoff_requested_by",
    "handoff_requested_at",
    "recommended_action",
    "human_review_required",
})

ALLOWED_PAYLOAD_KEYS_PROSPECT_READY_FOR_CRM_V1 = frozenset({
    "prospect_id",
    "lead_score",
    "priority",
    "recommended_action",
    "human_review_required",
})

PROHIBITED_PII_KEYS = frozenset({
    "email",
    "phone",
    "first_name",
    "last_name",
    "contact_name",
    "primary_contact",
})
