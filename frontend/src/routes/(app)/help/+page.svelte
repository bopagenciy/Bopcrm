<script>
  /**
   * Help.
   *
   * ── TWO TIERS, ONE PAGE ──────────────────────────────────────────────────
   * "Start here" is always shown, because somebody who opens Help is stuck and
   * the fastest fix is usually a page they already have. Below it the page
   * splits on `data.available`, which the load sets from whether the enterprise
   * support queue answered:
   *
   *   available   their tickets with the BottleCRM team, and a way to open one
   *   otherwise   how to reach a person, and what to tell them
   *
   * The second tier is not a degraded state, it is the whole of what a
   * community deployment can offer, and it is the page this route served
   * before the queue existed. Rendering an error there would take away help
   * from the one person guaranteed to need it.
   *
   * ── WHAT THIS PAGE IS NOT ────────────────────────────────────────────────
   * v1's support page was 647 lines of mission statement and pricing rationale
   * shown to people who have ALREADY BOUGHT and are, by the fact of being here,
   * stuck. Sales copy belongs on the marketing site, a different repo.
   *
   * Nothing identifying is rendered: no org id, no token, no email, no user id.
   * A help page that prints an identifier is a help page that puts it in
   * screenshots.
   */
  import { resolve } from '$app/paths';
  import { asInternalPath } from '$lib/utils/paths.js';
  import PageHeader from '$lib/v2/components/PageHeader.svelte';
  import EmptyState from '$lib/v2/components/EmptyState.svelte';
  import Pill from '$lib/v2/components/Pill.svelte';
  import { relativeTime } from '$lib/v2/format.js';
  import { BookOpen, LifeBuoy, Plus, Bug, Mail, ArrowUpRight, ClipboardList } from '@lucide/svelte';
  import { t as i18n } from '$lib/i18n';

  /** @type {{ data: any }} */
  let { data } = $props();

  const STATUS_TONE = {
    open: 'rust',
    in_progress: 'clay',
    waiting_on_customer: 'sky',
    resolved: 'moss',
    closed: 'slate'
  };

  let SELF_SERVE = $derived([
    {
      href: '/solutions',
      icon: BookOpen,
      title: $i18n('nav.knowledge_base', {}, 'Base de conocimiento'),
      body: 'Respuestas y artículos preparados para tu equipo y clientes.'
    },
    {
      href: '/tickets',
      icon: LifeBuoy,
      title: 'Tus tickets',
      body: 'Todo lo abierto y en espera. Revisa la asignación de tus casos.'
    },
    {
      href: '/settings',
      icon: ClipboardList,
      title: $i18n('nav.settings', {}, 'Configuración'),
      body: 'Reglas de enrutamiento, escalamiento, horario laboral y correo entrante.'
    }
  ]);

  let CONTACT = $derived([
    {
      href: 'https://github.com/django-crm/Django-CRM/issues',
      icon: Bug,
      title: 'Reportar un error',
      body: 'Seguimiento de problemas en GitHub. La vía más rápida para errores reproducibles.',
      newTab: true
    },
    {
      href: 'mailto:support@bottlecrm.io',
      icon: Mail,
      title: 'Soporte por correo',
      body: 'Para temas de datos, facturación o problemas de acceso a la cuenta.',
      newTab: false
    }
  ]);

  let browser = $state('—');
  let windowSize = $state('—');
  $effect(() => {
    if (data.available) return;
    const ua = navigator.userAgent;
    const m = ua.match(/(Firefox|Edg|Chrome|Safari)\/([\d.]+)/);
    browser = m ? `${m[1] === 'Edg' ? 'Edge' : m[1]} ${m[2].split('.')[0]}` : 'Navegador desconocido';
    windowSize = `${window.innerWidth}×${window.innerHeight}`;
  });
</script>

<PageHeader title={$i18n('help.title', {}, 'Ayuda')} center width="920px">
  {#snippet sub()}
    {$i18n('help.subtitle', {}, 'Soluciónalo por ti mismo o contacta a alguien que pueda ayudarte')}
  {/snippet}
  {#snippet actions()}
    {#if data.available}
      <a class="v2-btn v2-btn-primary" href={resolve('/help/new')}><Plus />Nuevo ticket</a>
    {/if}
  {/snippet}
</PageHeader>

<div class="v2-scroll">
  <div
    class="v2-pad"
    style="padding-top:18px;padding-bottom:32px;max-width:920px;margin-inline:auto"
  >
    <div class="v2-label" style="margin-bottom:10px">Start here</div>
    <div class="cards">
      {#each SELF_SERVE as card (card.href)}
        <a class="v2-card card" href={resolve(asInternalPath(card.href))}>
          <card.icon size={17} />
          <div>
            <b>{card.title}</b>
            <p>{card.body}</p>
          </div>
        </a>
      {/each}
    </div>

    {#if data.available}
      <div class="v2-label" style="margin:26px 0 10px">Your support tickets</div>
      {#if data.tickets.length === 0}
        <EmptyState
          title="No support tickets"
          body="When you need help with BOP CRM, open a ticket here. Replies and status changes stay attached to it."
        >
          {#snippet icon()}<LifeBuoy size={21} />{/snippet}
          {#snippet actions()}
            <a class="v2-btn v2-btn-primary" href={resolve('/help/new')}>Open a ticket</a>
          {/snippet}
        </EmptyState>
      {:else}
        <div class="v2-table-wrap">
          <table class="v2-table">
            <thead>
              <tr>
                <th>Ticket</th>
                <th>Category</th>
                <th>Status</th>
                <th>Messages</th>
                <th class="v2-r">Updated</th>
              </tr>
            </thead>
            <tbody>
              {#each data.tickets as ticket (ticket.id)}
                <tr>
                  <td data-m="title">
                    <a class="v2-row-link" href={resolve(`/help/${ticket.id}`)}>
                      <span class="v2-table-primary">{ticket.subject}</span>
                      <span class="v2-sub" style="display:block;font-size:11px;margin-top:2px"
                        >{ticket.reference}</span
                      >
                    </a>
                  </td>
                  <td class="v2-muted">{ticket.categoryLabel}</td>
                  <td data-m="tag"
                    ><Pill tone={STATUS_TONE[ticket.status]}>{ticket.statusLabel}</Pill></td
                  >
                  <td class="v2-num v2-muted" data-m="hide">{ticket.messageCount}</td>
                  <td class="v2-r v2-muted" data-m="meta">{relativeTime(ticket.lastActivityAt)}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      {/if}
    {:else}
      <div class="v2-label" style="margin:26px 0 10px">If that did not do it</div>
      <div class="cards">
        {#each CONTACT as card (card.href)}
          <a
            class="v2-card card"
            href={card.href}
            rel={card.newTab ? 'noreferrer noopener' : undefined}
            target={card.newTab ? '_blank' : undefined}
          >
            <card.icon size={17} />
            <div>
              <b>
                {card.title}{#if card.newTab}<ArrowUpRight size={12} class="ext" />{/if}
              </b>
              <p>{card.body}</p>
            </div>
          </a>
        {/each}
      </div>

      <div class="v2-label" style="margin:26px 0 10px">What to include when you write</div>
      <div class="v2-card" style="padding:16px 18px">
        <p class="lead">
          Four things turn a two-day exchange into one message. The first two are already known.
        </p>
        <dl class="facts">
          <dt>Browser</dt>
          <dd class="v2-num">{browser}</dd>
          <dt>Window size</dt>
          <dd class="v2-num">{windowSize}</dd>
          <dt>What you expected</dt>
          <dd>The thing you were trying to do, in one sentence.</dd>
          <dt>What happened instead</dt>
          <dd>
            The exact wording of any error. "It didn't work" and "Something went wrong" are the same
            message to us.
          </dd>
        </dl>
        <p class="fine">
          Please do not paste screenshots containing an invoice link, an API token or a survey URL.
          Each of those is a working credential for whoever ends up holding it.
        </p>
      </div>
    {/if}
  </div>
</div>

<style>
  .cards {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
    gap: 12px;
  }
  .card {
    display: flex;
    gap: 11px;
    align-items: flex-start;
    padding: 15px 16px;
    color: inherit;
    text-decoration: none;
    transition: border-color 0.12s;
  }
  .card:hover {
    border-color: var(--v2-slate);
  }
  .card :global(svg) {
    flex: none;
    margin-top: 1px;
    color: var(--v2-slate);
  }
  .card b {
    display: flex;
    align-items: center;
    gap: 3px;
    font-size: 13.5px;
    font-weight: 600;
  }
  .card :global(.ext) {
    opacity: 0.5;
  }
  .card p {
    margin: 4px 0 0;
    font-size: 12px;
    color: var(--v2-slate);
    line-height: 1.5;
  }

  .lead {
    margin: 0 0 12px;
    font-size: 12.5px;
    color: var(--v2-slate);
  }
  .facts {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 8px 18px;
    margin: 0;
    font-size: 12.5px;
    line-height: 1.5;
  }
  .facts dt {
    color: var(--v2-slate);
    white-space: nowrap;
  }
  .facts dd {
    margin: 0;
  }
  .fine {
    margin: 14px 0 0;
    padding-top: 12px;
    border-top: 1px solid var(--v2-line);
    font-size: 11.5px;
    color: var(--v2-slate);
    line-height: 1.55;
  }
  @media (max-width: 768px) {
    .facts {
      grid-template-columns: 1fr;
      gap: 2px 0;
    }
    .facts dd {
      margin-bottom: 8px;
    }
  }
</style>
