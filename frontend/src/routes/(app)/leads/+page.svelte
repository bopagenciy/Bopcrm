<script>
  import { resolve } from '$app/paths';
  import { page } from '$app/state';
  import PageHeader from '$lib/v2/components/PageHeader.svelte';
  import FilterBar from '$lib/v2/components/FilterBar.svelte';
  import Pill from '$lib/v2/components/Pill.svelte';
  import Avatar from '$lib/v2/components/Avatar.svelte';
  import EmptyState from '$lib/v2/components/EmptyState.svelte';
  import { money, count, relativeDays, daysSince } from '$lib/v2/format.js';
  import { LEAD_STATUS_TONE, LEAD_STATUS_LABEL } from '$lib/v2/enums.js';
  import { Plus, Upload, Target } from '@lucide/svelte';
  import { t } from '$lib/terminology.js';
  import { t as i18n } from '$lib/i18n';

  /** @type {{ data: any }} */
  let { data } = $props();

  let leads = $derived(data.leads);
  let totals = $derived(data.totals);

  let terms = $derived(data.org?.terminology);
  let plural = $derived(t(terms, 'lead.plural', 'Prospectos'));
  let singular = $derived(t(terms, 'lead.singular', 'prospecto'));

  const stale = (lead) => (daysSince(lead.last_contacted ?? lead.created_at) ?? 0) > 7;
</script>

<PageHeader title={plural}>
  {#snippet sub()}
    <span class="v2-num">{count(totals.count)}</span> abiertos ·
    <span class="v2-num">{totals.unworked_over_a_week}</span> sin gestión por más de una semana
  {/snippet}
  {#snippet actions()}
    <button class="v2-btn"><Upload />{$i18n('common.import', {}, 'Importar')}</button>
    <a class="v2-btn v2-btn-primary" href={resolve('/leads/new')}><Plus />Nuevo {singular}</a>
  {/snippet}
</PageHeader>

<FilterBar
  page="leads"
  url={page.url}
  people={data.people}
  tags={data.tags}
  meId={data.meId}
  meta="Contactados menos recientemente primero"
/>

<div class="v2-scroll">
  {#if leads.length === 0}
    <EmptyState
      title="Aún no hay prospectos"
      body="Un prospecto es alguien que podría comprar, antes de saber lo suficiente para convertirlo en negocio. Importa una lista o agrega la última persona que te escribió."
    >
      {#snippet icon()}<Target size={21} />{/snippet}
      {#snippet actions()}
        <a class="v2-btn v2-btn-primary" href={resolve('/leads/new')}>Nuevo {singular}</a>
        <button class="v2-btn">{$i18n('common.import', {}, 'Importar')}</button>
      {/snippet}
    </EmptyState>
  {:else}
    <div class="v2-table-wrap">
      <table class="v2-table">
        <thead>
          <tr>
            <th>Prospecto</th>
            <th>Compañía</th>
            <th>Estado</th>
            <th>Fuente</th>
            <th class="v2-r">Valor est.</th>
            <th>Último contacto</th>
            <th>Propietario</th>
          </tr>
        </thead>
        <tbody>
          {#each leads as l (l.id)}
            <tr>
              <td>
                <a class="v2-row-link" href={resolve(`/leads/${l.id}`)}>
                  <div class="v2-table-primary">{l.first_name} {l.last_name}</div>
                  <div class="v2-table-secondary">{l.job_title}</div>
                </a>
              </td>
              <td>
                <div>{l.company_name}</div>
                <div class="v2-table-secondary" data-m="hide">{l.industry}</div>
              </td>
              <td data-m="tag"><Pill tone={LEAD_STATUS_TONE[l.status]}>{LEAD_STATUS_LABEL[l.status] ?? l.status}</Pill></td>
              <td class="v2-muted" data-m="hide" style="font-size:12.5px">{l.source}</td>
              <td class="v2-r v2-num"
                >{l.opportunity_amount ? money(l.opportunity_amount, l.currency) : '—'}</td
              >
              <td class:v2-muted={!stale(l)} class:overdue={stale(l)}>
                {#if l.last_contacted}
                  {relativeDays(l.last_contacted)}
                {:else}
                  <div>Sin contactar</div>
                  <!-- Stacked, matching the Company cell. Inline, these two ran
                       together into "Not contactedadded 64 days ago". -->
                  <div class="v2-table-secondary" data-m="hide">
                    added {relativeDays(l.created_at)}
                  </div>
                {/if}
              </td>
              <td data-m="hide"><Avatar name={l.assigned_to} size={22} /></td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
    <p class="v2-sub v2-pad" style="font-size:12px;padding-bottom:24px">
      Showing <span class="v2-num">{leads.length}</span> of
      <span class="v2-num">{count(totals.count)}</span>
    </p>
  {/if}
</div>

<style>
  /* A colour and a weight, not an inline style. The cell already carries a
     class for the ordinary case and the two should be stated the same way. */
  .overdue {
    color: var(--v2-rust);
    font-weight: 600;
  }
</style>
