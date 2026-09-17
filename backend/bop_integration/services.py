import logging
from typing import Any, Dict, Optional, Tuple

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.functions import Lower
from django.utils import timezone

from accounts.models import Account
from bop_integration.models import BopEventLog, ExternalEntityMap
from common.tasks import set_rls_context
from common.utils import INDCHOICES, LEAD_SOURCE, PRIORITY_CHOICE
from leads.models import Lead

logger = logging.getLogger(__name__)

# Precompute choice lookup maps for case-insensitive normalization
_INDCHOICES_MAP = {c[0].strip().upper(): c[0] for c in INDCHOICES}
_LEAD_SOURCE_MAP = {c[0].strip().lower(): c[0] for c in LEAD_SOURCE}
_PRIORITY_MAP = {c[0].strip().upper(): c[0] for c in PRIORITY_CHOICE}


def ingest_prospect_ready_for_crm(event_log: BopEventLog) -> Dict[str, Any]:
    """
    Ingest a canonical Bop Clients 'prospect.ready_for_crm' v2 event into native BottleCRM entities.

    Transactional & Idempotency guarantees:
    - Verifies event_type == 'prospect.ready_for_crm' and event_version == 2
    - Scoped strictly to event_log.org under explicit RLS context
    - Deduplicates Account by Lower('name') within tenant org (backfills empty fields only)
    - Deduplicates Lead via canonical ExternalEntityMap (source_app='bopclients', entity_type='prospect', entity_id=prospect_id)
    - Never fabricates contact PII (first_name, last_name, email, phone remain None)
    - Stores lossless bop_clients metadata in Lead.custom_fields['bop_clients']
    - Atomic execution: Rolls back entity changes if anything fails while preserving BopEventLog.status='failed'
    """
    if event_log.event_type != "prospect.ready_for_crm":
        raise ValueError(f"Unsupported event_type '{event_log.event_type}' for prospect ingestion service.")

    if event_log.event_version != 2:
        raise ValueError(f"Unsupported event_version '{event_log.event_version}' for prospect ingestion service (expected 2).")

    org = event_log.org
    if not org:
        raise ValueError("BopEventLog is missing required organization context.")

    payload = event_log.payload or {}
    prospect_id = payload.get("prospect_id") or event_log.external_entity_id
    if not prospect_id or not str(prospect_id).strip():
        raise ValueError("prospect_id is missing or empty in event payload.")

    prospect_id = str(prospect_id).strip()
    company_name = (payload.get("company_name") or "").strip()
    if not company_name:
        raise ValueError("company_name is required in payload for prospect ingestion.")

    # Explicit RLS context for tenant isolation
    set_rls_context(org.id)

    # 1. Check if an ExternalEntityMap already exists for this prospect in this org
    existing_map = ExternalEntityMap.objects.filter(
        org=org,
        source_app="bopclients",
        external_entity_type="prospect",
        external_entity_id=prospect_id,
    ).select_related("content_type").first()

    if existing_map:
        lead = existing_map.content_object
        account = Account.objects.filter(org=org, name__iexact=company_name).first()
        return {
            "account": account,
            "lead": lead,
            "external_map": existing_map,
            "created": False,
        }

    # 2. Extract and prepare business field values
    website = (payload.get("website") or "").strip() or None
    raw_industry = (payload.get("industry") or "").strip() or None
    normalized_industry = (_INDCHOICES_MAP.get(raw_industry.upper()) or raw_industry[:255]) if raw_industry else None
    raw_location = (payload.get("location") or "").strip() or None
    lead_score = payload.get("lead_score")
    raw_priority = (payload.get("priority") or "").strip() or None
    normalized_priority = (_PRIORITY_MAP.get(raw_priority.upper()) or raw_priority[:255]) if raw_priority else None
    campaign_id = (payload.get("campaign_id") or "").strip() or None
    signal_summary = payload.get("signal_summary")
    raw_source = (payload.get("source") or "").strip() or None
    normalized_source = (_LEAD_SOURCE_MAP.get(raw_source.lower()) or raw_source[:255]) if raw_source else "other"
    prospect_url = (payload.get("prospect_url") or "").strip() or None
    handoff_by = (payload.get("handoff_requested_by") or "").strip() or None
    handoff_at = (payload.get("handoff_requested_at") or "").strip() or None
    recommended_action = (payload.get("recommended_action") or "").strip() or None
    human_review = bool(payload.get("human_review_required", False))

    # Lossless namespaced custom fields dictionary
    bop_clients_data = {
        "prospect_id": prospect_id,
        "lead_score": lead_score,
        "priority": raw_priority,
        "campaign_id": campaign_id,
        "signal_summary": signal_summary,
        "source": raw_source,
        "prospect_url": prospect_url,
        "handoff_requested_by": handoff_by,
        "handoff_requested_at": handoff_at,
        "recommended_action": recommended_action,
        "human_review_required": human_review,
        "location": raw_location,
    }

    # Build description notes for sales rep
    desc_lines = []
    if recommended_action:
        desc_lines.append(f"Recommended Action: {recommended_action}")
    if signal_summary:
        if isinstance(signal_summary, (dict, list)):
            import json
            desc_lines.append(f"Signal Summary: {json.dumps(signal_summary)}")
        else:
            desc_lines.append(f"Signal Summary: {signal_summary}")
    if prospect_url:
        desc_lines.append(f"Prospect URL: {prospect_url}")
    description_note = "\n".join(desc_lines) if desc_lines else None

    # 3. Atomic Entity Creation
    with transaction.atomic():
        # A. Account Matching & Creation (Protected against concurrent races)
        account = Account.objects.filter(org=org, name__iexact=company_name).first()
        if not account:
            try:
                # Savepoint to protect against concurrent unique_account_name_per_org race
                with transaction.atomic():
                    account = Account.objects.create(
                        org=org,
                        name=company_name[:255],
                        website=website[:255] if website else None,
                        industry=normalized_industry,
                        address_line=raw_location[:255] if raw_location else None,
                        description=description_note,
                        is_active=True,
                    )
            except IntegrityError:
                # Concurrent worker created account with same name (case-insensitive)
                account = Account.objects.filter(org=org, name__iexact=company_name).first()
                if not account:
                    raise

        # Backfill empty fields only; do not overwrite existing non-null data
        update_fields = []
        if not account.website and website:
            account.website = website[:255]
            update_fields.append("website")
        if not account.industry and normalized_industry:
            account.industry = normalized_industry
            update_fields.append("industry")
        if not account.address_line and raw_location:
            account.address_line = raw_location[:255]
            update_fields.append("address_line")
        if not account.description and description_note:
            account.description = description_note
            update_fields.append("description")
        if update_fields:
            account.save(update_fields=update_fields)

        # B. Lead Creation
        # Zero contact PII: first_name, last_name, email, phone remain None
        lead = Lead.objects.create(
            org=org,
            company_name=company_name[:255],
            title=f"Prospect: {company_name}"[:255],
            status="assigned",
            source=normalized_source or "other",
            industry=normalized_industry,
            website=website[:255] if website else None,
            address_line=raw_location[:255] if raw_location else None,
            description=description_note,
            custom_fields={"bop_clients": bop_clients_data},
            first_name=None,
            last_name=None,
            email=None,
            phone=None,
            is_active=True,
        )

        # C. ExternalEntityMap Creation
        lead_content_type = ContentType.objects.get_for_model(Lead)
        try:
            with transaction.atomic():
                external_map = ExternalEntityMap.objects.create(
                    org=org,
                    source_app="bopclients",
                    external_entity_type="prospect",
                    external_entity_id=prospect_id,
                    content_type=lead_content_type,
                    object_id=lead.id,
                )
        except IntegrityError:
            # Concurrent worker created mapping for this prospect_id
            external_map = ExternalEntityMap.objects.filter(
                org=org,
                source_app="bopclients",
                external_entity_type="prospect",
                external_entity_id=prospect_id,
            ).first()
            if not external_map:
                raise
            return {
                "account": account,
                "lead": external_map.content_object,
                "external_map": external_map,
                "created": False,
            }

        return {
            "account": account,
            "lead": lead,
            "external_map": external_map,
            "created": True,
        }
