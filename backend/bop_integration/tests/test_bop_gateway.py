import datetime
import json
import uuid
from unittest import mock
from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError, connection
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import Account
from bop_integration.models import BopEventLog
from common.models import Org, PersonalAccessToken, Profile, User
from common.tasks import clear_rls_context, set_rls_context
from contacts.models import Contact
from leads.models import Lead
from opportunity.models import Opportunity


class BopEventGatewayTestCase(TestCase):
    """
    Comprehensive integration and security tests for Phase CRM-I1B:
    Secure Bop Event Gateway API endpoint (POST /api/integrations/bop/v1/events/).
    """

    def setUp(self):
        # Create Org A and Org B with bop_organization_id UUIDs
        self.bop_org_id_a = uuid.uuid4()
        self.bop_org_id_b = uuid.uuid4()

        self.org_a = Org.objects.create(name="Gateway Org A", bop_organization_id=self.bop_org_id_a)
        self.org_b = Org.objects.create(name="Gateway Org B", bop_organization_id=self.bop_org_id_b)

        # Users and profiles
        uid_a = uuid.uuid4().hex[:8]
        uid_b = uuid.uuid4().hex[:8]
        self.user_a = User.objects.create_user(email=f"admin_gw_a_{uid_a}@test.com", password="pass")
        self.user_b = User.objects.create_user(email=f"admin_gw_b_{uid_b}@test.com", password="pass")

        self.profile_a = Profile.objects.create(user=self.user_a, org=self.org_a, role="ADMIN")
        self.profile_b = Profile.objects.create(user=self.user_b, org=self.org_b, role="ADMIN")

        # Personal Access Tokens bound to specific Bop source apps (CRM-I1B.2)
        self.raw_pat_a, self.pat_a = PersonalAccessToken.generate(
            profile=self.profile_a,
            name="Org A PAT",
            scopes=["integrations:write"],
            source_app="bop_clients",
        )
        self.raw_pat_b, self.pat_b = PersonalAccessToken.generate(
            profile=self.profile_b,
            name="Org B PAT",
            scopes=["integrations:write"],
            source_app="bop_erp",
        )

        self.client_a = APIClient()
        self.client_a.credentials(HTTP_AUTHORIZATION=f"Bearer {self.raw_pat_a}")

        self.client_b = APIClient()
        self.client_b.credentials(HTTP_AUTHORIZATION=f"Bearer {self.raw_pat_b}")

        # Baseline counts for entity immutability checks
        set_rls_context(self.org_a.id)
        self.initial_leads_count = Lead.objects.count()
        self.initial_accounts_count = Account.objects.count()
        self.initial_contacts_count = Contact.objects.count()
        self.initial_opps_count = Opportunity.objects.count()
        clear_rls_context()

    def tearDown(self):
        clear_rls_context()
        super().tearDown()

    def test_a_org_a_pat_and_org_a_bop_org_id_accepted(self):
        """A. Org A PAT + Org A bop_organization_id -> accepted (201 Created)."""
        event_uuid = str(uuid.uuid4())
        payload = {
            "event_id": event_uuid,
            "event_type": "prospect.ready_for_crm",
            "source_app": "bop_clients",
            "bop_organization_id": str(self.bop_org_id_a),
            "payload": {"score": 90},
        }
        res = self.client_a.post("/api/integrations/bop/v1/events/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data["status"], "received")
        self.assertEqual(res.data["event_id"], event_uuid)
        self.assertFalse(res.data["processed"])

    def test_b_org_a_pat_and_org_b_bop_org_id_forbidden(self):
        """B. Org A PAT + Org B bop_organization_id -> 403 Forbidden (no BopEventLog created)."""
        event_uuid = str(uuid.uuid4())
        payload = {
            "event_id": event_uuid,
            "event_type": "prospect.ready_for_crm",
            "source_app": "bop_clients",
            "bop_organization_id": str(self.bop_org_id_b),  # Org B!
            "payload": {"score": 90},
        }
        res = self.client_a.post("/api/integrations/bop/v1/events/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("Organization mismatch", str(res.data))

        # Verify no BopEventLog was created under Org B or Org A
        set_rls_context(self.org_b.id)
        self.assertEqual(BopEventLog.objects.filter(event_id=event_uuid).count(), 0)
        clear_rls_context()

    def test_c_invalid_token_rejected(self):
        """C. Invalid token -> rejected."""
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION="Bearer bcrm_pat_invalidtoken123456789")
        payload = {
            "event_id": str(uuid.uuid4()),
            "event_type": "prospect.ready_for_crm",
            "source_app": "bop_clients",
            "bop_organization_id": str(self.bop_org_id_a),
        }
        res = client.post("/api/integrations/bop/v1/events/", payload, format="json")
        self.assertIn(res.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_d_no_token_rejected(self):
        """D. No token -> rejected."""
        client = APIClient()
        payload = {
            "event_id": str(uuid.uuid4()),
            "event_type": "prospect.ready_for_crm",
            "source_app": "bop_clients",
            "bop_organization_id": str(self.bop_org_id_a),
        }
        res = client.post("/api/integrations/bop/v1/events/", payload, format="json")
        self.assertIn(res.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_e_unknown_bop_organization_id_rejected(self):
        """E. Unknown bop_organization_id -> safe 400 rejection."""
        payload = {
            "event_id": str(uuid.uuid4()),
            "event_type": "prospect.ready_for_crm",
            "source_app": "bop_clients",
            "bop_organization_id": str(uuid.uuid4()),  # Random unmapped UUID
        }
        res = self.client_a.post("/api/integrations/bop/v1/events/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Unknown or inactive bop_organization_id", str(res.data))

    def test_f_valid_event_creates_bop_event_log(self):
        """F. Valid event creates one BopEventLog inside correct tenant."""
        raw_social, _ = PersonalAccessToken.generate(
            profile=self.profile_a,
            name="Org A Social PAT",
            scopes=["integrations:write"],
            source_app="bop_social",
        )
        client_social = APIClient()
        client_social.credentials(HTTP_AUTHORIZATION=f"Bearer {raw_social}")

        event_uuid = str(uuid.uuid4())
        payload = {
            "event_id": event_uuid,
            "event_type": "social.message.received",
            "source_app": "bop_social",
            "bop_organization_id": str(self.bop_org_id_a),
            "external_entity_id": "ext-social-42",
            "payload": {"text": "hello"},
        }
        res = client_social.post("/api/integrations/bop/v1/events/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        set_rls_context(self.org_a.id)
        log = BopEventLog.objects.filter(event_id=event_uuid).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.org, self.org_a)
        self.assertEqual(log.source_app, "bop_social")
        self.assertEqual(log.status, "received")
        clear_rls_context()

    def test_g_duplicate_event_id_idempotency(self):
        """G. Duplicate event_id creates no second row (200 OK duplicate response)."""
        event_uuid = str(uuid.uuid4())
        payload = {
            "event_id": event_uuid,
            "event_type": "prospect.ready_for_crm",
            "source_app": "bop_clients",
            "bop_organization_id": str(self.bop_org_id_a),
        }
        res1 = self.client_a.post("/api/integrations/bop/v1/events/", payload, format="json")
        self.assertEqual(res1.status_code, status.HTTP_201_CREATED)

        # Duplicate submission
        res2 = self.client_a.post("/api/integrations/bop/v1/events/", payload, format="json")
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        self.assertEqual(res2.data["status"], "duplicate")

        set_rls_context(self.org_a.id)
        self.assertEqual(BopEventLog.objects.filter(event_id=event_uuid).count(), 1)
        clear_rls_context()

    def test_h_duplicate_idempotency_key_idempotency(self):
        """H. Duplicate idempotency_key creates no second row."""
        idem_key = f"idem-{uuid.uuid4()}"
        payload1 = {
            "event_id": str(uuid.uuid4()),
            "event_type": "prospect.ready_for_crm",
            "source_app": "bop_clients",
            "bop_organization_id": str(self.bop_org_id_a),
            "idempotency_key": idem_key,
        }
        res1 = self.client_a.post("/api/integrations/bop/v1/events/", payload1, format="json")
        self.assertEqual(res1.status_code, status.HTTP_201_CREATED)

        payload2 = {
            "event_id": str(uuid.uuid4()),  # Different event_id, same idempotency_key
            "event_type": "prospect.ready_for_crm",
            "source_app": "bop_clients",
            "bop_organization_id": str(self.bop_org_id_a),
            "idempotency_key": idem_key,
        }
        res2 = self.client_a.post("/api/integrations/bop/v1/events/", payload2, format="json")
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        self.assertEqual(res2.data["status"], "duplicate")

        set_rls_context(self.org_a.id)
        self.assertEqual(BopEventLog.objects.filter(idempotency_key=idem_key).count(), 1)
        clear_rls_context()

    def test_i_org_a_cannot_observe_org_b_event_logs(self):
        """I. Org A cannot observe Org B event logs under RLS."""
        event_b = str(uuid.uuid4())
        payload_b = {
            "event_id": event_b,
            "event_type": "erp.customer.updated",
            "source_app": "bop_erp",
            "bop_organization_id": str(self.bop_org_id_b),
        }
        res = self.client_b.post("/api/integrations/bop/v1/events/", payload_b, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        # Query under Org A context
        set_rls_context(self.org_a.id)
        self.assertEqual(BopEventLog.objects.filter(event_id=event_b).count(), 0)
        clear_rls_context()

    def test_j_no_tenant_context_exposes_zero_event_rows(self):
        """J. No tenant context exposes zero event rows (fail-closed)."""
        raw_asst, _ = PersonalAccessToken.generate(
            profile=self.profile_a,
            name="Org A Asst PAT",
            scopes=["integrations:write"],
            source_app="bop_assistant",
        )
        client_asst = APIClient()
        client_asst.credentials(HTTP_AUTHORIZATION=f"Bearer {raw_asst}")

        event_a = str(uuid.uuid4())
        payload_a = {
            "event_id": event_a,
            "event_type": "bop.assistant.task",
            "source_app": "bop_assistant",
            "bop_organization_id": str(self.bop_org_id_a),
        }
        client_asst.post("/api/integrations/bop/v1/events/", payload_a, format="json")

        clear_rls_context()
        self.assertEqual(BopEventLog.objects.count(), 0)

    def test_k_unsupported_source_app_rejected(self):
        """K. Unsupported source_app is rejected with 400."""
        payload = {
            "event_id": str(uuid.uuid4()),
            "event_type": "unsupported.event",
            "source_app": "malicious_app",
            "bop_organization_id": str(self.bop_org_id_a),
        }
        res = self.client_a.post("/api/integrations/bop/v1/events/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Unsupported source_app", str(res.data))

    def test_l_no_business_entity_creation_guarantee(self):
        """Verify explicitly that no Lead, Account, Contact, or Opportunity was created by the gateway."""
        # Submit valid events across multiple source apps
        for app in ["bop_clients", "bop_social", "bop_erp", "bop_chatbot", "bop_assistant"]:
            raw_token, _ = PersonalAccessToken.generate(
                profile=self.profile_a,
                name=f"Org A {app} PAT",
                scopes=["integrations:write"],
                source_app=app,
            )
            app_client = APIClient()
            app_client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw_token}")
            payload = {
                "event_id": str(uuid.uuid4()),
                "event_type": "prospect.ready_for_crm",
                "source_app": app,
                "bop_organization_id": str(self.bop_org_id_a),
                "payload": {"email": "test@test.com", "name": "No Entity Test"},
            }
            res = app_client.post("/api/integrations/bop/v1/events/", payload, format="json")
            self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        # Assert zero business entities created
        set_rls_context(self.org_a.id)
        self.assertEqual(Lead.objects.count(), self.initial_leads_count)
        self.assertEqual(Account.objects.count(), self.initial_accounts_count)
        self.assertEqual(Contact.objects.count(), self.initial_contacts_count)
        self.assertEqual(Opportunity.objects.count(), self.initial_opps_count)
        clear_rls_context()

    # =========================================================================
    # 1. PAT SCOPE HARDENING TESTS
    # =========================================================================

    def test_pat_empty_scope_rejected(self):
        """Unrestricted/empty scopes ([]) MUST be rejected by the Bop event gateway."""
        raw_pat, _ = PersonalAccessToken.generate(
            profile=self.profile_a, name="Empty Scope PAT", scopes=[]
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw_pat}")
        payload = {
            "event_id": str(uuid.uuid4()),
            "event_type": "prospect.ready_for_crm",
            "source_app": "bop_clients",
            "bop_organization_id": str(self.bop_org_id_a),
        }
        res = client.post("/api/integrations/bop/v1/events/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("scope", str(res.data).lower())

    def test_pat_readonly_scope_rejected(self):
        """Read-only scope ('integrations:read') MUST be rejected by the gateway."""
        raw_pat, _ = PersonalAccessToken.generate(
            profile=self.profile_a, name="Readonly Scope PAT", scopes=["integrations:read"]
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw_pat}")
        payload = {
            "event_id": str(uuid.uuid4()),
            "event_type": "prospect.ready_for_crm",
            "source_app": "bop_clients",
            "bop_organization_id": str(self.bop_org_id_a),
        }
        res = client.post("/api/integrations/bop/v1/events/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_pat_unrelated_scope_rejected(self):
        """Unrelated scope (e.g., 'leads:write') MUST be rejected by the gateway."""
        raw_pat, _ = PersonalAccessToken.generate(
            profile=self.profile_a,
            name="Leads Scope PAT",
            scopes=["leads:write"],
            source_app="bop_clients",
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw_pat}")
        payload = {
            "event_id": str(uuid.uuid4()),
            "event_type": "prospect.ready_for_crm",
            "source_app": "bop_clients",
            "bop_organization_id": str(self.bop_org_id_a),
        }
        res = client.post("/api/integrations/bop/v1/events/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_pat_wildcard_write_scope_accepted(self):
        """Super-scope '*:write' is accepted for event ingestion."""
        raw_pat, _ = PersonalAccessToken.generate(
            profile=self.profile_a,
            name="Wildcard Write PAT",
            scopes=["*:write"],
            source_app="bop_clients",
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw_pat}")
        payload = {
            "event_id": str(uuid.uuid4()),
            "event_type": "prospect.ready_for_crm",
            "source_app": "bop_clients",
            "bop_organization_id": str(self.bop_org_id_a),
        }
        res = client.post("/api/integrations/bop/v1/events/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

    def test_pat_integrations_write_accepted(self):
        """Exact scope 'integrations:write' is accepted."""
        payload = {
            "event_id": str(uuid.uuid4()),
            "event_type": "prospect.ready_for_crm",
            "source_app": "bop_clients",
            "bop_organization_id": str(self.bop_org_id_a),
        }
        res = self.client_a.post("/api/integrations/bop/v1/events/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

    # =========================================================================
    # 2. PAT LIFECYCLE TESTS
    # =========================================================================

    def test_pat_lifecycle_revoked_rejected(self):
        """Revoked PAT must be rejected with 401/403."""
        raw_pat, pat = PersonalAccessToken.generate(
            profile=self.profile_a,
            name="Revoked PAT",
            scopes=["integrations:write"],
            source_app="bop_clients",
        )
        pat.revoked_at = timezone.now()
        pat.save()

        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw_pat}")
        payload = {
            "event_id": str(uuid.uuid4()),
            "event_type": "prospect.ready_for_crm",
            "source_app": "bop_clients",
            "bop_organization_id": str(self.bop_org_id_a),
        }
        res = client.post("/api/integrations/bop/v1/events/", payload, format="json")
        self.assertIn(res.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_pat_lifecycle_expired_rejected(self):
        """Expired PAT must be rejected with 401/403."""
        raw_pat, pat = PersonalAccessToken.generate(
            profile=self.profile_a,
            name="Expired PAT",
            scopes=["integrations:write"],
            expires_at=timezone.now() - datetime.timedelta(days=1),
            source_app="bop_clients",
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw_pat}")
        payload = {
            "event_id": str(uuid.uuid4()),
            "event_type": "prospect.ready_for_crm",
            "source_app": "bop_clients",
            "bop_organization_id": str(self.bop_org_id_a),
        }
        res = client.post("/api/integrations/bop/v1/events/", payload, format="json")
        self.assertIn(res.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_pat_lifecycle_inactive_owner_rejected(self):
        """PAT whose profile/user is inactive must be rejected."""
        inactive_user = User.objects.create_user(email=f"inactive_{uuid.uuid4().hex[:6]}@test.com", password="pass")
        inactive_profile = Profile.objects.create(user=inactive_user, org=self.org_a, is_active=False)
        raw_pat, _ = PersonalAccessToken.generate(
            profile=inactive_profile,
            name="Inactive Owner PAT",
            scopes=["integrations:write"],
            source_app="bop_clients",
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw_pat}")
        payload = {
            "event_id": str(uuid.uuid4()),
            "event_type": "prospect.ready_for_crm",
            "source_app": "bop_clients",
            "bop_organization_id": str(self.bop_org_id_a),
        }
        res = client.post("/api/integrations/bop/v1/events/", payload, format="json")
        self.assertIn(res.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_pat_lifecycle_malformed_rejected(self):
        """Malformed PAT header must be rejected."""
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION="Bearer malformed-garbage-token-without-prefix")
        payload = {
            "event_id": str(uuid.uuid4()),
            "event_type": "prospect.ready_for_crm",
            "source_app": "bop_clients",
            "bop_organization_id": str(self.bop_org_id_a),
        }
        res = client.post("/api/integrations/bop/v1/events/", payload, format="json")
        self.assertIn(res.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_pat_lifecycle_missing_rejected(self):
        """Missing PAT credentials must be rejected."""
        client = APIClient()
        payload = {
            "event_id": str(uuid.uuid4()),
            "event_type": "prospect.ready_for_crm",
            "source_app": "bop_clients",
            "bop_organization_id": str(self.bop_org_id_a),
        }
        res = client.post("/api/integrations/bop/v1/events/", payload, format="json")
        self.assertIn(res.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    # =========================================================================
    # 3. REQUEST SIZE ENFORCEMENT TESTS
    # =========================================================================

    def test_request_size_content_length_exceeds_1mb_rejected(self):
        """Explicit Content-Length > 1MB returns 413 Payload Too Large."""
        payload = {
            "event_id": str(uuid.uuid4()),
            "event_type": "prospect.ready_for_crm",
            "source_app": "bop_clients",
            "bop_organization_id": str(self.bop_org_id_a),
        }
        res = self.client_a.post(
            "/api/integrations/bop/v1/events/",
            data=json.dumps(payload),
            content_type="application/json",
            CONTENT_LENGTH="2000000",
        )
        self.assertEqual(res.status_code, status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)

    def test_request_size_malformed_content_length_rejected(self):
        """Malformed Content-Length header returns 400 Bad Request."""
        payload = {
            "event_id": str(uuid.uuid4()),
            "event_type": "prospect.ready_for_crm",
            "source_app": "bop_clients",
            "bop_organization_id": str(self.bop_org_id_a),
        }
        res = self.client_a.post(
            "/api/integrations/bop/v1/events/",
            data=json.dumps(payload),
            content_type="application/json",
            CONTENT_LENGTH="malformed_length",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_request_size_negative_content_length_rejected(self):
        """Negative Content-Length header returns 400 Bad Request."""
        payload = {
            "event_id": str(uuid.uuid4()),
            "event_type": "prospect.ready_for_crm",
            "source_app": "bop_clients",
            "bop_organization_id": str(self.bop_org_id_a),
        }
        res = self.client_a.post(
            "/api/integrations/bop/v1/events/",
            data=json.dumps(payload),
            content_type="application/json",
            CONTENT_LENGTH="-10",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_request_size_oversized_payload_body_rejected(self):
        """Payload body exceeding 1MB is rejected with 413 Payload Too Large."""
        large_padding = "x" * (1_048_576 + 500)
        payload = {
            "event_id": str(uuid.uuid4()),
            "event_type": "prospect.ready_for_crm",
            "source_app": "bop_clients",
            "bop_organization_id": str(self.bop_org_id_a),
            "payload": {"padding": large_padding},
        }
        res = self.client_a.post("/api/integrations/bop/v1/events/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)

    # =========================================================================
    # 4. ENVELOPE VALIDATION TESTS
    # =========================================================================

    def test_envelope_malformed_bop_organization_id_rejected(self):
        """Malformed bop_organization_id returns 400 Bad Request."""
        payload = {
            "event_id": str(uuid.uuid4()),
            "event_type": "prospect.ready_for_crm",
            "source_app": "bop_clients",
            "bop_organization_id": "not-a-valid-uuid",
        }
        res = self.client_a.post("/api/integrations/bop/v1/events/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("bop_organization_id", res.data)

    def test_envelope_unexpected_top_level_field_rejected(self):
        """Unexpected top-level fields return 400 Bad Request."""
        payload = {
            "event_id": str(uuid.uuid4()),
            "event_type": "prospect.ready_for_crm",
            "source_app": "bop_clients",
            "bop_organization_id": str(self.bop_org_id_a),
            "unauthorized_field": "injected_value",
        }
        res = self.client_a.post("/api/integrations/bop/v1/events/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("unauthorized_field", res.data)

    def test_envelope_malformed_event_id_rejected(self):
        """Malformed or empty event_id returns 400 Bad Request."""
        for bad_id in ["not-a-uuid", "", "12345"]:
            payload = {
                "event_id": bad_id,
                "event_type": "prospect.ready_for_crm",
                "source_app": "bop_clients",
                "bop_organization_id": str(self.bop_org_id_a),
            }
            res = self.client_a.post("/api/integrations/bop/v1/events/", payload, format="json")
            self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertIn("event_id", res.data)

    def test_envelope_payload_must_be_dict(self):
        """Payload field must be a JSON object/dict; primitives and lists are rejected with 400."""
        for invalid_payload in ["a plain string", [1, 2, 3], 42, True]:
            payload = {
                "event_id": str(uuid.uuid4()),
                "event_type": "prospect.ready_for_crm",
                "source_app": "bop_clients",
                "bop_organization_id": str(self.bop_org_id_a),
                "payload": invalid_payload,
            }
            res = self.client_a.post("/api/integrations/bop/v1/events/", payload, format="json")
            self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertIn("payload", res.data)

    def test_envelope_malformed_occurred_at_rejected(self):
        """Malformed occurred_at string returns 400 Bad Request."""
        payload = {
            "event_id": str(uuid.uuid4()),
            "event_type": "prospect.ready_for_crm",
            "source_app": "bop_clients",
            "bop_organization_id": str(self.bop_org_id_a),
            "occurred_at": "yesterday afternoon",
        }
        res = self.client_a.post("/api/integrations/bop/v1/events/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("occurred_at", res.data)

    def test_envelope_valid_occurred_at_accepted(self):
        """Valid ISO-8601 occurred_at is accepted."""
        event_uuid = str(uuid.uuid4())
        payload = {
            "event_id": event_uuid,
            "event_type": "prospect.ready_for_crm",
            "source_app": "bop_clients",
            "bop_organization_id": str(self.bop_org_id_a),
            "occurred_at": "2026-09-17T10:00:00Z",
        }
        res = self.client_a.post("/api/integrations/bop/v1/events/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

    def test_envelope_event_type_grammar_validation(self):
        """event_type must follow normalized namespaced dot notation."""
        # Valid namespaced formats
        valid_types = [
            "prospect.ready_for_crm",
            "social.message.received",
            "erp.customer.updated",
            "bop.chatbot.session_started",
        ]
        for v_type in valid_types:
            payload = {
                "event_id": str(uuid.uuid4()),
                "event_type": v_type,
                "source_app": "bop_clients",
                "bop_organization_id": str(self.bop_org_id_a),
            }
            res = self.client_a.post("/api/integrations/bop/v1/events/", payload, format="json")
            self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        # Invalid formats (no dot, double dot, spaces, special chars)
        invalid_types = [
            "singleword",
            "invalid..dot",
            ".leadingdot",
            "trailingdot.",
            "has space.event",
            "special$chars.event",
        ]
        for inv_type in invalid_types:
            payload = {
                "event_id": str(uuid.uuid4()),
                "event_type": inv_type,
                "source_app": "bop_clients",
                "bop_organization_id": str(self.bop_org_id_a),
            }
            res = self.client_a.post("/api/integrations/bop/v1/events/", payload, format="json")
            self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertIn("event_type", res.data)

    # =========================================================================
    # 5. IDEMPOTENCY RACE PATH PROOF
    # =========================================================================

    def test_idempotency_race_integrity_error_handled_gracefully(self):
        """
        Prove that when a concurrent insert causes a database unique-constraint
        collision (IntegrityError), the gateway:
        - does NOT return 500
        - returns duplicate response (200 OK, status='duplicate', processed=False)
        - ensures only one BopEventLog exists in the database.
        """
        event_uuid = str(uuid.uuid4())
        payload = {
            "event_id": event_uuid,
            "event_type": "prospect.ready_for_crm",
            "source_app": "bop_clients",
            "bop_organization_id": str(self.bop_org_id_a),
        }

        # Simulate concurrent collision: first attempt creates row in DB
        res1 = self.client_a.post("/api/integrations/bop/v1/events/", payload, format="json")
        self.assertEqual(res1.status_code, status.HTTP_201_CREATED)

        # Mock initial duplicate check to return None (simulating race where thread B
        # checks before thread A commits, then attempts BopEventLog.objects.create)
        real_filter = BopEventLog.objects.filter

        def mocked_filter(*args, **kwargs):
            qs = real_filter(*args, **kwargs)
            # Intercept duplicate check and pretend record was not found yet
            orig_first = qs.first
            qs.first = lambda: None
            return qs

        with mock.patch.object(BopEventLog.objects, "filter", side_effect=mocked_filter):
            # Database unique constraint (unique_bop_event_id_per_org) will fire IntegrityError
            res2 = self.client_a.post("/api/integrations/bop/v1/events/", payload, format="json")

        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        self.assertEqual(res2.data["status"], "duplicate")
        self.assertFalse(res2.data["processed"])

        # Verify only one event log exists in the database
        set_rls_context(self.org_a.id)
        self.assertEqual(BopEventLog.objects.filter(event_id=event_uuid).count(), 1)
        clear_rls_context()

    # =========================================================================
    # 6. LOG HYGIENE TEST
    # =========================================================================

    def test_log_hygiene_no_secret_or_payload_leakage(self):
        """
        Verify that gateway logs contain only safe correlation identifiers
        (event_id, target_org.id) and NEVER log authorization tokens, PAT secrets,
        payload bodies, or arbitrary user-controlled idempotency keys.
        """
        secret_payload_value = "secret_password_value_12345"
        arbitrary_idem_key = "user_input_idem_key_99999"
        event_uuid = str(uuid.uuid4())

        payload = {
            "event_id": event_uuid,
            "event_type": "prospect.ready_for_crm",
            "source_app": "bop_clients",
            "bop_organization_id": str(self.bop_org_id_a),
            "idempotency_key": arbitrary_idem_key,
            "payload": {"secret": secret_payload_value},
        }

        with self.assertLogs("bop_integration.views", level="INFO") as log_capture:
            res = self.client_a.post("/api/integrations/bop/v1/events/", payload, format="json")
            self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        captured_text = "\n".join(log_capture.output)

        # Assert secrets and user payloads are not leaked
        self.assertNotIn(secret_payload_value, captured_text)
        self.assertNotIn(arbitrary_idem_key, captured_text)
        self.assertNotIn(self.raw_pat_a, captured_text)
        self.assertNotIn("Authorization", captured_text)

        # Assert safe correlation identifiers are present
        self.assertIn(event_uuid, captured_text)
        self.assertIn(str(self.org_a.id), captured_text)

    # =========================================================================
    # 7. BOP SERVICE IDENTITY BINDING TESTS (CRM-I1B.2)
    # =========================================================================

    def test_source_binding_matching_app_accepted(self):
        """A. PAT source_app=bop_clients + payload bop_clients -> accepted (201 Created)."""
        payload = {
            "event_id": str(uuid.uuid4()),
            "event_type": "prospect.ready_for_crm",
            "source_app": "bop_clients",
            "bop_organization_id": str(self.bop_org_id_a),
        }
        res = self.client_a.post("/api/integrations/bop/v1/events/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data["status"], "received")

    def test_source_binding_mismatched_app_forbidden(self):
        """B. PAT source_app=bop_clients + payload bop_erp -> 403 Forbidden."""
        payload = {
            "event_id": str(uuid.uuid4()),
            "event_type": "erp.customer.updated",
            "source_app": "bop_erp",
            "bop_organization_id": str(self.bop_org_id_a),
        }
        res = self.client_a.post("/api/integrations/bop/v1/events/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("Source application mismatch", str(res.data))

    def test_source_binding_null_source_app_forbidden(self):
        """C. PAT source_app=NULL + Bop gateway -> 403 Forbidden."""
        raw_null_pat, _ = PersonalAccessToken.generate(
            profile=self.profile_a,
            name="Legacy Unbound PAT",
            scopes=["integrations:write"],
            source_app=None,
        )
        null_client = APIClient()
        null_client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw_null_pat}")
        payload = {
            "event_id": str(uuid.uuid4()),
            "event_type": "prospect.ready_for_crm",
            "source_app": "bop_clients",
            "bop_organization_id": str(self.bop_org_id_a),
        }
        res = null_client.post("/api/integrations/bop/v1/events/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("not bound to a Bop source application", str(res.data))

    def test_source_binding_invalid_source_app_cannot_be_persisted(self):
        """D. Invalid PAT source_app cannot be persisted or generated."""
        from django.core.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            PersonalAccessToken.generate(
                profile=self.profile_a,
                name="Malicious PAT",
                scopes=["integrations:write"],
                source_app="malicious_hacked_app",
            )

        with self.assertRaises(ValidationError):
            pat = PersonalAccessToken(
                org=self.org_a,
                profile=self.profile_a,
                name="Direct Bad PAT",
                source_app="arbitrary_app",
            )
            pat.save()

    def test_source_binding_legacy_non_bop_pat_behavior_unchanged(self):
        """E. Existing non-Bop PAT behavior remains unchanged for standard CRM APIs."""
        raw_legacy, legacy_pat = PersonalAccessToken.generate(
            profile=self.profile_a,
            name="Legacy CRM PAT",
            scopes=["leads:read"],
            source_app=None,
        )
        self.assertIsNone(legacy_pat.source_app)
        self.assertTrue(legacy_pat.is_valid())

        # Authenticable via PATAuthentication
        legacy_client = APIClient()
        legacy_client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw_legacy}")
        res = legacy_client.get("/api/leads/")
        # Should NOT be rejected because of missing source_app
        self.assertNotIn("source application", str(res.data))
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_source_binding_mismatch_creates_zero_event_logs(self):
        """F. Mismatch creates zero BopEventLog rows."""
        set_rls_context(self.org_a.id)
        before_count = BopEventLog.objects.filter(org=self.org_a).count()
        clear_rls_context()

        for wrong_app in ["bop_erp", "bop_social", "bop_chatbot", "bop_assistant"]:
            payload = {
                "event_id": str(uuid.uuid4()),
                "event_type": "prospect.ready_for_crm",
                "source_app": wrong_app,
                "bop_organization_id": str(self.bop_org_id_a),
            }
            res = self.client_a.post("/api/integrations/bop/v1/events/", payload, format="json")
            self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        set_rls_context(self.org_a.id)
        after_count = BopEventLog.objects.filter(org=self.org_a).count()
        clear_rls_context()
        self.assertEqual(before_count, after_count)

    def test_source_binding_matching_request_preserves_org_rls(self):
        """G. Matching request still passes existing org/RLS protections."""
        event_uuid = str(uuid.uuid4())
        payload = {
            "event_id": event_uuid,
            "event_type": "prospect.ready_for_crm",
            "source_app": "bop_clients",
            "bop_organization_id": str(self.bop_org_id_a),
        }
        res = self.client_a.post("/api/integrations/bop/v1/events/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        # Visible under Org A
        set_rls_context(self.org_a.id)
        self.assertEqual(BopEventLog.objects.filter(event_id=event_uuid).count(), 1)
        clear_rls_context()

        # Completely invisible under Org B
        set_rls_context(self.org_b.id)
        self.assertEqual(BopEventLog.objects.filter(event_id=event_uuid).count(), 0)
        clear_rls_context()


class CanonicalBopClientsCompatibilityTestCase(TestCase):
    """
    Targeted test suite for Phase CRM-I1C.1:
    Canonical Bop Clients Envelope Compatibility (prospect.ready_for_crm v2).
    """

    def setUp(self):
        self.bop_org_id = uuid.uuid4()
        self.org = Org.objects.create(name="Canonical Test Org", bop_organization_id=self.bop_org_id)

        uid = uuid.uuid4().hex[:8]
        self.user = User.objects.create_user(email=f"canonical_admin_{uid}@test.com", password="pass")
        self.profile = Profile.objects.create(user=self.user, org=self.org, role="ADMIN")

        # Canonical PAT with source_app="bopclients"
        self.raw_pat, self.pat = PersonalAccessToken.generate(
            profile=self.profile,
            name="Canonical PAT",
            scopes=["integrations:write"],
            source_app="bopclients",
        )
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.raw_pat}")

        # Legacy PAT with source_app="bop_clients"
        self.raw_pat_legacy, self.pat_legacy = PersonalAccessToken.generate(
            profile=self.profile,
            name="Legacy PAT",
            scopes=["integrations:write"],
            source_app="bop_clients",
        )
        self.client_legacy = APIClient()
        self.client_legacy.credentials(HTTP_AUTHORIZATION=f"Bearer {self.raw_pat_legacy}")

        # Wrong PAT with source_app="boperp"
        self.raw_pat_erp, self.pat_erp = PersonalAccessToken.generate(
            profile=self.profile,
            name="ERP PAT",
            scopes=["integrations:write"],
            source_app="boperp",
        )
        self.client_erp = APIClient()
        self.client_erp.credentials(HTTP_AUTHORIZATION=f"Bearer {self.raw_pat_erp}")

    def tearDown(self):
        clear_rls_context()
        super().tearDown()

    def get_canonical_fixture(self):
        """Build a pristine canonical BopIntegrationEvent.to_dict() payload for Org."""
        event_id = str(uuid.uuid4())
        corr_id = str(uuid.uuid4())
        return {
            "event_id": event_id,
            "event_type": "prospect.ready_for_crm",
            "event_version": 2,
            "occurred_at": "2026-09-16T18:00:00.000000+00:00",
            "producer_app": "bopclients",
            "bop_organization_id": str(self.bop_org_id),
            "subject": {
                "bop_organization_id": str(self.bop_org_id),
                "application_id": "bopclients",
                "entity_type": "prospect",
                "entity_id": "prsp_987654321",
            },
            "correlation_id": corr_id,
            "causation_id": None,
            "payload": {
                "prospect_id": "prsp_987654321",
                "company_name": "Solaris Energy Corp",
                "website": "https://solaris-energy.example.com",
                "industry": "Clean Energy",
                "location": "Denver, CO, USA",
                "lead_score": 88,
                "priority": "HIGH",
                "campaign_id": "cmp_123456789",
                "signal_summary": None,
                "source": "discovery",
                "prospect_url": "https://app.bopclients.com/prospects/prsp_987654321",
                "handoff_requested_by": "usr_alpha_admin",
                "handoff_requested_at": "2026-09-16T18:00:00.000000+00:00",
                "recommended_action": "handoff_to_crm",
                "human_review_required": False,
            },
            "metadata": {},
        }

    def test_a_canonical_bopclients_v2_envelope_accepted(self):
        """A. canonical Bop Clients v2 envelope -> 201 Created and properly stored."""
        envelope = self.get_canonical_fixture()
        res = self.client.post("/api/integrations/bop/v1/events/", envelope, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data["status"], "processed")
        self.assertEqual(res.data["event_id"], envelope["event_id"])
        self.assertTrue(res.data["processed"])

        set_rls_context(self.org.id)
        log = BopEventLog.objects.get(event_id=envelope["event_id"])
        self.assertEqual(log.source_app, "bopclients")
        self.assertEqual(log.event_type, "prospect.ready_for_crm")
        self.assertEqual(log.event_version, 2)
        self.assertEqual(log.correlation_id, envelope["correlation_id"])
        self.assertIsNone(log.causation_id)
        self.assertEqual(log.external_entity_id, "prsp_987654321")
        self.assertEqual(log.external_entity_type, "prospect")
        self.assertEqual(log.payload["company_name"], "Solaris Energy Corp")
        self.assertEqual(log.metadata, {})
        clear_rls_context()

    def test_b_duplicate_deterministic_event_id(self):
        """B. duplicate deterministic event_id -> 200 duplicate, exactly one log row."""
        envelope = self.get_canonical_fixture()
        res1 = self.client.post("/api/integrations/bop/v1/events/", envelope, format="json")
        self.assertEqual(res1.status_code, status.HTTP_201_CREATED)

        res2 = self.client.post("/api/integrations/bop/v1/events/", envelope, format="json")
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        self.assertEqual(res2.data["status"], "duplicate")
        self.assertEqual(res2.data["event_id"], envelope["event_id"])

        set_rls_context(self.org.id)
        self.assertEqual(BopEventLog.objects.filter(event_id=envelope["event_id"]).count(), 1)
        clear_rls_context()

    def test_c_producer_app_bopclients_recognized(self):
        """C. producer_app=bopclients recognized and persisted canonically."""
        envelope = self.get_canonical_fixture()
        envelope["producer_app"] = "bopclients"
        res = self.client.post("/api/integrations/bop/v1/events/", envelope, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        set_rls_context(self.org.id)
        log = BopEventLog.objects.get(event_id=envelope["event_id"])
        self.assertEqual(log.source_app, "bopclients")
        clear_rls_context()

    def test_d_pat_source_app_bopclients_matches_producer(self):
        """D. PAT source_app=bopclients matches producer (and legacy alias bop_clients normalizes)."""
        # Canonical token
        envelope1 = self.get_canonical_fixture()
        res1 = self.client.post("/api/integrations/bop/v1/events/", envelope1, format="json")
        self.assertEqual(res1.status_code, status.HTTP_201_CREATED)

        # Legacy token with bop_clients sends canonical bopclients
        envelope2 = self.get_canonical_fixture()
        res2 = self.client_legacy.post("/api/integrations/bop/v1/events/", envelope2, format="json")
        self.assertEqual(res2.status_code, status.HTTP_201_CREATED)

    def test_e_pat_source_mismatch_forbidden(self):
        """E. PAT source mismatch -> 403 Forbidden."""
        envelope = self.get_canonical_fixture()
        res = self.client_erp.post("/api/integrations/bop/v1/events/", envelope, format="json")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("Source application mismatch", str(res.data))

    def test_f_envelope_org_mismatch_subject_org_rejected(self):
        """F. envelope org != subject org -> 400 Bad Request."""
        envelope = self.get_canonical_fixture()
        envelope["subject"]["bop_organization_id"] = str(uuid.uuid4())
        res = self.client.post("/api/integrations/bop/v1/events/", envelope, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Tenant mismatch", str(res.data))

    def test_g_producer_app_mismatch_subject_application_id_rejected(self):
        """G. producer_app != subject.application_id -> 400 Bad Request."""
        envelope = self.get_canonical_fixture()
        envelope["subject"]["application_id"] = "boperp"
        res = self.client.post("/api/integrations/bop/v1/events/", envelope, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Application mismatch", str(res.data))

    def test_h_subject_entity_id_mismatch_payload_prospect_id_rejected(self):
        """H. subject.entity_id != payload.prospect_id -> 400 Bad Request."""
        envelope = self.get_canonical_fixture()
        envelope["payload"]["prospect_id"] = "prsp_mismatch_id"
        res = self.client.post("/api/integrations/bop/v1/events/", envelope, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("does not match payload prospect_id", str(res.data))

    def test_i_subject_entity_type_not_prospect_rejected(self):
        """I. subject entity_type != prospect -> 400 Bad Request."""
        envelope = self.get_canonical_fixture()
        envelope["subject"]["entity_type"] = "deal"
        res = self.client.post("/api/integrations/bop/v1/events/", envelope, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("requires subject.entity_type='prospect'", str(res.data))

    def test_j_unsupported_event_version_rejected(self):
        """J. unsupported event_version -> 400 Bad Request."""
        # Version 3 unsupported
        envelope = self.get_canonical_fixture()
        envelope["event_version"] = 3
        res = self.client.post("/api/integrations/bop/v1/events/", envelope, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Unsupported event_version", str(res.data))

        # Version 0 invalid
        envelope2 = self.get_canonical_fixture()
        envelope2["event_version"] = 0
        res2 = self.client.post("/api/integrations/bop/v1/events/", envelope2, format="json")
        self.assertEqual(res2.status_code, status.HTTP_400_BAD_REQUEST)

    def test_k_invalid_correlation_id_rejected(self):
        """K. invalid correlation_id -> 400 Bad Request."""
        # Malformed string
        envelope = self.get_canonical_fixture()
        envelope["correlation_id"] = "not-a-valid-uuid"
        res = self.client.post("/api/integrations/bop/v1/events/", envelope, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("correlation_id", str(res.data))

        # Missing on canonical Bop Clients event
        envelope2 = self.get_canonical_fixture()
        del envelope2["correlation_id"]
        res2 = self.client.post("/api/integrations/bop/v1/events/", envelope2, format="json")
        self.assertEqual(res2.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("correlation_id", str(res2.data))

    def test_l_invalid_causation_id_rejected(self):
        """L. invalid causation_id -> 400 Bad Request."""
        envelope = self.get_canonical_fixture()
        envelope["causation_id"] = "not-a-uuid"
        res = self.client.post("/api/integrations/bop/v1/events/", envelope, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("causation_id", str(res.data))

    def test_m_metadata_non_object_rejected(self):
        """M. metadata non-object -> 400 Bad Request."""
        envelope = self.get_canonical_fixture()
        envelope["metadata"] = "just a string"
        res = self.client.post("/api/integrations/bop/v1/events/", envelope, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("metadata", str(res.data))

        envelope2 = self.get_canonical_fixture()
        envelope2["metadata"] = ["item1", "item2"]
        res2 = self.client.post("/api/integrations/bop/v1/events/", envelope2, format="json")
        self.assertEqual(res2.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("metadata", str(res2.data))

    def test_n_prohibited_pii_payload_keys_rejected(self):
        """N. prohibited PII payload keys -> 400 Bad Request."""
        prohibited_keys = [
            "email",
            "phone",
            "first_name",
            "last_name",
            "contact_name",
            "primary_contact",
        ]
        for pii in prohibited_keys:
            envelope = self.get_canonical_fixture()
            envelope["payload"][pii] = "unauthorized_pii_value"
            res = self.client.post("/api/integrations/bop/v1/events/", envelope, format="json")
            self.assertEqual(
                res.status_code,
                status.HTTP_400_BAD_REQUEST,
                f"Expected 400 rejection for PII key '{pii}'",
            )
            self.assertIn("prohibited PII", str(res.data))

    def test_o_canonical_envelope_creates_exactly_one_event_log(self):
        """O. canonical envelope creates exactly one BopEventLog row."""
        set_rls_context(self.org.id)
        before_count = BopEventLog.objects.filter(org=self.org).count()
        clear_rls_context()

        envelope = self.get_canonical_fixture()
        res = self.client.post("/api/integrations/bop/v1/events/", envelope, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        set_rls_context(self.org.id)
        after_count = BopEventLog.objects.filter(org=self.org).count()
        clear_rls_context()
        self.assertEqual(after_count, before_count + 1)

    def test_p_zero_crm_business_entities_created(self):
        """P. zero Contact or Opportunity created during prospect ingestion (Lead and Account are created)."""
        set_rls_context(self.org.id)
        before_leads = Lead.objects.count()
        before_accounts = Account.objects.count()
        before_contacts = Contact.objects.count()
        before_opps = Opportunity.objects.count()
        clear_rls_context()

        envelope = self.get_canonical_fixture()
        res = self.client.post("/api/integrations/bop/v1/events/", envelope, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        set_rls_context(self.org.id)
        # Lead and Account are created in CRM-I1C.3
        self.assertEqual(Lead.objects.count(), before_leads + 1)
        self.assertEqual(Account.objects.count(), before_accounts + 1)
        # Contact and Opportunity are never created during prospect ingestion
        self.assertEqual(Contact.objects.count(), before_contacts)
        self.assertEqual(Opportunity.objects.count(), before_opps)
        clear_rls_context()

    def test_q_alias_conflicts_and_backward_compatibility(self):
        """Q. Alias conflicts and backward compatibility verification."""
        # 1. Matching aliases: producer_app=bopclients, source_app=bop_clients -> accepted
        envelope1 = self.get_canonical_fixture()
        envelope1["source_app"] = "bop_clients"
        res1 = self.client.post("/api/integrations/bop/v1/events/", envelope1, format="json")
        self.assertEqual(res1.status_code, status.HTTP_201_CREATED)

        # 2. Contradictory aliases: producer_app=bopclients, source_app=boperp -> 400
        envelope2 = self.get_canonical_fixture()
        envelope2["source_app"] = "boperp"
        res2 = self.client.post("/api/integrations/bop/v1/events/", envelope2, format="json")
        self.assertEqual(res2.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Contradictory", str(res2.data))

        # 3. Matching external_entity_id alias -> accepted
        envelope3 = self.get_canonical_fixture()
        envelope3["external_entity_id"] = "prsp_987654321"
        res3 = self.client.post("/api/integrations/bop/v1/events/", envelope3, format="json")
        self.assertEqual(res3.status_code, status.HTTP_201_CREATED)

        # 4. Conflicting external_entity_id alias -> 400
        envelope4 = self.get_canonical_fixture()
        envelope4["external_entity_id"] = "prsp_different_id"
        res4 = self.client.post("/api/integrations/bop/v1/events/", envelope4, format="json")
        self.assertEqual(res4.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Conflict", str(res4.data))

        # 5. Matching external_entity_type alias -> accepted
        envelope5 = self.get_canonical_fixture()
        envelope5["external_entity_type"] = "prospect"
        res5 = self.client.post("/api/integrations/bop/v1/events/", envelope5, format="json")
        self.assertEqual(res5.status_code, status.HTTP_201_CREATED)

        # 6. Conflicting external_entity_type alias -> 400
        envelope6 = self.get_canonical_fixture()
        envelope6["external_entity_type"] = "account"
        res6 = self.client.post("/api/integrations/bop/v1/events/", envelope6, format="json")
        self.assertEqual(res6.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Conflict", str(res6.data))
