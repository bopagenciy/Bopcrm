<script>
  import { SvelteURLSearchParams } from 'svelte/reactivity';
  import { resolve } from '$app/paths';
  import { asInternalPath } from '$lib/utils/paths.js';
  import { page } from '$app/state';
  import PageHeader from '$lib/v2/components/PageHeader.svelte';
  import FilterBar from '$lib/v2/components/FilterBar.svelte';
  import Pill from '$lib/v2/components/Pill.svelte';
  import Avatar from '$lib/v2/components/Avatar.svelte';
  import StageMeter from '$lib/v2/components/StageMeter.svelte';
  import EmptyState from '$lib/v2/components/EmptyState.svelte';
  import { money, count, shortDate } from '$lib/v2/format.js';
  import { STAGE_LABEL, AGING_TONE, AGING_LABEL } from '$lib/v2/enums.js';
  import { activeChips, activePresetKey, withoutParam } from '$lib/v2/filters.js';
  import { Columns3, List, Plus, TriangleAlert } from '@lucide/svelte';
  import { flip } from 'svelte/animate';
  import { dndzone } from 'svelte-dnd-action';
  import { invalidateAll } from '$app/navigation';
  import { deserialize } from '$app/forms';
  import { t as i18n } from '$lib/i18n';

  /** @type {{ data: any }} */
  let { data } = $props();

  const FLIP_MS = 160;

  let deals = $derived(data.deals);
  let totals = $derived(data.totals);
  let view = $derived(data.view);

  /* Lanes are built server-side from `/opportunities/kanban/`, which returns
     every stage with its true count. They used to be grouped on the client
     from whatever the list happened to return: correct only until the first
     page boundary, and wrong in the way that looks right: all the columns
     render, each is just short. */
  let lanes = $derived(data.lanes);

  /* `dndzone` reorders the array it is handed, so the board renders from a
     local copy. Rebuilt whenever the server sends new lanes, which is what
     makes a rejected move snap back: the action calls `invalidateAll()` and
     this effect overwrites the optimistic arrangement with the stored one. */
  let boardLanes = $state(/** @type {any[]} */ ([]));
  $effect(() => {
    boardLanes = lanes.map((/** @type {any} */ lane) => ({ ...lane, rows: [...lane.rows] }));
  });

  let moveError = $state('');

  /* The header has to describe the cards under it after an optimistic move,
     not the count the server sent before it. A capped lane keeps the server's
     total, since its own rows are not the whole story either way. */
  function laneCount(/** @type {any} */ lane) {
    return lane.truncated ? lane.count : lane.rows.length;
  }
  function laneSum(/** @type {any} */ lane) {
    return lane.rows.reduce((/** @type {number} */ total, /** @type {any} */ r) => total + r.amount, 0);
  }

  function onConsider(/** @type {any} */ lane, /** @type {any} */ e) {
    lane.rows = e.detail.items;
  }

  async function onFinalize(/** @type {any} */ lane, /** @type {any} */ e) {
    lane.rows = e.detail.items;
    const movedId = e.detail.info?.id;
    const index = e.detail.items.findIndex((/** @type {any} */ r) => r.id === movedId);
    // Finalize fires on both lanes of a cross-lane move. Only the lane now
    // holding the card knows where it landed, so only that one persists.
    if (index === -1) return;
    await persistMove(
      movedId,
      lane.stage,
      e.detail.items[index - 1]?.id,
      e.detail.items[index + 1]?.id
    );
  }

  /**
   * Both neighbours are sent when they exist. The server resolves them inside
   * the destination column and ignores any it cannot find there, so a board
   * another user has rearranged since this one loaded degrades to an append
   * rather than to a position computed from a card that has moved on.
   */
  async function persistMove(
    /** @type {string} */ id,
    /** @type {string} */ columnId,
    /** @type {string | undefined} */ aboveId,
    /** @type {string | undefined} */ belowId
  ) {
    const body = new FormData();
    body.set('id', id);
    body.set('column_id', columnId);
    if (aboveId) body.set('above_id', aboveId);
    if (belowId) body.set('below_id', belowId);
    try {
      const res = await fetch('?/move', { method: 'POST', body });
      const result = deserialize(await res.text());
      if (result.type === 'success') {
        moveError = '';
        return;
      }
      moveError =
        (result.type === 'failure' && /** @type {any} */ (result.data)?.error) ||
        'No se pudo mover el negocio; revertido.';
    } catch {
      moveError = 'No se pudo mover el negocio; revertido.';
    }
    await invalidateAll();
  }

  let isFiltered = $derived(
    activeChips('pipeline', page.url, { people: data.people, tags: data.tags }).length > 0 ||
      activePresetKey('pipeline', page.url, data.meId) !== 'all'
  );

  let listHref = $derived(withoutParam(page.url, 'view'));
  let boardHref = $derived.by(() => {
    const next = new SvelteURLSearchParams();
    next.set('view', 'board');
    for (const key of [...(data.boardFields ?? []), 'search']) {
      const value = page.url.searchParams.get(key);
      if (value) next.set(key, value);
    }
    return `/pipeline?${next}`;
  });
</script>

<PageHeader title="Pipeline">
  {#snippet sub()}
    <span class="v2-num">{count(totals.count)}</span> {$i18n('pipeline.deals_count', { count: '' }, 'negocios').trim()} ·
    <span class="v2-num">{money(totals.amount_sum, data.org.currency)}</span> ·
    <span class="v2-num">{money(totals.weighted_sum, data.org.currency)}</span> {$i18n('pipeline.weighted', {}, 'ponderado')} ·
    <span class="v2-num" style="color:var(--v2-rust)">{totals.stalled_count}</span> {$i18n('pipeline.stalled', {}, 'estancados')}
  {/snippet}
  {#snippet actions()}
    {#if view === 'board'}
      <a class="v2-btn v2-btn-quiet" href={resolve(asInternalPath(listHref))}><List />{$i18n('common.list', {}, 'Lista')}</a>
      <span class="v2-btn" aria-current="true"><Columns3 />{$i18n('common.board', {}, 'Tablero')}</span>
    {:else}
      <span class="v2-btn" aria-current="true"><List />{$i18n('common.list', {}, 'Lista')}</span>
      <a class="v2-btn v2-btn-quiet" href={resolve(asInternalPath(boardHref))}><Columns3 />{$i18n('common.board', {}, 'Tablero')}</a>
    {/if}
    <a class="v2-btn v2-btn-primary" href={resolve('/pipeline/new')}><Plus />{$i18n('pipeline.new_deal', {}, 'Nuevo negocio')}</a>
  {/snippet}
</PageHeader>

{#if isFiltered}
  <p class="v2-sub" style="font-size:11.5px;margin:8px 0 0">
    Estos números describen el pipeline filtrado.
  </p>
{/if}

<FilterBar
  page="pipeline"
  url={page.url}
  people={data.people}
  tags={data.tags}
  meId={data.meId}
  onlyFields={data.onlyFields}
  onlyPresets={data.onlyPresets}
  meta={view === 'board' ? 'Solo etapas abiertas. Arrastra una tarjeta para cambiar su etapa' : $i18n('pipeline.sorted_by_value', {}, 'Ordenado por valor')}
/>

{#if moveError}
  <div class="v2-pad" style="padding-top:12px;flex:none">
    <div class="v2-move-error" role="status">
      <TriangleAlert size={13} style="flex:none" />
      <span>{moveError}</span>
    </div>
  </div>
{/if}

{#if view === 'board'}
  <div class="v2-board">
    {#each boardLanes as lane (lane.stage)}
      <section class="v2-lane">
        <div class="v2-lane-head">
          <span class="v2-label">{STAGE_LABEL[lane.stage]}</span>
          <span class="v2-num"
            >{count(laneCount(lane))} · {money(laneSum(lane), data.org.currency)}</span
          >
        </div>
        {#if lane.truncated}
          <p class="v2-sub" style="padding:0 2px 6px;font-size:11.5px">
            Mostrando los primeros <span class="v2-num">{lane.rows.length}</span>. Filtra para ver más.
          </p>
        {/if}
        <div
          class="v2-lane-body"
          use:dndzone={{ items: lane.rows, flipDurationMs: FLIP_MS }}
          onconsider={(e) => onConsider(lane, e)}
          onfinalize={(e) => onFinalize(lane, e)}
        >
          {#each lane.rows as d (d.id)}
            <div class="v2-deal-card v2-card-drag" animate:flip={{ duration: FLIP_MS }}>
              <a
                href={resolve(`/pipeline/${d.id}`)}
                style="font-weight:600;letter-spacing:-0.012em;line-height:1.3;color:inherit;text-decoration:none"
                >{d.name}</a
              >
              <div class="v2-sub" style="margin-top:2px">{d.account.name}</div>
              <div style="margin-top:9px">
                <Pill tone={AGING_TONE[d.aging_status]} dot>
                  {AGING_LABEL[d.aging_status] +
                    (d.aging_status === 'green' ? '' : ` · ${d.days_in_current_stage}d`)}
                </Pill>
              </div>
              <div class="v2-deal-card-foot">
                <Avatar name={d.assigned_to} size={21} />
                <span class="v2-num" style="font-weight:600">{money(d.amount, d.currency)}</span>
                <span class="v2-sub" style="margin-left:auto;font-size:11.5px"
                  >{shortDate(d.closed_on)}</span
                >
              </div>
            </div>
          {:else}
            <p class="v2-sub" style="padding:10px 2px;font-size:12px">Sin negocios en esta etapa.</p>
          {/each}
        </div>
      </section>
    {/each}
  </div>
{:else if deals.length === 0}
  <div class="v2-scroll">
    <EmptyState
      title={$i18n('pipeline.no_deals', {}, 'No hay negocios aquí')}
      body={$i18n('pipeline.no_deals_sub', {}, 'No hay resultados para esta vista...')}
    >
      {#snippet icon()}<Columns3 size={21} />{/snippet}
      {#snippet actions()}
        <a class="v2-btn v2-btn-primary" href={resolve('/pipeline/new')}>{$i18n('pipeline.new_deal', {}, 'Nuevo negocio')}</a>
        <a class="v2-btn" href={resolve('/leads')}>{$i18n('pipeline.go_to_leads', {}, 'Ir a prospectos')}</a>
      {/snippet}
    </EmptyState>
  </div>
{:else}
  <div class="v2-scroll">
    <div class="v2-table-wrap">
      <table class="v2-table">
        <thead>
          <tr>
            <th>Negocio</th>
            <th>Etapa</th>
            <th>Salud</th>
            <th class="v2-r">Valor</th>
            <th>Cierre</th>
            <th class="v2-r">En etapa</th>
            <th>Propietario</th>
          </tr>
        </thead>
        <tbody>
          {#each deals as d (d.id)}
            <tr>
              <td>
                <a class="v2-row-link" href={resolve(`/pipeline/${d.id}`)}>
                  <div class="v2-table-primary">{d.name}</div>
                  <div class="v2-table-secondary">{d.account.name}</div>
                </a>
              </td>
              <td><StageMeter stage={d.stage} /></td>
              <td data-m="tag">
                <Pill tone={AGING_TONE[d.aging_status]} dot>{AGING_LABEL[d.aging_status]}</Pill>
              </td>
              <td class="v2-r v2-num" style="font-weight:600">{money(d.amount, d.currency)}</td>
              <td>{shortDate(d.closed_on)}</td>
              <!-- Hidden on a phone: the Health pill beside the title is computed
                   from this same number, so showing both spends a line to say
                   the same thing twice. -->
              <td
                class="v2-r v2-num"
                data-m="hide"
                style={d.aging_status === 'red'
                  ? 'color:var(--v2-rust);font-weight:600'
                  : 'color:var(--v2-slate)'}
              >
                {d.days_in_current_stage}d
              </td>
              <td data-m="hide"><Avatar name={d.assigned_to} size={22} /></td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
    <p class="v2-sub v2-pad" style="font-size:12px;padding-bottom:24px">
      Showing <span class="v2-num">{deals.length}</span> of
      <span class="v2-num">{count(totals.count)}</span>
    </p>
  </div>
{/if}
