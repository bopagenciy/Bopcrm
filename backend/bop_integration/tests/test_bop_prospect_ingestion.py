import copy
import json
import threading
import uuid
from unittest.mock import Mock, patch

from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError, connections, transaction
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import Account
from bop_integration.models import BopEventLog, ExternalEntityMap
from bop_integration.services import ingest_prospect_ready_for_crm
from common.models import Org, PersonalAccessToken, Profile, User
from common.tasks import clear_rls_context, set_rls_context
from contacts.models import Contact
from leads.models import Lead
from leads.services import convert_lead_to_account
from opportunity.models import Opportunity
from tasks.models import Task


class BopProspectBusinessIngestionTestCase(TestCase):
    """
    Test suite for Phase CRM-I1C.3: Bop Clients Prospect Business Ingestion.
    Validates atomic, tenant-isolated ingestion of canonical prospect.ready_for_crm v2 events.
    """

    def setUp(self):
        self.bop_org_id_a = uuid.uuid4()
        self.bop_org_id_b = uuid.uuid4()

        self.org_a = Org.objects.create(name="Prospect Org A", bop_organization_id=self.bop_org_id_a)
        self.org_b = Org.objects.create(name="Prospect Org B", bop_organization_id=self.bop_org_id_b)

        uid_a = uuid.uuid4().hex[:8]
        uid_b = uuid.uuid4().hex[:8]
        self.user_a = User.objects.create_user(email=f"admin_prsp_a_{uid_a}@test.com", password="pass")
        self.user_b = User.objects.create_user(email=f"admin_prsp_b_{uid_b}@test.com", password="pass")

        self.profile_a = Profile.objects.create(user=self.user_a, org=self.org_a, role="ADMIN")
        self.profile_b = Profile.objects.create(user=self.user_b, org=self.org_b, role="ADMIN")

        self.raw_pat_a, self.pat_a = PersonalAccessToken.generate(
            profile=self.profile_a,
            name="Org A PAT",
            scopes=["integrations:write"],
            source_app="bopclients",
        )
        self.raw_pat_b, self.pat_b = PersonalAccessToken.generate(
            profile=self.profile_b,
            name="Org B PAT",
            scopes=["integrations:write"],
            source_app="bopclients",
        )

        self.client_a = APIClient()
        self.client_a.credentials(HTTP_AUTHORIZATION=f"Bearer {self.raw_pat_a}")

        self.client_b = APIClient()
        self.client_b.credentials(HTTP_AUTHORIZATION=f"Bearer {self.raw_pat_b}")

    def tearDown(self):
        clear_rls_context()
        super().tearDown()

    def build_canonical_event(self, org=None, prospect_id="prsp_001", company_name="Acme Solar Industries", **overrides):
        target_org = org or self.org_a
        event_uuid = str(uuid.uuid4())
        payload = {
            "prospect_id": prospect_id,
            "company_name": company_name,
            "website": "https://acmesolar.example.com",
            "industry": "Clean Energy",
            "location": "Denver, CO, USA",
            "lead_score": 88,
            "priority": "HIGH",
            "campaign_id": "cmp_123456",
            "signal_summary": {"intent": "high", "growth": "fast"},
            "source": "discovery",
            "prospect_url": f"https://app.bopclients.com/prospects/{prospect_id}",
            "handoff_requested_by": "usr_alpha_agent",
            "handoff_requested_at": "2026-09-16T18:00:00.000000+00:00",
            "recommended_action": "handoff_to_crm",
            "human_review_required": False,
        }
        payload.update(overrides)

        envelope = {
            "event_id": event_uuid,
            "event_type": "prospect.ready_for_crm",
            "event_version": 2,
            "occurred_at": timezone.now().isoformat(),
            "producer_app": "bopclients",
            "bop_organization_id": str(target_org.bop_organization_id),
            "subject": {
                "bop_organization_id": str(target_org.bop_organization_id),
                "application_id": "bopclients",
                "entity_type": "prospect",
                "entity_id": prospect_id,
            },
            "correlation_id": str(uuid.uuid4()),
            "causation_id": None,
            "payload": payload,
            "metadata": {"env": "prod"},
        }
        return envelope

    def test_case_a_new_prospect_creates_account_lead_and_map(self):
        """Case A: New prospect -> creates exactly 1 Account, 1 Lead, 1 ExternalEntityMap."""
        envelope = self.build_canonical_event()
        res = self.client_a.post("/api/integrations/bop/v1/events/", envelope, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data["status"], "processed")
        self.assertTrue(res.data["processed"])

        set_rls_context(self.org_a.id)
        # Account verified
        accounts = Account.objects.filter(org=self.org_a, name="Acme Solar Industries")
        self.assertEqual(accounts.count(), 1)
        account = accounts.first()
        self.assertEqual(account.website, "https://acmesolar.example.com")
        self.assertEqual(account.industry, "Clean Energy")
        self.assertEqual(account.address_line, "Denver, CO, USA")

        # Lead verified
        leads = Lead.objects.filter(org=self.org_a, company_name="Acme Solar Industries")
        self.assertEqual(leads.count(), 1)
        lead = leads.first()
        self.assertEqual(lead.title, "Prospect: Acme Solar Industries")
        self.assertEqual(lead.status, "assigned")
        self.assertEqual(lead.source, "discovery")
        self.assertEqual(lead.industry, "Clean Energy")

        # ExternalEntityMap verified
        maps = ExternalEntityMap.objects.filter(
            org=self.org_a,
            source_app="bopclients",
            external_entity_type="prospect",
            external_entity_id="prsp_001",
        )
        self.assertEqual(maps.count(), 1)
        ext_map = maps.first()
        self.assertEqual(ext_map.content_object, lead)

        # Event log verified
        log = BopEventLog.objects.get(event_id=envelope["event_id"])
        self.assertEqual(log.status, "processed")
        self.assertIsNotNone(log.processed_at)
        self.assertIsNone(log.last_error)
        clear_rls_context()

    def test_case_b_existing_account_reused_and_backfilled(self):
        """Case B: Existing Account with same name is reused and backfilled without overwriting existing data."""
        set_rls_context(self.org_a.id)
        existing_acc = Account.objects.create(
            org=self.org_a,
            name="Acme Solar Industries",
            website="https://original-acme.com",  # Non-null, must NOT be overwritten
            industry=None,  # Null, should be backfilled
            description="Existing account description",  # Must NOT be overwritten
            is_active=True,
        )
        clear_rls_context()

        envelope = self.build_canonical_event(
            company_name="Acme Solar Industries",
            website="https://new-website.com",
            industry="Clean Energy",
        )
        res = self.client_a.post("/api/integrations/bop/v1/events/", envelope, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        set_rls_context(self.org_a.id)
        # Verify Account count is still 1
        self.assertEqual(Account.objects.filter(org=self.org_a).count(), 1)
        acc = Account.objects.get(id=existing_acc.id)
        self.assertEqual(acc.website, "https://original-acme.com")  # Preserved!
        self.assertEqual(acc.industry, "Clean Energy")  # Backfilled!
        self.assertEqual(acc.description, "Existing account description")  # Preserved!

        # Lead was created
        self.assertEqual(Lead.objects.filter(org=self.org_a, company_name="Acme Solar Industries").count(), 1)
        clear_rls_context()

    def test_case_c_same_event_replay_duplicate_200(self):
        """Case C: Same event replay -> duplicate detected, no duplicate entities created, HTTP 200 duplicate."""
        envelope = self.build_canonical_event(prospect_id="prsp_replay")
        res1 = self.client_a.post("/api/integrations/bop/v1/events/", envelope, format="json")
        self.assertEqual(res1.status_code, status.HTTP_201_CREATED)

        res2 = self.client_a.post("/api/integrations/bop/v1/events/", envelope, format="json")
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        self.assertEqual(res2.data["status"], "duplicate")
        self.assertTrue(res2.data["duplicate"])
        self.assertTrue(res2.data["processed"])

        set_rls_context(self.org_a.id)
        self.assertEqual(Account.objects.filter(org=self.org_a).count(), 1)
        self.assertEqual(Lead.objects.filter(org=self.org_a).count(), 1)
        self.assertEqual(ExternalEntityMap.objects.filter(org=self.org_a).count(), 1)
        self.assertEqual(BopEventLog.objects.filter(event_id=envelope["event_id"]).count(), 1)
        clear_rls_context()

    def test_case_d_different_event_id_same_prospect_id_deduplicated(self):
        """Case D: Different event_id with same prospect_id -> ExternalEntityMap protects against second Lead."""
        envelope1 = self.build_canonical_event(prospect_id="prsp_same_id")
        res1 = self.client_a.post("/api/integrations/bop/v1/events/", envelope1, format="json")
        self.assertEqual(res1.status_code, status.HTTP_201_CREATED)

        envelope2 = self.build_canonical_event(prospect_id="prsp_same_id")
        envelope2["event_id"] = str(uuid.uuid4())
        envelope2["correlation_id"] = str(uuid.uuid4())

        res2 = self.client_a.post("/api/integrations/bop/v1/events/", envelope2, format="json")
        self.assertEqual(res2.status_code, status.HTTP_201_CREATED)

        set_rls_context(self.org_a.id)
        self.assertEqual(Lead.objects.filter(org=self.org_a).count(), 1)
        self.assertEqual(ExternalEntityMap.objects.filter(org=self.org_a, external_entity_id="prsp_same_id").count(), 1)
        self.assertEqual(BopEventLog.objects.filter(org=self.org_a).count(), 2)
        clear_rls_context()

    def test_case_e_case_insensitive_account_matching(self):
        """Case E: Case-insensitive account name matching within tenant (ACME CORP matches acme corp)."""
        set_rls_context(self.org_a.id)
        Account.objects.create(org=self.org_a, name="acme solar industries", is_active=True)
        clear_rls_context()

        envelope = self.build_canonical_event(company_name="ACME SOLAR INDUSTRIES")
        res = self.client_a.post("/api/integrations/bop/v1/events/", envelope, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        set_rls_context(self.org_a.id)
        self.assertEqual(Account.objects.filter(org=self.org_a).count(), 1)
        clear_rls_context()

    def test_case_f_same_company_name_in_different_org_allowed(self):
        """Case F: Same company name in different org -> separate Account allowed per tenant isolation."""
        envelope_a = self.build_canonical_event(org=self.org_a, company_name="Shared Company Name")
        res_a = self.client_a.post("/api/integrations/bop/v1/events/", envelope_a, format="json")
        self.assertEqual(res_a.status_code, status.HTTP_201_CREATED)

        envelope_b = self.build_canonical_event(org=self.org_b, company_name="Shared Company Name")
        res_b = self.client_b.post("/api/integrations/bop/v1/events/", envelope_b, format="json")
        self.assertEqual(res_b.status_code, status.HTTP_201_CREATED)

        set_rls_context(self.org_a.id)
        self.assertEqual(Account.objects.filter(name="Shared Company Name").count(), 1)
        clear_rls_context()

        set_rls_context(self.org_b.id)
        self.assertEqual(Account.objects.filter(name="Shared Company Name").count(), 1)
        clear_rls_context()

    def test_case_g_same_prospect_id_in_different_org_allowed(self):
        """Case G: Same prospect_id in different org -> separate mapping and entity allowed."""
        envelope_a = self.build_canonical_event(org=self.org_a, prospect_id="prsp_tenant_shared")
        res_a = self.client_a.post("/api/integrations/bop/v1/events/", envelope_a, format="json")
        self.assertEqual(res_a.status_code, status.HTTP_201_CREATED)

        envelope_b = self.build_canonical_event(org=self.org_b, prospect_id="prsp_tenant_shared")
        res_b = self.client_b.post("/api/integrations/bop/v1/events/", envelope_b, format="json")
        self.assertEqual(res_b.status_code, status.HTTP_201_CREATED)

        set_rls_context(self.org_a.id)
        map_a = ExternalEntityMap.objects.filter(external_entity_id="prsp_tenant_shared")
        self.assertEqual(map_a.count(), 1)
        self.assertEqual(map_a.first().org, self.org_a)
        clear_rls_context()

        set_rls_context(self.org_b.id)
        map_b = ExternalEntityMap.objects.filter(external_entity_id="prsp_tenant_shared")
        self.assertEqual(map_b.count(), 1)
        self.assertEqual(map_b.first().org, self.org_b)
        clear_rls_context()

    def test_case_h_zero_contact_pii_on_lead(self):
        """Case H: Lead has first_name, last_name, email, phone as None/blank (zero fabricated PII)."""
        envelope = self.build_canonical_event(prospect_id="prsp_no_pii")
        res = self.client_a.post("/api/integrations/bop/v1/events/", envelope, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        set_rls_context(self.org_a.id)
        lead = Lead.objects.get(company_name="Acme Solar Industries")
        self.assertIsNone(lead.first_name)
        self.assertIsNone(lead.last_name)
        self.assertIsNone(lead.email)
        self.assertIsNone(lead.phone)
        clear_rls_context()

    def test_case_i_zero_contact_created(self):
        """Case I: Zero Contact created during prospect ingestion."""
        set_rls_context(self.org_a.id)
        contacts_before = Contact.objects.filter(org=self.org_a).count()
        clear_rls_context()

        envelope = self.build_canonical_event(prospect_id="prsp_zero_contact")
        res = self.client_a.post("/api/integrations/bop/v1/events/", envelope, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        set_rls_context(self.org_a.id)
        self.assertEqual(Contact.objects.filter(org=self.org_a).count(), contacts_before)
        clear_rls_context()

    def test_case_j_zero_opportunity_created(self):
        """Case J: Zero Opportunity created during prospect ingestion."""
        set_rls_context(self.org_a.id)
        opps_before = Opportunity.objects.filter(org=self.org_a).count()
        clear_rls_context()

        envelope = self.build_canonical_event(prospect_id="prsp_zero_opp")
        res = self.client_a.post("/api/integrations/bop/v1/events/", envelope, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        set_rls_context(self.org_a.id)
        self.assertEqual(Opportunity.objects.filter(org=self.org_a).count(), opps_before)
        clear_rls_context()

    def test_case_k_zero_task_created(self):
        """Case K: Zero Task created during prospect ingestion."""
        set_rls_context(self.org_a.id)
        tasks_before = Task.objects.filter(org=self.org_a).count()
        clear_rls_context()

        envelope = self.build_canonical_event(prospect_id="prsp_zero_task")
        res = self.client_a.post("/api/integrations/bop/v1/events/", envelope, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        set_rls_context(self.org_a.id)
        self.assertEqual(Task.objects.filter(org=self.org_a).count(), tasks_before)
        clear_rls_context()

    def test_case_l_atomic_failure_rolls_back_all_business_entities(self):
        """Case L: Atomic failure leaves no partial Account, Lead, or map."""
        envelope = self.build_canonical_event(prospect_id="prsp_atomic_fail")

        with patch("bop_integration.services.ExternalEntityMap.objects.create", side_effect=RuntimeError("Simulated DB map error")):
            res = self.client_a.post("/api/integrations/bop/v1/events/", envelope, format="json")
            self.assertEqual(res.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)

        set_rls_context(self.org_a.id)
        self.assertEqual(Account.objects.filter(org=self.org_a, name="Acme Solar Industries").count(), 0)
        self.assertEqual(Lead.objects.filter(org=self.org_a, company_name="Acme Solar Industries").count(), 0)
        self.assertEqual(ExternalEntityMap.objects.filter(org=self.org_a, external_entity_id="prsp_atomic_fail").count(), 0)
        clear_rls_context()

    def test_case_m_failure_sets_event_log_status_failed(self):
        """Case M: Failure sets BopEventLog.status = 'failed' with safe last_error."""
        envelope = self.build_canonical_event(prospect_id="prsp_fail_status")

        with patch("bop_integration.services.Lead.objects.create", side_effect=ValueError("Simulated Lead crash")):
            res = self.client_a.post("/api/integrations/bop/v1/events/", envelope, format="json")
            self.assertEqual(res.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)

        set_rls_context(self.org_a.id)
        log = BopEventLog.objects.get(event_id=envelope["event_id"])
        self.assertEqual(log.status, "failed")
        self.assertIn("Simulated Lead crash", log.last_error)
        clear_rls_context()

    def test_case_n_retry_of_failed_event_succeeds_without_duplicate_log(self):
        """Case N: Retry of failed event succeeds without creating a duplicate log row."""
        envelope = self.build_canonical_event(prospect_id="prsp_retry")

        # 1. First attempt fails
        with patch("bop_integration.services.Lead.objects.create", side_effect=RuntimeError("Transient error")):
            res1 = self.client_a.post("/api/integrations/bop/v1/events/", envelope, format="json")
            self.assertEqual(res1.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)

        set_rls_context(self.org_a.id)
        self.assertEqual(BopEventLog.objects.filter(event_id=envelope["event_id"]).count(), 1)
        log_before = BopEventLog.objects.get(event_id=envelope["event_id"])
        self.assertEqual(log_before.status, "failed")
        clear_rls_context()

        # 2. Second attempt (retry) succeeds without mocking
        res2 = self.client_a.post("/api/integrations/bop/v1/events/", envelope, format="json")
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        self.assertEqual(res2.data["status"], "processed")
        self.assertTrue(res2.data["processed"])

        set_rls_context(self.org_a.id)
        self.assertEqual(BopEventLog.objects.filter(event_id=envelope["event_id"]).count(), 1)
        log_after = BopEventLog.objects.get(event_id=envelope["event_id"])
        self.assertEqual(log_after.status, "processed")
        self.assertIsNone(log_after.last_error)
        self.assertIsNotNone(log_after.processed_at)

        self.assertEqual(Account.objects.filter(org=self.org_a).count(), 1)
        self.assertEqual(Lead.objects.filter(org=self.org_a).count(), 1)
        clear_rls_context()

    def test_case_o_concurrent_duplicate_simulation(self):
        """Case O: Concurrent simulated duplicate prospect cannot create two Leads."""
        envelope1 = self.build_canonical_event(prospect_id="prsp_concurrent")
        envelope2 = copy.deepcopy(envelope1)
        envelope2["event_id"] = str(uuid.uuid4())
        envelope2["correlation_id"] = str(uuid.uuid4())

        res1 = self.client_a.post("/api/integrations/bop/v1/events/", envelope1, format="json")
        self.assertEqual(res1.status_code, status.HTTP_201_CREATED)

        res2 = self.client_a.post("/api/integrations/bop/v1/events/", envelope2, format="json")
        self.assertEqual(res2.status_code, status.HTTP_201_CREATED)

        set_rls_context(self.org_a.id)
        self.assertEqual(Lead.objects.filter(org=self.org_a, company_name="Acme Solar Industries").count(), 1)
        self.assertEqual(ExternalEntityMap.objects.filter(org=self.org_a, external_entity_id="prsp_concurrent").count(), 1)
        clear_rls_context()

    def test_case_p_native_lead_conversion_compatibility(self):
        """
        Case P: Native Lead conversion reuses pre-created Account after email enrichment.
        Proves convert_lead_to_account does not duplicate or fail on unique_account_name_per_org constraint.
        """
        envelope = self.build_canonical_event(prospect_id="prsp_conversion_compat", company_name="Solaris Power Corp")
        res = self.client_a.post("/api/integrations/bop/v1/events/", envelope, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        set_rls_context(self.org_a.id)
        lead = Lead.objects.get(company_name="Solaris Power Corp")
        initial_account = Account.objects.get(name="Solaris Power Corp", org=self.org_a)

        # Sales rep enriches Lead with contact information
        lead.first_name = "Sarah"
        lead.last_name = "Connor"
        lead.email = "sconnor@solarispower.example.com"
        lead.phone = "+1-555-0199"
        lead.save()

        # Mock request object required by convert_lead_to_account
        mock_request = Mock()
        mock_request.profile = self.profile_a

        conv_account, conv_contact, conv_opportunity = convert_lead_to_account(lead, mock_request, create_opportunity=False)

        self.assertEqual(conv_account.id, initial_account.id)
        self.assertEqual(Account.objects.filter(org=self.org_a, name="Solaris Power Corp").count(), 1)

        self.assertIsNotNone(conv_contact)
        self.assertEqual(conv_contact.email, "sconnor@solarispower.example.com")
        self.assertEqual(conv_contact.first_name, "Sarah")

        lead.refresh_from_db()
        self.assertEqual(lead.status, "converted")
        clear_rls_context()

    def test_case_q_signal_summary_preserved_as_structured_json(self):
        """Case Q: signal_summary preserved as structured JSON in custom_fields['bop_clients']."""
        complex_signals = {
            "intent": "high",
            "technologies": ["React", "Django", "Postgres"],
            "metrics": {"growth_yoy": 120.5, "headcount": 45},
        }
        envelope = self.build_canonical_event(
            prospect_id="prsp_structured_signals",
            signal_summary=complex_signals,
        )
        res = self.client_a.post("/api/integrations/bop/v1/events/", envelope, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        set_rls_context(self.org_a.id)
        lead = Lead.objects.get(company_name="Acme Solar Industries")
        cf_bop = lead.custom_fields.get("bop_clients", {})
        self.assertEqual(cf_bop["signal_summary"], complex_signals)
        self.assertEqual(cf_bop["signal_summary"]["technologies"], ["React", "Django", "Postgres"])
        self.assertEqual(cf_bop["signal_summary"]["metrics"]["growth_yoy"], 120.5)
        clear_rls_context()

    def test_case_r_lead_score_remains_exact_numeric_value(self):
        """Case R: lead_score remains exact numeric value without invented HOT/WARM/COLD tiers."""
        envelope = self.build_canonical_event(
            prospect_id="prsp_exact_score",
            lead_score=87.5,
        )
        res = self.client_a.post("/api/integrations/bop/v1/events/", envelope, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        set_rls_context(self.org_a.id)
        lead = Lead.objects.get(company_name="Acme Solar Industries")
        cf_bop = lead.custom_fields.get("bop_clients", {})
        self.assertEqual(cf_bop["lead_score"], 87.5)
        self.assertIsInstance(cf_bop["lead_score"], (int, float))
        clear_rls_context()


class BopAccountConcurrencyTestCase(TransactionTestCase):
    """
    PostgreSQL-backed concurrency verification for Account deduplication during prospect ingestion.
    Validates that true concurrent requests across separate worker connections cannot produce
    duplicate Accounts, whether company names match exactly or with case variations.
    """

    def setUp(self):
        connections.close_all()
        self.bop_org_id_a = uuid.uuid4()
        self.bop_org_id_b = uuid.uuid4()

        self.org_a = Org.objects.create(name="Concurrent Org A", bop_organization_id=self.bop_org_id_a)
        self.org_b = Org.objects.create(name="Concurrent Org B", bop_organization_id=self.bop_org_id_b)

        uid_a = uuid.uuid4().hex[:8]
        uid_b = uuid.uuid4().hex[:8]
        self.user_a = User.objects.create_user(email=f"admin_conc_a_{uid_a}@test.com", password="pass")
        self.user_b = User.objects.create_user(email=f"admin_conc_b_{uid_b}@test.com", password="pass")

        self.profile_a = Profile.objects.create(user=self.user_a, org=self.org_a, role="ADMIN")
        self.profile_b = Profile.objects.create(user=self.user_b, org=self.org_b, role="ADMIN")

        self.raw_pat_a, self.pat_a = PersonalAccessToken.generate(
            profile=self.profile_a,
            name="Org A Concurrency PAT",
            scopes=["integrations:write"],
            source_app="bopclients",
        )
        self.raw_pat_b, self.pat_b = PersonalAccessToken.generate(
            profile=self.profile_b,
            name="Org B Concurrency PAT",
            scopes=["integrations:write"],
            source_app="bopclients",
        )

    def tearDown(self):
        clear_rls_context()
        connections.close_all()
        super().tearDown()

    def build_envelope(self, org, prospect_id, company_name, **overrides):
        event_uuid = str(uuid.uuid4())
        payload = {
            "prospect_id": prospect_id,
            "company_name": company_name,
            "website": "https://concurrent-solar.example.com",
            "industry": "Clean Energy",
            "location": "Denver, CO, USA",
            "lead_score": 90,
            "priority": "HIGH",
            "campaign_id": "cmp_conc_123",
            "signal_summary": {"concurrency": True},
            "source": "discovery",
            "prospect_url": f"https://app.bopclients.com/prospects/{prospect_id}",
            "handoff_requested_by": "usr_concurrency_agent",
            "handoff_requested_at": "2026-09-17T10:00:00.000000+00:00",
            "recommended_action": "handoff_to_crm",
            "human_review_required": False,
        }
        payload.update(overrides)

        return {
            "event_id": event_uuid,
            "event_type": "prospect.ready_for_crm",
            "event_version": 2,
            "occurred_at": timezone.now().isoformat(),
            "producer_app": "bopclients",
            "bop_organization_id": str(org.bop_organization_id),
            "subject": {
                "bop_organization_id": str(org.bop_organization_id),
                "application_id": "bopclients",
                "entity_type": "prospect",
                "entity_id": prospect_id,
            },
            "correlation_id": str(uuid.uuid4()),
            "causation_id": None,
            "payload": payload,
            "metadata": {"env": "test"},
        }

    def test_concurrent_prospect_ingestion_same_company_same_org(self):
        """
        True concurrency: Two independent threads ingest at approximately the same time:
        - same org
        - different event_id
        - different prospect_id
        - same company_name
        Expected:
        - exactly ONE Account
        - exactly TWO Leads
        - exactly TWO ExternalEntityMaps
        - both Leads refer conceptually to the same company Account
        """
        company_name = "Acme Concurrent Solar"
        env1 = self.build_envelope(self.org_a, "prsp_conc_1", company_name)
        env2 = self.build_envelope(self.org_a, "prsp_conc_2", company_name)

        barrier = threading.Barrier(2)
        results = [None, None]
        errors = [None, None]

        def worker(index, envelope):
            connections.close_all()
            try:
                client = APIClient()
                client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.raw_pat_a}")
                barrier.wait()
                resp = client.post("/api/integrations/bop/v1/events/", envelope, format="json")
                results[index] = resp
            except Exception as e:
                errors[index] = e
            finally:
                connections.close_all()

        t1 = threading.Thread(target=worker, args=(0, env1))
        t2 = threading.Thread(target=worker, args=(1, env2))

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertIsNone(errors[0])
        self.assertIsNone(errors[1])
        self.assertEqual(results[0].status_code, status.HTTP_201_CREATED)
        self.assertEqual(results[1].status_code, status.HTTP_201_CREATED)
        self.assertTrue(results[0].data["processed"])
        self.assertTrue(results[1].data["processed"])

        set_rls_context(self.org_a.id)
        # Exactly ONE Account created
        accounts = Account.objects.filter(org=self.org_a, name__iexact=company_name)
        self.assertEqual(accounts.count(), 1)

        # Exactly TWO Leads created
        leads = Lead.objects.filter(org=self.org_a, company_name__iexact=company_name)
        self.assertEqual(leads.count(), 2)

        # Exactly TWO ExternalEntityMaps created
        maps = ExternalEntityMap.objects.filter(
            org=self.org_a,
            source_app="bopclients",
            external_entity_type="prospect",
        )
        self.assertEqual(maps.count(), 2)

        map1 = ExternalEntityMap.objects.get(external_entity_id="prsp_conc_1")
        map2 = ExternalEntityMap.objects.get(external_entity_id="prsp_conc_2")
        self.assertNotEqual(map1.object_id, map2.object_id)
        clear_rls_context()

    def test_concurrent_prospect_ingestion_case_variation(self):
        """
        Case variation concurrency: "Acme Solar" vs "ACME SOLAR" within same org.
        Expected:
        - exactly ONE Account
        - exactly TWO Leads
        - exactly TWO ExternalEntityMaps
        """
        env1 = self.build_envelope(self.org_a, "prsp_case_1", "Acme Solar")
        env2 = self.build_envelope(self.org_a, "prsp_case_2", "ACME SOLAR")

        barrier = threading.Barrier(2)
        results = [None, None]
        errors = [None, None]

        def worker(index, envelope):
            connections.close_all()
            try:
                client = APIClient()
                client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.raw_pat_a}")
                barrier.wait()
                resp = client.post("/api/integrations/bop/v1/events/", envelope, format="json")
                results[index] = resp
            except Exception as e:
                errors[index] = e
            finally:
                connections.close_all()

        t1 = threading.Thread(target=worker, args=(0, env1))
        t2 = threading.Thread(target=worker, args=(1, env2))

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertIsNone(errors[0])
        self.assertIsNone(errors[1])
        self.assertEqual(results[0].status_code, status.HTTP_201_CREATED)
        self.assertEqual(results[1].status_code, status.HTTP_201_CREATED)
        self.assertTrue(results[0].data["processed"])
        self.assertTrue(results[1].data["processed"])

        set_rls_context(self.org_a.id)
        # Exactly ONE Account created
        accounts = Account.objects.filter(org=self.org_a, name__iexact="Acme Solar")
        self.assertEqual(accounts.count(), 1)

        # Exactly TWO Leads created
        leads = Lead.objects.filter(org=self.org_a, company_name__iexact="Acme Solar")
        self.assertEqual(leads.count(), 2)

        # Exactly TWO ExternalEntityMaps created
        self.assertEqual(ExternalEntityMap.objects.filter(org=self.org_a).count(), 2)
        clear_rls_context()

    def test_concurrent_prospect_ingestion_different_orgs_allowed(self):
        """
        Concurrency across different tenants: Same company name ingested into Org A and Org B concurrently.
        Expected:
        - Two Accounts (one per tenant)
        - Tenant isolation preserved
        """
        env1 = self.build_envelope(self.org_a, "prsp_multi_1", "Universal Solar Corp")
        env2 = self.build_envelope(self.org_b, "prsp_multi_2", "Universal Solar Corp")

        barrier = threading.Barrier(2)
        results = [None, None]
        errors = [None, None]

        def worker(index, envelope, raw_pat):
            connections.close_all()
            try:
                client = APIClient()
                client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw_pat}")
                barrier.wait()
                resp = client.post("/api/integrations/bop/v1/events/", envelope, format="json")
                results[index] = resp
            except Exception as e:
                errors[index] = e
            finally:
                connections.close_all()

        t1 = threading.Thread(target=worker, args=(0, env1, self.raw_pat_a))
        t2 = threading.Thread(target=worker, args=(1, env2, self.raw_pat_b))

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertIsNone(errors[0])
        self.assertIsNone(errors[1])
        self.assertEqual(results[0].status_code, status.HTTP_201_CREATED)
        self.assertEqual(results[1].status_code, status.HTTP_201_CREATED)

        set_rls_context(self.org_a.id)
        self.assertEqual(Account.objects.filter(org=self.org_a, name="Universal Solar Corp").count(), 1)
        clear_rls_context()

        set_rls_context(self.org_b.id)
        self.assertEqual(Account.objects.filter(org=self.org_b, name="Universal Solar Corp").count(), 1)
        clear_rls_context()
