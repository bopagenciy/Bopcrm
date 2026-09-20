import uuid
from django.core.exceptions import ValidationError
from django.test import TestCase

from accounts.models import Account
from bop_integration.models import BopEventLog, ExternalEntityMap
from bop_integration.services import ingest_prospect_ready_for_crm
from common.models import Org, Profile, User
from common.tasks import clear_rls_context, set_rls_context
from leads.models import Lead
from leads.serializer import LeadSerializer
from leads.services import convert_lead_to_account


class LeadAccountAssociationTestCase(TestCase):
    """
    Test suite for Phase CRM-I1D.4B.1: Native Lead-Account Association.
    Verifies persistent, tenant-safe, identity-based association between Bop CRM Lead and Account.
    """

    def setUp(self):
        self.org_a = Org.objects.create(name="Assoc Org A", bop_organization_id=uuid.uuid4())
        self.org_b = Org.objects.create(name="Assoc Org B", bop_organization_id=uuid.uuid4())

        self.user_a = User.objects.create_user(email="user_a_assoc@test.com", password="pwd")
        self.user_b = User.objects.create_user(email="user_b_assoc@test.com", password="pwd")

        self.profile_a = Profile.objects.create(user=self.user_a, org=self.org_a, role="ADMIN")
        self.profile_b = Profile.objects.create(user=self.user_b, org=self.org_b, role="ADMIN")

        set_rls_context(self.org_a.id)

    def tearDown(self):
        clear_rls_context()

    def _create_event_log(self, org, prospect_id, company_name):
        return BopEventLog.objects.create(
            org=org,
            event_id=str(uuid.uuid4()),
            source_app="bopclients",
            event_type="prospect.ready_for_crm",
            event_version=2,
            external_entity_type="prospect",
            external_entity_id=str(prospect_id),
            status="received",
            payload={
                "prospect_id": str(prospect_id),
                "company_name": company_name,
                "lead_score": 85,
                "priority": "HIGH",
                "source": "manual",
                "website": "https://example.com",
            },
        )

    def test_ingestion_creates_account_linked_lead(self):
        """A. Ingestion creates Account-linked Lead with identical tenant org."""
        prospect_id = uuid.uuid4()
        event = self._create_event_log(self.org_a, prospect_id, "Acme Robotics")

        result = ingest_prospect_ready_for_crm(event)
        self.assertTrue(result["created"])
        account = result["account"]
        lead = result["lead"]

        self.assertIsNotNone(account)
        self.assertIsNotNone(lead)
        self.assertEqual(lead.account_id, account.id)
        self.assertEqual(lead.account.name, "Acme Robotics")
        self.assertEqual(lead.org_id, account.org_id)
        self.assertEqual(lead.status, "assigned")

    def test_existing_account_reuse_preserves_exact_identity(self):
        """B. Existing Account reuse preserves exact Account identity and links to Lead."""
        existing_account = Account.objects.create(
            org=self.org_a,
            name="Existing Heavy Industries",
            website="https://heavy.com",
        )

        prospect_id = uuid.uuid4()
        event = self._create_event_log(self.org_a, prospect_id, "existing heavy industries")

        result = ingest_prospect_ready_for_crm(event)
        self.assertTrue(result["created"])
        self.assertEqual(result["account"].id, existing_account.id)
        self.assertEqual(result["lead"].account_id, existing_account.id)

    def test_native_lead_has_account_null_by_default(self):
        """C. Native Lead created without account has account=None by default."""
        lead = Lead.objects.create(
            org=self.org_a,
            first_name="Native",
            last_name="Lead",
            company_name="Independent Corp",
        )
        self.assertIsNone(lead.account_id)
        self.assertIsNone(lead.account)

    def test_foreign_tenant_account_association_rejected(self):
        """D. Foreign-tenant Account association is rejected by clean() and save()."""
        set_rls_context(self.org_b.id)
        account_b = Account.objects.create(
            org=self.org_b,
            name="Foreign Tenant Account",
        )
        set_rls_context(self.org_a.id)

        lead_a = Lead(
            org=self.org_a,
            company_name="Tenant A Lead",
            account=account_b,
        )

        with self.assertRaises(ValidationError):
            lead_a.clean()

        with self.assertRaises(ValidationError):
            lead_a.save()

    def test_serializer_returns_same_tenant_account(self):
        """E. Serializer returns same-tenant Account data {id, name}."""
        account = Account.objects.create(
            org=self.org_a,
            name="Serializer Test Account",
        )
        lead = Lead.objects.create(
            org=self.org_a,
            company_name="Serializer Test Lead",
            account=account,
        )

        serializer = LeadSerializer(instance=lead)
        self.assertIsNotNone(serializer.data["account"])
        self.assertEqual(serializer.data["account"]["id"], str(account.id))
        self.assertEqual(serializer.data["account"]["name"], "Serializer Test Account")

    def test_serializer_does_not_expose_foreign_tenant_account(self):
        """F. Serializer does not expose foreign-tenant Account even if directly assigned."""
        set_rls_context(self.org_b.id)
        account_b = Account.objects.create(
            org=self.org_b,
            name="Tenant B Account",
        )
        set_rls_context(self.org_a.id)

        lead = Lead.objects.create(
            org=self.org_a,
            company_name="Tenant A Lead",
        )
        # Force account_id without save() validation to test serializer defense
        Lead.objects.filter(id=lead.id).update(account=account_b)
        lead.refresh_from_db()

        serializer = LeadSerializer(instance=lead)
        self.assertIsNone(serializer.data["account"])

    def test_idempotent_replay_preserves_exact_relationship(self):
        """G. Idempotent replay preserves exact relationship without re-resolving."""
        prospect_id = uuid.uuid4()
        event1 = self._create_event_log(self.org_a, prospect_id, "Replay Corp")
        result1 = ingest_prospect_ready_for_crm(event1)
        self.assertTrue(result1["created"])

        # Replay the same prospect_id
        event2 = self._create_event_log(self.org_a, prospect_id, "Replay Corp")
        result2 = ingest_prospect_ready_for_crm(event2)
        self.assertFalse(result2["created"])
        self.assertEqual(result2["account"].id, result1["account"].id)
        self.assertEqual(result2["lead"].id, result1["lead"].id)
        self.assertEqual(result2["lead"].account_id, result1["account"].id)

    def test_account_name_change_does_not_redirect_association(self):
        """H. Account name changes do not redirect association on replay."""
        prospect_id = uuid.uuid4()
        event1 = self._create_event_log(self.org_a, prospect_id, "Original Name")
        result1 = ingest_prospect_ready_for_crm(event1)
        account = result1["account"]

        # Rename account in CRM
        account.name = "Renamed Holdings"
        account.save()

        # Replay event with old company_name in payload
        event2 = self._create_event_log(self.org_a, prospect_id, "Original Name")
        result2 = ingest_prospect_ready_for_crm(event2)

        self.assertFalse(result2["created"])
        # Must return the verified linked account, NOT search by "Original Name" and create another!
        self.assertEqual(result2["account"].id, account.id)
        self.assertEqual(result2["account"].name, "Renamed Holdings")

    def test_account_deletion_follows_set_null_semantics(self):
        """I. Account deletion follows SET_NULL semantics without deleting Lead."""
        account = Account.objects.create(
            org=self.org_a,
            name="Temporary Account",
        )
        lead = Lead.objects.create(
            org=self.org_a,
            company_name="Surviving Lead",
            account=account,
        )

        account.delete()
        lead.refresh_from_db()
        self.assertIsNone(lead.account_id)
        self.assertEqual(lead.company_name, "Surviving Lead")

    def test_lead_conversion_does_not_create_duplicate_account(self):
        """J. Lead conversion reuses existing lead.account without creating duplicate Account."""
        account = Account.objects.create(
            org=self.org_a,
            name="Enterprise Pre-linked Account",
        )
        lead = Lead.objects.create(
            org=self.org_a,
            first_name="Jane",
            last_name="Executive",
            email="jane@enterprise.com",
            company_name="Different Trade Name",
            account=account,
        )

        class DummyRequest:
            def __init__(self, profile):
                self.profile = profile

        req = DummyRequest(self.profile_a)
        conv_account, conv_contact, conv_opp = convert_lead_to_account(lead, req, create_opportunity=False)

        self.assertEqual(conv_account.id, account.id)
        # Ensure no duplicate account was created
        self.assertEqual(Account.objects.filter(org=self.org_a).count(), 1)
        lead.refresh_from_db()
        self.assertEqual(lead.status, "converted")
        self.assertEqual(lead.account_id, account.id)

    def test_pii_free_lead_remains_assigned_without_conversion(self):
        """K. Existing PII-free Lead remains in 'assigned' status without forced conversion."""
        prospect_id = uuid.uuid4()
        event = self._create_event_log(self.org_a, prospect_id, "PII Free Enterprise")

        result = ingest_prospect_ready_for_crm(event)
        lead = result["lead"]

        self.assertEqual(lead.status, "assigned")
        self.assertIsNone(lead.email)
        self.assertIsNone(lead.first_name)
        self.assertIsNone(lead.last_name)
        self.assertIsNotNone(lead.account)

        # Attempting conversion without email must raise ValidationError
        class DummyRequest:
            def __init__(self, profile):
                self.profile = profile

        with self.assertRaises(ValidationError):
            convert_lead_to_account(lead, DummyRequest(self.profile_a))

    def test_regression_external_entity_map_and_custom_fields(self):
        """L. Ingestion maintains ExternalEntityMap to Lead and preserves custom_fields."""
        prospect_id = uuid.uuid4()
        event = self._create_event_log(self.org_a, prospect_id, "Regression Corp")

        result = ingest_prospect_ready_for_crm(event)
        lead = result["lead"]
        account = result["account"]
        ext_map = result["external_map"]

        self.assertEqual(ext_map.object_id, lead.id)
        self.assertEqual(ext_map.content_object, lead)
        self.assertEqual(lead.custom_fields["bop_clients"]["lead_score"], 85)
        self.assertEqual(lead.custom_fields["bop_clients"]["priority"], "HIGH")
        self.assertEqual(lead.account_id, account.id)

    def test_conversion_inactive_account_fallback(self):
        """M. Conversion falls back to active account creation if pre-linked account was deactivated."""
        inactive_account = Account.objects.create(
            org=self.org_a,
            name="Deactivated Corp",
            is_active=False,
        )
        lead = Lead.objects.create(
            org=self.org_a,
            first_name="Active",
            last_name="User",
            email="active.user@example.com",
            company_name="Active Corp New",
            account=inactive_account,
        )

        class DummyRequest:
            def __init__(self, profile):
                self.profile = profile

        req = DummyRequest(self.profile_a)
        conv_account, conv_contact, conv_opp = convert_lead_to_account(
            lead, req, create_opportunity=False
        )

        self.assertNotEqual(conv_account.id, inactive_account.id)
        self.assertTrue(conv_account.is_active)
        self.assertEqual(conv_account.name, "Active Corp New")
        lead.refresh_from_db()
        self.assertEqual(lead.account_id, conv_account.id)
