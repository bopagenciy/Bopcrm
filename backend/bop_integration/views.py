import json
import logging
from django.db import IntegrityError
from django.db.models import Q
from django.utils import timezone
from rest_framework import exceptions, parsers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from common.models import Org
from common.pat_auth import PATAuthentication
from common.tasks import clear_rls_context, set_rls_context
from bop_integration.models import BopEventLog
from bop_integration.permissions import HasBopEventGatewayScope
from bop_integration.serializers import BopEventEnvelopeSerializer

logger = logging.getLogger(__name__)

MAX_PAYLOAD_BYTES = 1_048_576  # 1 MB maximum payload limit


class PayloadTooLarge(exceptions.APIException):
    status_code = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    default_detail = "Request payload exceeds maximum allowed size of 1MB."
    default_code = "payload_too_large"


class BoundedJSONParser(parsers.JSONParser):
    """
    Hard-bounded JSON parser enforcing a strict 1 MB maximum payload limit.

    Protects against:
    - Missing Content-Length header with unbounded body stream
    - Malformed Content-Length header
    - Spoofed Content-Length header (e.g. claims 100 bytes, sends 2 MB)
    - Legitimate Content-Length > 1 MB
    """

    def parse(self, stream, media_type=None, parser_context=None):
        parser_context = parser_context or {}
        request = parser_context.get("request")

        if request is not None:
            content_length = request.META.get("CONTENT_LENGTH")
            if content_length not in (None, ""):
                try:
                    cl = int(content_length)
                    if cl < 0:
                        raise exceptions.ValidationError({"detail": "Malformed Content-Length header."})
                    if cl > MAX_PAYLOAD_BYTES:
                        raise PayloadTooLarge()
                except (ValueError, TypeError):
                    raise exceptions.ValidationError({"detail": "Malformed Content-Length header."})

        data = stream.read(MAX_PAYLOAD_BYTES + 1)
        if len(data) > MAX_PAYLOAD_BYTES:
            raise PayloadTooLarge()

        if not data:
            return {}

        encoding = parser_context.get("encoding", "utf-8") or "utf-8"
        try:
            decoded = data.decode(encoding)
            return json.loads(decoded)
        except UnicodeDecodeError as exc:
            raise exceptions.ParseError(f"Unicode decode error: {exc}")
        except json.JSONDecodeError as exc:
            raise exceptions.ParseError(f"JSON parse error: {exc}")


class BopEventGatewayView(APIView):
    """
    Secure generic event ingestion gateway for Bop Universe applications.

    POST /api/integrations/bop/v1/events/

    Enforces:
    - PAT authentication
    - Strict scope boundaries ('integrations:write' or '*:write'; rejects empty, read-only, unrelated)
    - Hard bounded 1MB payload enforcement
    - Organization cross-match validation
    - Idempotent BopEventLog persistence under strict PostgreSQL RLS context
    - Safe audit logging without credential or payload leakage
    """

    authentication_classes = [PATAuthentication]
    permission_classes = [IsAuthenticated, HasBopEventGatewayScope]
    parser_classes = [BoundedJSONParser]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        content_length = request.META.get("CONTENT_LENGTH")
        if content_length not in (None, ""):
            try:
                cl = int(content_length)
                if cl < 0:
                    raise exceptions.ValidationError({"detail": "Malformed Content-Length header."})
                if cl > MAX_PAYLOAD_BYTES:
                    raise PayloadTooLarge()
            except (ValueError, TypeError):
                raise exceptions.ValidationError({"detail": "Malformed Content-Length header."})

    def post(self, request, *args, **kwargs):
        # 1. Defense-in-depth payload size verification
        if hasattr(request, "_body") and len(request._body) > MAX_PAYLOAD_BYTES:
            raise PayloadTooLarge()

        # 2. Deserialization & validation
        serializer = BopEventEnvelopeSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        validated_data = serializer.validated_data
        bop_org_id = validated_data["bop_organization_id"]
        event_id = validated_data["event_id"]
        payload_source_app = validated_data["source_app"]

        # 3. Source Application Authenticity Enforcement (CRM-I1B.2)
        pat = getattr(request, "_pat", None) or getattr(request, "auth", None)
        pat_source_app = getattr(pat, "source_app", None) if pat else None
        if not pat_source_app:
            logger.warning(
                "Bop event gateway: token rejected (missing bound source_app) for event %s",
                event_id,
            )
            return Response(
                {"detail": "Authenticated token is not bound to a Bop source application."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if pat_source_app != payload_source_app:
            logger.warning(
                "Bop event gateway: source_app mismatch for event %s (token '%s' != payload '%s')",
                event_id,
                pat_source_app,
                payload_source_app,
            )
            return Response(
                {
                    "detail": f"Source application mismatch: token bound to '{pat_source_app}', cannot submit as '{payload_source_app}'."
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        # 4. Resolve bop_organization_id to target Org
        target_org = Org.objects.filter(bop_organization_id=bop_org_id, is_active=True).first()
        if not target_org:
            logger.warning("Bop event gateway: unknown or inactive bop_organization_id %s", bop_org_id)
            return Response(
                {"detail": "Unknown or inactive bop_organization_id."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 4. Organization Cross-Match Security Check (CRITICAL)
        # Authenticated PAT org must match resolved target_org
        authed_org = getattr(request, "org", None)
        if not authed_org or authed_org.id != target_org.id:
            logger.warning(
                "Bop event gateway: org mismatch for event %s (PAT org %s != target org %s)",
                event_id,
                getattr(authed_org, "id", None),
                target_org.id,
            )
            return Response(
                {
                    "detail": "Organization mismatch: authenticated token does not belong to the target bop_organization_id."
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        # 5. Tenant-Scoped Ingestion & Idempotency Check under RLS Context
        source_app = validated_data["source_app"]
        event_type = validated_data["event_type"]
        external_entity_id = validated_data.get("external_entity_id") or ""
        idempotency_key = validated_data.get("idempotency_key") or ""
        payload = validated_data.get("payload") or {}
        occurred_at = validated_data.get("occurred_at") or timezone.now()

        set_rls_context(target_org.id)
        try:
            # Query existing log under tenant RLS context
            duplicate_filter = Q(event_id=event_id)
            if idempotency_key:
                duplicate_filter |= Q(idempotency_key=idempotency_key)

            existing_log = BopEventLog.objects.filter(org=target_org).filter(duplicate_filter).first()
            if existing_log:
                logger.info(
                    "Bop event gateway: duplicate event %s (source=%s) for org %s",
                    event_id,
                    source_app,
                    target_org.id,
                )
                return Response(
                    {
                        "status": "duplicate",
                        "event_id": event_id,
                        "processed": False,
                    },
                    status=status.HTTP_200_OK,
                )

            try:
                BopEventLog.objects.create(
                    org=target_org,
                    event_id=event_id,
                    source_app=source_app,
                    event_type=event_type,
                    external_entity_id=external_entity_id,
                    idempotency_key=idempotency_key,
                    payload=payload,
                    status="received",
                    received_at=occurred_at,
                )
                logger.info(
                    "Bop event gateway: received event %s (type=%s, source=%s) for org %s",
                    event_id,
                    event_type,
                    source_app,
                    target_org.id,
                )
                return Response(
                    {
                        "status": "received",
                        "event_id": event_id,
                        "processed": False,
                    },
                    status=status.HTTP_201_CREATED,
                )
            except IntegrityError:
                # Handle concurrent duplicate ingestion race condition gracefully
                logger.info(
                    "Bop event gateway: concurrent duplicate race for event %s for org %s",
                    event_id,
                    target_org.id,
                )
                return Response(
                    {
                        "status": "duplicate",
                        "event_id": event_id,
                        "processed": False,
                    },
                    status=status.HTTP_200_OK,
                )
        finally:
            clear_rls_context()

