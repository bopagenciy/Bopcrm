import os
import uuid
import pytest
from django.test import TestCase
from django.db import connection, IntegrityError, DatabaseError
from django.contrib.contenttypes.models import ContentType
from common.models import Org
from leads.models import Lead
from bop_integration.models import ExternalEntityMap, BopEventLog
from common.tasks import set_rls_context, clear_rls_context


class PostgresRLSTenantSafetyTestCase(TestCase):
    """
    Focused PostgreSQL RLS integration tests for Phase CRM-I1A.1.
    Exercises actual PostgreSQL Row-Level Security policies without Python-level fallback.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.is_postgres = connection.vendor == "postgresql"
        if cls.is_postgres:
            with connection.cursor() as cursor:
                cursor.execute("SELECT usesuper FROM pg_user WHERE usename = current_user")
                row = cursor.fetchone()
                cls.is_superuser = row[0] if row else True
        else:
            cls.is_superuser = False

    def setUp(self):
        super().setUp()
        if not self.is_postgres:
            self.skipTest("RLS integration tests require PostgreSQL vendor")

        self.org_a = Org.objects.create(name="RLS Org A")
        self.org_b = Org.objects.create(name="RLS Org B")

        # Set RLS context to Org A to create Org A fixtures
        set_rls_context(self.org_a.id)
        self.lead_a = Lead.objects.create(title="Lead A", first_name="A", last_name="User", org=self.org_a)
        self.map_a = ExternalEntityMap.objects.create(
            org=self.org_a,
            source_app="bop_clients",
            external_entity_type="prospect",
            external_entity_id="ext-a-100",
            content_type=ContentType.objects.get_for_model(Lead),
            object_id=self.lead_a.id,
        )
        self.evt_a = BopEventLog.objects.create(
            org=self.org_a,
            event_id="evt-a-100",
            source_app="bop_clients",
            event_type="prospect.ready_for_crm",
        )

        # Set RLS context to Org B to create Org B fixtures
        set_rls_context(self.org_b.id)
        self.lead_b = Lead.objects.create(title="Lead B", first_name="B", last_name="User", org=self.org_b)
        self.map_b = ExternalEntityMap.objects.create(
            org=self.org_b,
            source_app="bop_clients",
            external_entity_type="prospect",
            external_entity_id="ext-b-100",
            content_type=ContentType.objects.get_for_model(Lead),
            object_id=self.lead_b.id,
        )
        self.evt_b = BopEventLog.objects.create(
            org=self.org_b,
            event_id="evt-b-100",
            source_app="bop_clients",
            event_type="prospect.ready_for_crm",
        )

        # Clear RLS context for individual test methods
        clear_rls_context()

    def tearDown(self):
        clear_rls_context()
        super().tearDown()

    def test_a_b_rls_external_entity_map_isolation(self):
        """Prove Org A context sees Org A ExternalEntityMap rows and CANNOT see Org B rows."""
        if self.is_superuser:
            self.skipTest("RLS is bypassed for DB superuser")

        with connection.cursor() as cursor:
            # Set RLS context to Org A
            cursor.execute("SELECT set_config('app.current_org', %s, false)", [str(self.org_a.id)])
            cursor.execute("SELECT id, external_entity_id FROM external_entity_map")
            rows_a = cursor.fetchall()
            self.assertEqual(len(rows_a), 1)
            self.assertEqual(str(rows_a[0][0]), str(self.map_a.id))
            self.assertEqual(rows_a[0][1], "ext-a-100")

            # Switch RLS context to Org B
            cursor.execute("SELECT set_config('app.current_org', %s, false)", [str(self.org_b.id)])
            cursor.execute("SELECT id, external_entity_id FROM external_entity_map")
            rows_b = cursor.fetchall()
            self.assertEqual(len(rows_b), 1)
            self.assertEqual(str(rows_b[0][0]), str(self.map_b.id))
            self.assertEqual(rows_b[0][1], "ext-b-100")

    def test_c_d_rls_bop_event_log_isolation(self):
        """Prove Org A context sees Org A BopEventLog rows and CANNOT see Org B rows."""
        if self.is_superuser:
            self.skipTest("RLS is bypassed for DB superuser")

        with connection.cursor() as cursor:
            # Set RLS context to Org A
            cursor.execute("SELECT set_config('app.current_org', %s, false)", [str(self.org_a.id)])
            cursor.execute("SELECT id, event_id FROM bop_event_log")
            rows_a = cursor.fetchall()
            self.assertEqual(len(rows_a), 1)
            self.assertEqual(str(rows_a[0][0]), str(self.evt_a.id))

            # Switch RLS context to Org B
            cursor.execute("SELECT set_config('app.current_org', %s, false)", [str(self.org_b.id)])
            cursor.execute("SELECT id, event_id FROM bop_event_log")
            rows_b = cursor.fetchall()
            self.assertEqual(len(rows_b), 1)
            self.assertEqual(str(rows_b[0][0]), str(self.evt_b.id))

    def test_e_empty_context_exposes_zero_rows(self):
        """Prove empty org context exposes zero rows (fail-closed)."""
        if self.is_superuser:
            self.skipTest("RLS is bypassed for DB superuser")

        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config('app.current_org', '', false)")

            cursor.execute("SELECT COUNT(*) FROM external_entity_map")
            self.assertEqual(cursor.fetchone()[0], 0)

            cursor.execute("SELECT COUNT(*) FROM bop_event_log")
            self.assertEqual(cursor.fetchone()[0], 0)

    def test_f_cross_tenant_insert_rejected_by_rls(self):
        """Prove cross-tenant INSERT (inserting Org B row under Org A context) is rejected by PostgreSQL RLS WITH CHECK."""
        if self.is_superuser:
            self.skipTest("RLS is bypassed for DB superuser")

        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config('app.current_org', %s, false)", [str(self.org_a.id)])
            new_id = uuid.uuid4()
            from django.db import transaction
            with self.assertRaises((IntegrityError, DatabaseError)):
                with transaction.atomic():
                    cursor.execute(
                        """
                        INSERT INTO bop_event_log
                        (id, event_id, source_app, event_type, status, attempt_count, payload, received_at, org_id, created_at, updated_at)
                        VALUES (%s, %s, 'bop_clients', 'cross.tenant', 'received', 0, '{}'::jsonb, NOW(), %s, NOW(), NOW())
                        """,
                        [str(new_id), str(uuid.uuid4()), str(self.org_b.id)],
                    )

    def test_g_cross_tenant_update_rejected_by_rls(self):
        """Prove cross-tenant UPDATE (updating Org B row under Org A context) modifies 0 rows due to RLS isolation."""
        if self.is_superuser:
            self.skipTest("RLS is bypassed for DB superuser")

        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config('app.current_org', %s, false)", [str(self.org_a.id)])
            cursor.execute(
                "UPDATE bop_event_log SET event_type = 'hacked' WHERE id = %s",
                [str(self.evt_b.id)],
            )
            updated_count = cursor.rowcount
            self.assertEqual(updated_count, 0, "PostgreSQL RLS must prevent updating another tenant's row")

    def test_bop_organization_id_database_behavior(self):
        """Prove bop_organization_id allows NULLs, rejects duplicate non-nulls, and accepts distinct UUIDs."""
        from django.db import transaction
        # 1. Multiple NULLs allowed
        org1 = Org.objects.create(name="Null Org 1", bop_organization_id=None)
        org2 = Org.objects.create(name="Null Org 2", bop_organization_id=None)
        self.assertIsNone(org1.bop_organization_id)
        self.assertIsNone(org2.bop_organization_id)

        # 2. Distinct non-null UUIDs accepted
        u1 = uuid.uuid4()
        u2 = uuid.uuid4()
        org1.bop_organization_id = u1
        org1.save()
        org2.bop_organization_id = u2
        org2.save()
        self.assertEqual(Org.objects.get(id=org1.id).bop_organization_id, u1)
        self.assertEqual(Org.objects.get(id=org2.id).bop_organization_id, u2)

        # 3. Duplicate non-null UUID rejected
        org3 = Org(name="Duplicate Org", bop_organization_id=u1)
        with self.assertRaises((IntegrityError, DatabaseError)):
            with transaction.atomic():
                org3.save()
