<script>
  import { resolve } from '$app/paths';
  import { asInternalPath } from '$lib/utils/paths.js';
  /**
   * The settings hub.
   *
   * v1 has thirteen settings routes reachable only from a dropdown, so nobody
   * could tell what was configurable without opening each one. This lists them
   * with the current value beside each. A settings index that does not tell
   * you the current state is a table of contents, not a screen.
   *
   * Grouped by what a setting decides, not by which Django app owns it:
   * "who a ticket lands on" and "what closes it" belong together whether or
   * not they live in the same models file.
   *
   * `warn` is the second reason this page exists. Each destination reports
   * whether something there needs attention, so the hub is worth opening even
   * when you did not come to change anything. A warning here always has a
   * matching explanation on the page it points to, never a badge that leads
   * to a screen with nothing on it.
   *
   * Destinations v2 has not built are listed anyway and link to v1, marked as
   * such. An index that quietly omits settings is worse than one that admits
   * where they live: people go looking, find nothing, and conclude the feature
   * does not exist.
   */
  import PageHeader from '$lib/v2/components/PageHeader.svelte';
  import { count, shortDate } from '$lib/v2/format.js';
  import { ChevronRight, ShieldAlert } from '@lucide/svelte';
  import { t as i18n } from '$lib/i18n';

  /** @type {{ data: any }} */
  let { data } = $props();

  let org = $derived(data.org);

  let hoursSummary = $derived.by(() => {
    const open = data.calendar.days.filter((d) => d.open);
    if (!open.length) return 'Sin horario de atención configurado';
    const first = open[0];
    const uniform = open.every((d) => d.open === first.open && d.close === first.close);
    return uniform
      ? `${open.length} días, ${first.open}-${first.close}`
      : `${open.length} días, horario variable`;
  });

  let stuckApprovalRules = $derived(
    data.approvalRules.filter(
      (r) => r.is_active && r.approver_role === 'MANAGER' && !r.approvers.length
    ).length
  );

  let groups = $derived([
    {
      label: 'Personas y accesos',
      items: [
        {
          href: '/team',
          title: 'Equipo y accesos',
          body: 'Quién puede ingresar y lo que su rol le permite hacer.',
          value: data.peopleTotals
            ? `${data.peopleTotals.count} personas · ${data.peopleTotals.admins} admins`
            : null,
          warn: data.peopleTotals ? data.peopleTotals.tokens_on_deactivated > 0 : false
        },
        {
          href: '/settings/api-tokens',
          title: 'Tokens de API',
          body: 'Tokens de acceso personal para scripts, integraciones y agentes de IA.',
          value: data.tokenTotals ? `${data.tokenTotals.live} activos` : null,
          warn: data.tokenTotals
            ? data.tokenTotals.orphaned > 0 || data.tokenTotals.unused_90d > 0
            : false
        },
        {
          href: '/settings/web-forms',
          title: 'Formularios web',
          body: 'Formularios que integras en tu sitio web. Lo que completan se convierte en prospectos.',
          value: `${data.webFormTotals.published} publicados`,
          warn: data.webFormTotals.published > 0 && data.webFormTotals.submissions_30d === 0
        },
        {
          href: '/settings/organization',
          title: 'Organización',
          body: 'Los datos de la empresa impresos en facturas y cotizaciones.',
          value: org.company_name,
          warn: false
        }
      ]
    },
    {
      label: 'Gestión de tickets',
      items: [
        {
          href: '/settings/routing',
          title: 'Ruteo de tickets',
          body: 'A quién se le asigna un nuevo ticket según las reglas configuradas.',
          value: `${data.routingTotals.active} reglas`,
          warn: data.routingTotals.unrouted_last_30d > 0
        },
        {
          href: '/settings/escalation',
          title: 'Escalamiento',
          body: 'Qué ocurre cuando un ticket supera el tiempo límite de respuesta.',
          value: `${data.escalationTotals.active} de ${data.escalationTotals.count} prioridades`,
          warn: data.escalationTotals.breaches_unhandled_30d > 0
        },
        {
          href: '/settings/business-hours',
          title: 'Horario de atención',
          body: 'Horarios contra los cuales se mide el tiempo de respuesta del SLA.',
          value: `${data.calendar.name} · ${hoursSummary}`,
          warn: false
        },
        {
          href: '/settings/ticket-approvals',
          title: 'Reglas de aprobación',
          body: 'Qué condiciona el cierre de un ticket y quién puede aprobarlo.',
          value: `${data.approvalTotals.active} activas`,
          warn: stuckApprovalRules > 0
        },
        {
          href: '/settings/reopen',
          title: 'Política de reapertura',
          body: 'Determina si la respuesta de un cliente reabre un ticket cerrado.',
          value: !data.reopen
            ? null
            : data.reopen.is_enabled
              ? `Dentro de ${data.reopen.reopen_window_days} días`
              : 'Desactivada',
          warn: data.reopen ? !data.reopen.is_enabled : false
        },
        {
          href: '/settings/inbound-email',
          title: 'Correo entrante',
          body: 'Las cuentas de correo que convierten mensajes en tickets.',
          value: `${data.mailboxTotals.active} de ${data.mailboxTotals.count} activas`,
          warn: data.mailboxTotals.silently_dropping > 0
        }
      ]
    },
    {
      label: 'Palabras y campos compartidos',
      items: [
        {
          href: '/settings/macros',
          title: 'Plantillas de respuesta (Macros)',
          body: 'Respuestas predefinidas y variables sustituibles.',
          value: `${data.macroTotals.org} compartidas`,
          warn: data.macroTotals.with_unknown_placeholders > 0
        },
        {
          href: '/settings/tags',
          title: 'Etiquetas',
          body: 'Etiquetas compartidas entre empresas, prospectos, negocios y tickets.',
          value: `${data.tagTotals.active} en uso`,
          warn: false
        },
        {
          href: '/settings/custom-fields',
          title: 'Campos personalizados',
          body: 'Campos adicionales agregados por tu organización a los registros.',
          value: `${data.fieldTotals.active} en ${data.fieldTotals.models_extended} tipos de registros`,
          warn: data.fieldTotals.required_with_gaps > 0
        },
        {
          href: '/invoices/templates',
          title: 'Plantillas de factura',
          body: 'Aspecto visual de las facturas enviadas a los clientes.',
          value: 'En Facturas',
          warn: false
        }
      ]
    }
  ]);

  let warnings = $derived(groups.flatMap((g) => g.items).filter((i) => i.warn).length);
</script>

<PageHeader title={$i18n('settings.title', {}, 'Configuración')}>
  {#snippet sub()}
    {org.name} · <span class="v2-num">{count(org.member_count)}</span> miembros · desde
    {shortDate(org.created_at)}
    {#if warnings}
      · <span class="v2-num">{count(warnings)}</span> requieren atención
    {/if}
  {/snippet}
</PageHeader>

<div class="v2-scroll">
  <div class="v2-pad" style="padding-top:18px;padding-bottom:32px">
    {#each groups as g (g.label)}
      <div class="v2-label" style="margin-bottom:10px">{g.label}</div>
      <div class="v2-card" style="overflow:hidden;margin-bottom:22px">
        {#each g.items as s (s.href)}
          <a class="v2-setting" href={resolve(asInternalPath(s.href))}>
            <div class="v2-setting-body">
              <b>{s.title}</b>
              <span class="v2-sub" style="font-size:11.5px">{s.body}</span>
            </div>
            {#if s.warn}
              <ShieldAlert size={15} style="color:var(--v2-clay);flex:none" />
            {/if}
            {#if s.value}
              <span class="v2-sub v2-setting-value">{s.value}</span>
            {/if}
            <ChevronRight size={15} style="color:var(--v2-slate);flex:none" />
          </a>
        {/each}
      </div>
    {/each}

    <!--
      The org API key is deliberately absent from this page. It is a
      credential, it was once exposed through nested serializers, and a
      settings screen that renders it is how the next leak happens. Rotating
      or revealing it belongs behind an explicit, audited action, not on an
      index anyone with the URL can load.
    -->
    <p class="v2-sub" style="font-size:11.5px;margin-top:18px;max-width:64ch">
      The organisation API key is not shown here. Credentials are never rendered on a page you can
      arrive at by browsing. See
      <a href={resolve('/settings/api-tokens')} style="color:inherit">API tokens</a> for how token values
      are handled.
    </p>
  </div>
</div>

<style>
  .v2-setting-value {
    font-size: 12px;
    text-align: right;
  }

  /* At 414px the value column squeezes the title to a couple of words per
     line. Drop it. The destination and what it does are what you navigate
     by, and every value is repeated on the page it points to. */
  @media (max-width: 640px) {
    .v2-setting-value {
      display: none;
    }
  }
</style>
