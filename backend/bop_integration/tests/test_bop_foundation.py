import uuid

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection
from django.test import TestCase

from accounts.models import Account
from bop_integration.models import BopEventLog, ExternalEntityMap
from common.models import Org, Profile, User
from common.tasks import clear_rls_context, set_rls_context
from leads.models import Lead


class BopFoundationTestCase(TestCase):
    """
    Targeted tests for Phase CRM-I1A:
    A. bop_organization_id
    B. ExternalEntityMap
    C. BopEventLog
    D. RLS / Multi-tenant isolation
    """

    def setUp(self):
        # Create two isolated organizations
        self.org_a = Org.objects.create(name="Org Alpha")
        self.org_b = Org.objects.create(name="Org Beta")

        self.user_a = User.objects.create_user(email="admin_a@test.com", password="pass")
        self.user_b = User.objects.create_user(email="admin_b@test.com", password="pass")

        self.profile_a = Profile.objects.create(user=self.user_a, org=self.org_a, role="ADMIN")
        self.profile_b = Profile.objects.create(user=self.user_b, org=self.org_b, role="ADMIN")

        # Create native CRM entities
        set_rls_context(self.org_a.id)
        self.lead_a = Lead.objects.create(
            title="Lead A", first_name="John", last_name="Doe", org=self.org_a
        )
        self.account_a = Account.objects.create(name="Acme Corp", org=self.org_a)

        set_rls_context(self.org_b.id)
        self.lead_b = Lead.objects.create(
            title="Lead B", first_name="Jane", last_name="Smith", org=self.org_b
        )

        clear_rls_context()
        self.lead_ct = ContentType.objects.get_for_model(Lead)
        self.account_ct = ContentType.objects.get_for_model(Account)

    def tearDown(self):
        clear_rls_context()

    # =========================================================================
    # A. BOP ORGANIZATION ID TESTS
    # =========================================================================

    def test_bop_organization_id_nullable_by_default(self):
        """Org.bop_organization_id defaults to None."""
        self.assertIsNone(self.org_a.bop_organization_id)
        self.assertIsNone(self.org_b.bop_organization_id)

    def test_bop_organization_id_stores_valid_uuid(self):
        """Org.bop_organization_id accepts a valid UUID."""
        bop_uuid = uuid.uuid4()
        self.org_a.bop_organization_id = bop_uuid
        self.org_a.save()
        self.org_a.refresh_from_db()
        self.assertEqual(self.org_a.bop_organization_id, bop_uuid)

    def test_bop_organization_id_uniqueness(self):
        """Duplicate non-null bop_organization_id across Orgs must be rejected."""
        shared_uuid = uuid.uuid4()
        self.org_a.bop_organization_id = shared_uuid
        self.org_a.save()

        self.org_b.bop_organization_id = shared_uuid
        from django.db import transaction
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.org_b.save()

    # =========================================================================
    # B. EXTERNAL ENTITY MAP TESTS
    # =========================================================================

    def test_external_entity_map_creation(self):
        """Valid ExternalEntityMap creation for tenant entity."""
        set_rls_context(self.org_a.id)
        mapping = ExternalEntityMap.objects.create(
            org=self.org_a,
            source_app="bop_clients",
            external_entity_type="prospect",
            external_entity_id="ext-prospect-101",
            content_type=self.lead_ct,
            object_id=self.lead_a.id,
        )
        self.assertEqual(mapping.content_object, self.lead_a)

    def test_external_entity_map_same_external_id_in_different_orgs(self):
        """Same external entity ID can exist safely in distinct tenant orgs."""
        set_rls_context(self.org_a.id)
        ExternalEntityMap.objects.create(
            org=self.org_a,
            source_app="bop_clients",
            external_entity_type="prospect",
            external_entity_id="ext-prospect-common",
            content_type=self.lead_ct,
            object_id=self.lead_a.id,
        )

        set_rls_context(self.org_b.id)
        mapping_b = ExternalEntityMap.objects.create(
            org=self.org_b,
            source_app="bop_clients",
            external_entity_type="prospect",
            external_entity_id="ext-prospect-common",
            content_type=self.lead_ct,
            object_id=self.lead_b.id,
        )
        self.assertEqual(mapping_b.org, self.org_b)

    def test_external_entity_map_duplicate_in_same_org_rejected(self):
        """Duplicate mapping (org, source_app, external_entity_type, external_entity_id) is rejected."""
        set_rls_context(self.org_a.id)
        ExternalEntityMap.objects.create(
            org=self.org_a,
            source_app="bop_clients",
            external_entity_type="prospect",
            external_entity_id="ext-prospect-dup",
            content_type=self.lead_ct,
            object_id=self.lead_a.id,
        )

        from django.db import transaction
        with self.assertRaises((ValidationError, IntegrityError)):
            with transaction.atomic():
                ExternalEntityMap.objects.create(
                    org=self.org_a,
                    source_app="bop_clients",
                    external_entity_type="prospect",
                    external_entity_id="ext-prospect-dup",
                    content_type=self.lead_ct,
                    object_id=self.lead_a.id,
                )

    def test_external_entity_map_cross_tenant_generic_relation_rejected(self):
        """Mapping an external entity to a target object belonging to another Org via save() raises ValidationError."""
        set_rls_context(self.org_a.id)
        mapping = ExternalEntityMap(
            org=self.org_a,  # Org A mapping
            source_app="bop_clients",
            external_entity_type="prospect",
            external_entity_id="ext-prospect-cross-save",
            content_type=self.lead_ct,
            object_id=self.lead_b.id,  # Belongs to Org B!
        )
        with self.assertRaises(ValidationError) as ctx:
            mapping.save()
        self.assertIn("must belong to the same organization", str(ctx.exception))

    def test_external_entity_map_cross_tenant_create_rejected(self):
        """Mapping an external entity to a target object belonging to another Org via objects.create() raises ValidationError."""
        set_rls_context(self.org_a.id)
        with self.assertRaises(ValidationError) as ctx:
            ExternalEntityMap.objects.create(
                org=self.org_a,  # Org A mapping
                source_app="bop_clients",
                external_entity_type="prospect",
                external_entity_id="ext-prospect-cross-create",
                content_type=self.lead_ct,
                object_id=self.lead_b.id,  # Belongs to Org B!
            )
        self.assertIn("must belong to the same organization", str(ctx.exception))

    def test_external_entity_map_bulk_create_cross_tenant_rejected(self):
        """bulk_create() containing a cross-tenant mapping is rejected by full_clean validation."""
        set_rls_context(self.org_a.id)
        map_valid = ExternalEntityMap(
            org=self.org_a,
            source_app="bop_clients",
            external_entity_type="prospect",
            external_entity_id="ext-bulk-valid",
            content_type=self.lead_ct,
            object_id=self.lead_a.id,
        )
        map_cross = ExternalEntityMap(
            org=self.org_a,
            source_app="bop_clients",
            external_entity_type="prospect",
            external_entity_id="ext-bulk-cross",
            content_type=self.lead_ct,
            object_id=self.lead_b.id,  # Org B lead!
        )
        with self.assertRaises(ValidationError) as ctx:
            ExternalEntityMap.objects.bulk_create([map_valid, map_cross])
        self.assertIn("must belong to the same organization", str(str(ctx.exception)))

    def test_external_entity_map_bulk_update_restricted_rejected(self):
        """QuerySet.update() on mapping identity or target fields is rejected for tenant safety."""
        set_rls_context(self.org_a.id)
        mapping = ExternalEntityMap.objects.create(
            org=self.org_a,
            source_app="bop_clients",
            external_entity_type="prospect",
            external_entity_id="ext-update-test",
            content_type=self.lead_ct,
            object_id=self.lead_a.id,
        )
        with self.assertRaises(ValidationError) as ctx:
            ExternalEntityMap.objects.filter(id=mapping.id).update(object_id=self.lead_b.id)
        self.assertIn("Direct bulk update of identity or mapping fields", str(ctx.exception))

    # =========================================================================
    # C. BOP EVENT LOG TESTS
    # =========================================================================

    def test_bop_event_log_creation(self):
        """BopEventLog stores inbound event metadata and default status."""
        set_rls_context(self.org_a.id)
        event_uuid = str(uuid.uuid4())
        log = BopEventLog.objects.create(
            org=self.org_a,
            event_id=event_uuid,
            source_app="bop_clients",
            event_type="prospect.ready_for_crm",
            external_entity_id="ext-prospect-99",
            payload={"score": 85, "intent": "high"},
        )
        self.assertEqual(log.status, "received")
        self.assertEqual(log.payload["score"], 85)

    def test_bop_event_log_duplicate_event_id_rejected(self):
        """Duplicate event_id inside the same org is rejected by unique constraint."""
        set_rls_context(self.org_a.id)
        event_uuid = str(uuid.uuid4())
        BopEventLog.objects.create(
            org=self.org_a,
            event_id=event_uuid,
            source_app="bop_clients",
            event_type="prospect.ready_for_crm",
        )

        from django.db import transaction
        with self.assertRaises((ValidationError, IntegrityError)):
            with transaction.atomic():
                BopEventLog.objects.create(
                    org=self.org_a,
                    event_id=event_uuid,
                    source_app="bop_clients",
                    event_type="prospect.ready_for_crm",
                )

    def test_bop_event_log_duplicate_idempotency_key_rejected(self):
        """Duplicate idempotency_key inside the same org is rejected."""
        set_rls_context(self.org_a.id)
        idempotency = f"idem-{uuid.uuid4()}"
        BopEventLog.objects.create(
            org=self.org_a,
            event_id=str(uuid.uuid4()),
            source_app="bop_clients",
            event_type="prospect.ready_for_crm",
            idempotency_key=idempotency,
        )

        from django.db import transaction
        with self.assertRaises((ValidationError, IntegrityError)):
            with transaction.atomic():
                BopEventLog.objects.create(
                    org=self.org_a,
                    event_id=str(uuid.uuid4()),
                    source_app="bop_clients",
                    event_type="prospect.ready_for_crm",
                    idempotency_key=idempotency,
                )

    # =========================================================================
    # D. RLS & MULTI-TENANT ISOLATION TESTS
    # =========================================================================

    def test_rls_isolation_external_entity_map_and_event_log(self):
        """Verify that Postgres RLS policies enforce tenant isolation on integration tables."""
        if connection.vendor != "postgresql":
            self.skipTest("RLS tests require PostgreSQL vendor")

        # Create rows in both orgs
        set_rls_context(self.org_a.id)
        ExternalEntityMap.objects.create(
            org=self.org_a,
            source_app="bop_clients",
            external_entity_type="prospect",
            external_entity_id="ext-a",
            content_type=self.lead_ct,
            object_id=self.lead_a.id,
        )
        BopEventLog.objects.create(
            org=self.org_a,
            event_id="evt-a",
            source_app="bop_clients",
            event_type="test.event",
        )

        set_rls_context(self.org_b.id)
        ExternalEntityMap.objects.create(
            org=self.org_b,
            source_app="bop_clients",
            external_entity_type="prospect",
            external_entity_id="ext-b",
            content_type=self.lead_ct,
            object_id=self.lead_b.id,
        )
        BopEventLog.objects.create(
            org=self.org_b,
            event_id="evt-b",
            source_app="bop_clients",
            event_type="test.event",
        )

        # 1. Under Org A context, only Org A integration rows are returned
        set_rls_context(self.org_a.id)
        self.assertEqual(ExternalEntityMap.objects.count(), 1)
        self.assertEqual(ExternalEntityMap.objects.first().org, self.org_a)
        self.assertEqual(BopEventLog.objects.count(), 1)
        self.assertEqual(BopEventLog.objects.first().org, self.org_a)

        # 2. Switch to Org B context
        set_rls_context(self.org_b.id)
        self.assertEqual(ExternalEntityMap.objects.count(), 1)
        self.assertEqual(ExternalEntityMap.objects.first().org, self.org_b)
        self.assertEqual(BopEventLog.objects.count(), 1)
        self.assertEqual(BopEventLog.objects.first().org, self.org_b)

        # 3. Clear context -> fail-closed (0 rows returned)
        clear_rls_context()
        self.assertEqual(ExternalEntityMap.objects.count(), 0)
        self.assertEqual(BopEventLog.objects.count(), 0)
