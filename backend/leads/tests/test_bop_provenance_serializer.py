import pytest
from django.contrib.contenttypes.models import ContentType

from bop_integration.models import ExternalEntityMap
from common.testing import set_rls_context
from leads.models import Lead
from leads.serializer import LeadSerializer


@pytest.mark.django_db
class TestBopProvenanceSerializer:
    """Verify source_app serialization and tenant isolation for Bop Clients leads."""

    def test_serializer_with_external_entity_map(self, admin_user, org_a):
        set_rls_context(org_a)
        lead = Lead.objects.create(
            first_name="Test",
            last_name="Ingested",
            email="ingested@example.com",
            created_by=admin_user,
            org=org_a,
            custom_fields={
                "bop_clients": {
                    "prospect_id": "5d5cd7c6-df3d-400f-a94c-e6898d45aef9",
                    "lead_score": 50,
                    "priority": "MEDIUM",
                    "source": "manual",
                }
            },
        )
        lead_ct = ContentType.objects.get_for_model(Lead)
        ExternalEntityMap.objects.create(
            org=org_a,
            content_type=lead_ct,
            object_id=lead.id,
            source_app="bopclients",
            external_entity_type="prospect",
            external_entity_id="5d5cd7c6-df3d-400f-a94c-e6898d45aef9",
        )

        serializer = LeadSerializer(instance=lead)
        data = serializer.data
        assert data["source_app"] == "bopclients"
        assert "bop_clients" in data["custom_fields"]
        assert data["custom_fields"]["bop_clients"]["lead_score"] == 50

    def test_serializer_rejects_unverified_custom_fields_without_external_entity_map(self, admin_user, org_a):
        """A manual or unverified lead with bop_clients in custom_fields CANNOT claim source_app without ExternalEntityMap."""
        set_rls_context(org_a)
        lead = Lead.objects.create(
            first_name="Unverified",
            last_name="Lead",
            email="unverified@example.com",
            created_by=admin_user,
            org=org_a,
            custom_fields={"bop_clients": {"prospect_id": "fake-injected-id"}},
        )
        serializer = LeadSerializer(instance=lead)
        assert serializer.data["source_app"] is None

    def test_serializer_native_lead_has_no_source_app(self, admin_user, org_a):
        """Native CRM leads have source_app=None."""
        set_rls_context(org_a)
        lead = Lead.objects.create(
            first_name="Native",
            last_name="Lead",
            email="native@example.com",
            created_by=admin_user,
            org=org_a,
        )
        serializer = LeadSerializer(instance=lead)
        assert serializer.data["source_app"] is None

    def test_detail_api_includes_source_app(self, admin_client, admin_user, org_a):
        set_rls_context(org_a)
        lead = Lead.objects.create(
            first_name="API",
            last_name="Lead",
            email="api@example.com",
            created_by=admin_user,
            org=org_a,
            custom_fields={"bop_clients": {"lead_score": 75}},
        )
        lead_ct = ContentType.objects.get_for_model(Lead)
        ExternalEntityMap.objects.create(
            org=org_a,
            content_type=lead_ct,
            object_id=lead.id,
            source_app="bopclients",
            external_entity_type="prospect",
            external_entity_id="ext-123",
        )

        response = admin_client.get(f"/api/leads/{lead.id}/")
        assert response.status_code == 200
        lead_obj = response.json().get("lead_obj", {})
        assert lead_obj.get("source_app") == "bopclients"
        assert lead_obj.get("custom_fields", {}).get("bop_clients", {}).get("lead_score") == 75

    def test_cross_tenant_lead_isolation(self, org_b_client, admin_user, org_a, org_b):
        """Org B client cannot view or infer Org A's lead."""
        set_rls_context(org_a)
        lead = Lead.objects.create(
            first_name="Secret",
            last_name="Lead",
            email="secret@example.com",
            created_by=admin_user,
            org=org_a,
            custom_fields={"bop_clients": {"prospect_id": "secret-prospect"}},
        )

        set_rls_context(org_b)
        response = org_b_client.get(f"/api/leads/{lead.id}/")
        assert response.status_code == 404
