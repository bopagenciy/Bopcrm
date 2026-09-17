from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from common.base import BaseOrgModel


class ExternalEntityMapQuerySet(models.QuerySet):
    """
    QuerySet hardening for ExternalEntityMap to ensure bulk operations
    cannot bypass tenant safety and GenericForeignKey cross-tenant checks.
    """

    def bulk_create(self, objs, *args, **kwargs):
        for obj in objs:
            if hasattr(obj, "full_clean"):
                obj.full_clean()
        return super().bulk_create(objs, *args, **kwargs)

    def update(self, **kwargs):
        restricted_fields = {
            "org",
            "org_id",
            "content_type",
            "content_type_id",
            "object_id",
            "content_object",
            "external_entity_id",
            "source_app",
            "external_entity_type",
        }
        if restricted_fields.intersection(kwargs.keys()):
            raise ValidationError(
                "Direct bulk update of identity or mapping fields on ExternalEntityMap is disabled for tenant safety."
            )
        return super().update(**kwargs)


class ExternalEntityMapManager(models.Manager.from_queryset(ExternalEntityMapQuerySet)):
    pass


class ExternalEntityMap(BaseOrgModel):
    """
    Tenant-scoped mapping table connecting external Bop Universe entity IDs
    (e.g., prospect ID from Bop Clients, customer ID from Bop ERP) to native BottleCRM entities.

    Protected by PostgreSQL RLS via BaseOrgModel (org FK).
    Enforces cross-tenant protection on GenericForeignKey assignments.
    """

    objects = ExternalEntityMapManager()

    source_app = models.CharField(
        _("Source Application"),
        max_length=64,
        help_text="Identifier of the source system (e.g., 'bop_clients', 'bop_erp', 'bop_social')",
    )
    external_entity_type = models.CharField(
        _("External Entity Type"),
        max_length=64,
        help_text="Type of the entity in the source system (e.g., 'prospect', 'customer')",
    )
    external_entity_id = models.CharField(
        _("External Entity ID"),
        max_length=255,
        help_text="Primary identifier of the entity in the source system",
    )
    idempotency_key = models.CharField(
        _("Idempotency Key"),
        max_length=255,
        blank=True,
        null=True,
        help_text="Optional unique key to ensure idempotent creation per organization",
    )

    # Generic relation to target BottleCRM object (Lead, Account, Contact, etc.)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.UUIDField()
    content_object = GenericForeignKey("content_type", "object_id")

    class Meta:
        verbose_name = "External Entity Map"
        verbose_name_plural = "External Entity Maps"
        db_table = "external_entity_map"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["org", "-created_at"]),
            models.Index(
                fields=["org", "source_app", "external_entity_type", "external_entity_id"],
                name="ext_map_lookup_idx",
            ),
            models.Index(fields=["content_type", "object_id"], name="ext_map_target_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["org", "source_app", "external_entity_type", "external_entity_id"],
                name="unique_external_entity_map_per_org",
            ),
            models.UniqueConstraint(
                fields=["org", "idempotency_key"],
                name="unique_external_entity_idempotency_per_org",
                condition=Q(idempotency_key__isnull=False) & ~Q(idempotency_key=""),
            ),
        ]

    def __str__(self):
        return f"[{self.source_app}] {self.external_entity_type}:{self.external_entity_id} -> {self.content_type.model}:{self.object_id} ({self.org.name})"

    def clean(self):
        super().clean()
        # Cross-Tenant Generic Foreign Key Guard:
        # Verify that the target content_object belongs to the SAME tenant organization.
        if self.content_type_id and self.object_id and self.org_id:
            target_org_id = None
            if self.content_object is not None:
                target_org_id = getattr(self.content_object, "org_id", None)

            if target_org_id is None:
                # Target object might be hidden by PostgreSQL RLS because it belongs to another tenant
                model_cls = self.content_type.model_class()
                if model_cls and hasattr(model_cls, "org"):
                    table_name = model_cls._meta.db_table
                    from django.db import connection
                    with connection.cursor() as cursor:
                        cursor.execute(
                            f"SELECT org_id FROM {table_name} WHERE id = %s", [str(self.object_id)]
                        )
                        row = cursor.fetchone()
                        if row:
                            target_org_id = row[0]

            if target_org_id is not None and str(target_org_id) != str(self.org_id):
                raise ValidationError("Referenced CRM entity must belong to the same organization")
            elif target_org_id is None:
                # Object does not exist or is hidden by RLS from another tenant
                raise ValidationError("Referenced CRM entity must belong to the same organization")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class BopEventLog(BaseOrgModel):
    """
    Tenant-scoped audit and inbox log for inbound/outbound events from Bop Universe.

    Provides idempotent event tracking, retry handling, and status lifecycle across Bop apps.
    """

    STATUS_CHOICES = (
        ("received", "Received"),
        ("processing", "Processing"),
        ("processed", "Processed"),
        ("failed", "Failed"),
    )

    event_id = models.CharField(
        _("Event ID"),
        max_length=255,
        help_text="Unique event UUID sent by the Bop source application",
    )
    source_app = models.CharField(
        _("Source Application"),
        max_length=64,
        help_text="Origin app (e.g., 'bop_clients', 'bop_chatbot')",
    )
    event_type = models.CharField(
        _("Event Type"),
        max_length=128,
        help_text="Domain event name (e.g., 'prospect.ready_for_crm')",
    )
    event_version = models.PositiveIntegerField(
        _("Event Version"),
        default=1,
        help_text="Canonical schema version of the event",
    )
    correlation_id = models.CharField(
        _("Correlation ID"),
        max_length=255,
        blank=True,
        null=True,
        db_index=True,
        help_text="Cross-application correlation identifier",
    )
    causation_id = models.CharField(
        _("Causation ID"),
        max_length=255,
        blank=True,
        null=True,
        help_text="Direct causal event identifier",
    )
    external_entity_type = models.CharField(
        _("External Entity Type"),
        max_length=64,
        blank=True,
        null=True,
        help_text="Domain entity type in source application (e.g. 'prospect')",
    )
    external_entity_id = models.CharField(
        _("External Entity ID"),
        max_length=255,
        blank=True,
        null=True,
    )
    idempotency_key = models.CharField(
        _("Idempotency Key"),
        max_length=255,
        blank=True,
        null=True,
        help_text="Unique key for deduplication across retries",
    )
    payload = models.JSONField(
        default=dict,
        blank=True,
        help_text="Full event JSON payload",
    )
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Contextual event metadata dictionary",
    )
    status = models.CharField(
        _("Status"),
        max_length=32,
        choices=STATUS_CHOICES,
        default="received",
    )
    attempt_count = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True, null=True)
    received_at = models.DateTimeField(default=timezone.now)
    processed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        verbose_name = "Bop Event Log"
        verbose_name_plural = "Bop Event Logs"
        db_table = "bop_event_log"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["org", "-created_at"]),
            models.Index(fields=["org", "status"], name="bop_evt_status_idx"),
            models.Index(fields=["org", "source_app", "event_type"], name="bop_evt_src_type_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["org", "event_id"],
                name="unique_bop_event_id_per_org",
            ),
            models.UniqueConstraint(
                fields=["org", "idempotency_key"],
                name="unique_bop_event_idempotency_per_org",
                condition=Q(idempotency_key__isnull=False) & ~Q(idempotency_key=""),
            ),
        ]

    def __str__(self):
        return f"[{self.source_app}] {self.event_type} ({self.status}) - {self.event_id}"
