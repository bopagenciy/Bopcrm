<script>
  import { resolve } from '$app/paths';
  import { page } from '$app/state';
  import PageHeader from '$lib/v2/components/PageHeader.svelte';
  import SectionTabs from '$lib/v2/components/SectionTabs.svelte';
  import FilterBar from '$lib/v2/components/FilterBar.svelte';
  import StatCard from '$lib/v2/components/StatCard.svelte';
  import Pill from '$lib/v2/components/Pill.svelte';
  import EmptyState from '$lib/v2/components/EmptyState.svelte';
  import { money, count, shortDate, daysSince } from '$lib/v2/format.js';
  import { INVOICE_STATUS_TONE, invoiceStatusLabel } from '$lib/v2/enums.js';
  import { enhance } from '$app/forms';
  import { Plus, Receipt } from '@lucide/svelte';
  import { t as i18n } from '$lib/i18n';

  /** @type {{ data: any, form: any }} */
  let { data, form } = $props();

  let invoices = $derived(data.invoices);
  let totals = $derived(data.totals);

  /** Rows with a send in flight, so the button can show it is working. */
  let sending = $state(/** @type {Record<string, boolean>} */ ({}));

  const SETTLED = ['Paid', 'Cancelled'];

  function ageLabel(inv) {
    if (SETTLED.includes(inv.status)) return '—';
    if (!inv.due_date) return '—';
    const n = daysSince(inv.due_date);
    if (n > 0) return `${n}d atraso`;
    if (n === 0) return 'vence hoy';
    return `faltan ${Math.abs(n)}d`;
  }

  const isLate = (inv) =>
    !SETTLED.includes(inv.status) && inv.due_date && daysSince(inv.due_date) > 0;
</script>

<PageHeader title={$i18n('invoices.title', {}, 'Facturas')}>
  {#snippet sub()}
    <span class="v2-num">{count(totals.count)}</span> facturas ·
    <span class="v2-num">{money(totals.outstanding, data.org.currency)}</span> pendientes de cobro
  {/snippet}
  {#snippet actions()}
    <a class="v2-btn v2-btn-primary" href={resolve('/invoices/new')}><Plus />{$i18n('invoices.new_invoice', {}, 'Nueva factura')}</a>
  {/snippet}
</PageHeader>

<SectionTabs set="invoices" />

<div class="v2-pad" style="padding-top:16px;flex:none">
  <div class="v2-stats">
    <StatCard
      label="Vencidas"
      value={money(totals.overdue, data.org.currency)}
      tone="rust"
      detail="Cobrar primero estas"
    />
    <StatCard
      label="Vencen este mes"
      value={money(totals.due_this_month, data.org.currency)}
      tone="clay"
    />
    <StatCard
      label="Pagadas este trimestre"
      value={money(totals.paid_this_quarter, data.org.currency)}
      tone="moss"
    />
    <StatCard
      label="Borrador"
      value={money(totals.draft, data.org.currency)}
      tone="slate"
      detail="Aún no enviadas"
    />
  </div>
</div>

<FilterBar
  page="invoices"
  url={page.url}
  people={data.people}
  accounts={data.accounts}
  meId={data.meId}
  meta="Vencimiento más antiguo primero"
/>

{#if form?.error}
  <p class="v2-sub v2-pad" style="color:var(--v2-rust);font-size:12.5px;padding-top:10px">
    {form.error}
  </p>
{/if}

<div class="v2-scroll">
  {#if invoices.length === 0}
    <EmptyState
      title={$i18n('invoices.no_invoices', {}, 'Aún no hay facturas')}
      body="Las facturas aparecerán aquí una vez que crees una. Un negocio ganado suele ser el punto de partida."
    >
      {#snippet icon()}<Receipt size={21} />{/snippet}
      {#snippet actions()}
        <a class="v2-btn v2-btn-primary" href={resolve('/invoices/new')}>{$i18n('invoices.new_invoice', {}, 'Nueva factura')}</a>
        <a class="v2-btn" href={resolve('/pipeline')}>Ir al pipeline</a>
      {/snippet}
    </EmptyState>
  {:else}
    <div class="v2-table-wrap">
      <table class="v2-table">
        <thead>
          <tr>
            <th>Factura</th>
            <th>Empresa</th>
            <th>Estado</th>
            <th class="v2-r">Monto</th>
            <th>Vencimiento</th>
            <th class="v2-r">Antigüedad</th>
            <th style="width:130px"></th>
          </tr>
        </thead>
        <tbody>
          {#each invoices as inv (inv.id)}
            {@const late = isLate(inv)}
            <tr>
              <td>
                <a class="v2-row-link" href={resolve(`/invoices/${inv.id}`)}>
                  <span class="v2-table-primary v2-num" style="font-size:13px"
                    >{inv.invoice_number}</span
                  >
                </a>
              </td>
              <td>{inv.account.name}</td>
              <td>
                <Pill tone={INVOICE_STATUS_TONE[inv.status]}>{invoiceStatusLabel(inv.status)}</Pill>
              </td>
              <td class="v2-r v2-num" style="font-weight:600"
                >{money(inv.total_amount, inv.currency)}</td
              >
              <td>{shortDate(inv.due_date)}</td>
              <td
                class="v2-r v2-num"
                class:v2-muted={!late}
                style={late ? 'color:var(--v2-rust);font-weight:600' : ''}
              >
                {ageLabel(inv)}
              </td>
              <td>
                {#if inv.status === 'Overdue' || inv.status === 'Draft'}
                  <form
                    method="POST"
                    action="?/send"
                    use:enhance={() => {
                      sending[inv.id] = true;
                      return async ({ update }) => {
                        await update();
                        sending[inv.id] = false;
                      };
                    }}
                  >
                    <input type="hidden" name="id" value={inv.id} />
                    <button class="v2-btn v2-btn-sm" disabled={sending[inv.id]}>
                      {#if sending[inv.id]}Enviando…{:else if inv.status === 'Overdue'}Enviar recordatorio{:else}Enviar{/if}
                    </button>
                  </form>
                {/if}
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
    <p class="v2-sub v2-pad" style="font-size:12px;padding-bottom:24px">
      Showing <span class="v2-num">{invoices.length}</span> of
      <span class="v2-num">{count(totals.count)}</span>
    </p>
  {/if}
</div>
