<script>
  import { resolve } from '$app/paths';
  import { asInternalPath } from '$lib/utils/paths.js';
  import { page } from '$app/state';
  import {
    Sun,
    Columns3,
    Target,
    Building2,
    Users,
    CircleCheck,
    LifeBuoy,
    BookOpen,
    Receipt,
    Trophy,
    Clock,
    UserCog,
    CircleUser,
    CircleHelp,
    FileText,
    Bell,
    SlidersHorizontal,
    Search,
    Smartphone,
    LogOut
  } from '@lucide/svelte';
  import { t as tTerm } from '$lib/terminology.js';
  import { t as i18n } from '$lib/i18n';
  import { resolveMediaUrl } from '$lib/v2/media.js';

  /**
   * One flat tree, grouped by what the person is doing rather than by which
   * Django app owns the model. Every label matches the route it lands on and
   * the page title it lands on; "Pipeline" goes to /v2/pipeline, which is
   * titled "Pipeline".
   *
   * v1 had /leads listed twice, as "Pipeline" and as "Leads", and a "Deals"
   * entry pointing at /opportunities while /deals 404'd.
   *
   * `role` is server-derived from the JWT (see the app layout loader). It only
   * decides which destinations to *show*. Every hidden one is still enforced
   * by the backend, so this is UX, not access control. An item marked `admin`
   * is one where a member gets nothing but a "for administrators" gate, so
   * showing it would only teach them to bounce off it.
   *
   * `termKey` marks the handful of entity destinations a vertical pack may
   * relabel (see `$lib/terminology.js`). The string in `label` below is only
   * ever the fallback an org with no pack, or no override for that key,
   * still renders; the derived `groups` below is what actually resolves it
   * against `terminology`. No other label branches on the org at all.
   *
   * @type {{
   *   counts?: Record<string, number>,
   *   org?: { name: string, logo_url?: string | null },
   *   role?: string,
   *   terminology?: Record<string, string> | null,
   *   onsearch?: () => void
   * }}
   */
  let {
    counts = {},
    org = { name: 'BOP CRM' },
    role = 'USER',
    terminology = undefined,
    onsearch = () => {}
  } = $props();

  const GROUPS = [
    {
      label: 'Ventas',
      groupKey: 'nav.group_sell',
      items: [
        { href: '/', key: 'nav.today', label: 'Hoy', icon: Sun, exact: true },
        {
          href: '/pipeline',
          key: 'nav.pipeline',
          label: 'Pipeline',
          icon: Columns3,
          count: 'pipeline',
          termKey: 'opportunity.plural'
        },
        { href: '/leads', key: 'nav.leads', label: 'Prospectos', icon: Target, count: 'leads', termKey: 'lead.plural' },
        { href: '/accounts', key: 'nav.accounts', label: 'Empresas', icon: Building2, termKey: 'account.plural' },
        { href: '/contacts', key: 'nav.contacts', label: 'Contactos', icon: Users, termKey: 'contact.plural' },
        { href: '/goals', key: 'nav.goals', label: 'Objetivos', icon: Trophy }
      ]
    },
    {
      label: 'Servicio',
      groupKey: 'nav.group_serve',
      items: [
        { href: '/tasks', key: 'nav.tasks', label: 'Tareas', icon: CircleCheck, count: 'tasks' },
        { href: '/tickets', key: 'nav.tickets', label: 'Tickets', icon: LifeBuoy, count: 'tickets' },
        { href: '/solutions', key: 'nav.knowledge_base', label: 'Base de conocimiento', icon: BookOpen },
        { href: '/documents', key: 'nav.documents', label: 'Documentos', icon: FileText }
      ]
    },
    {
      label: 'Facturación',
      groupKey: 'nav.group_bill',
      items: [
        {
          href: '/invoices',
          key: 'nav.invoices',
          label: 'Facturas',
          icon: Receipt,
          count: 'invoices',
          termKey: 'invoice.plural'
        },
        { href: '/timesheet', key: 'nav.timesheet', label: 'Registro de tiempo', icon: Clock }
      ]
    },
    {
      label: 'Administración',
      groupKey: 'nav.group_run',
      items: [
        { href: '/team', key: 'nav.team_access', label: 'Equipo y accesos', icon: UserCog, admin: true },
        { href: '/settings', key: 'nav.settings', label: 'Configuración', icon: SlidersHorizontal }
      ]
    }
  ];

  // Drop admin-only items for members, resolve any relabelled entity through
  // the terminology map, then drop any group left with nothing.
  let groups = $derived(
    GROUPS.map((group) => ({
      ...group,
      label: group.groupKey ? $i18n(group.groupKey, {}, group.label) : group.label,
      items: group.items
        .filter((item) => role === 'ADMIN' || !item.admin)
        .map((item) => {
          let itemLabel = item.key ? $i18n(item.key, {}, item.label) : item.label;
          if (item.termKey && terminology?.[item.termKey]) {
            itemLabel = tTerm(terminology, item.termKey, itemLabel);
          }
          return { ...item, label: itemLabel };
        })
    })).filter((group) => group.items.length > 0)
  );

  const isActive = (href, exact) =>
    exact ? page.url.pathname === href : page.url.pathname.startsWith(href);
</script>

<nav class="v2-nav" aria-label="Main">
  <div class="v2-org">
    {#if resolveMediaUrl(org.logo_url)}
      <img
        src={resolveMediaUrl(org.logo_url)}
        alt={org.name}
        class="v2-org-logo"
      />
    {:else}
      <span class="v2-mark">{org.name?.slice(0, 1)?.toUpperCase() || '?'}</span>
    {/if}
    <b>{org.name}</b>
  </div>

  <!--
    No entry appears here without a route behind it. v1's "Deals" pointed at
    /opportunities while /deals 404'd; an Inbox link with nothing behind it
    would be the same mistake.
  -->
  {#each groups as group (group.label)}
    <div class="v2-nav-group v2-label">{group.label}</div>
    {#each group.items as item (item.href)}
      <a
        class="v2-link"
        href={resolve(asInternalPath(item.href))}
        aria-current={isActive(item.href, 'exact' in item ? Boolean(item.exact) : false) ? 'page' : undefined}
      >
        <item.icon />
        {item.label}
        {#if 'count' in item && item.count && counts[item.count]}
          <span class="v2-count">{counts[item.count]}</span>
        {/if}
      </a>
    {/each}
  {/each}

  <div class="v2-nav-foot">
    <button class="v2-link v2-nav-search" type="button" onclick={onsearch}>
      <Search />
      {$i18n('nav.search', {}, 'Buscar')}
      <span class="v2-count">⌘K</span>
    </button>
    <!-- Personal, not work: your own feed sits with your own profile rather
         than in Serve, where it would read as a queue the team shares. -->
    <a
      class="v2-link"
      href={resolve('/notifications')}
      aria-current={isActive('/notifications', false) ? 'page' : undefined}
    >
      <Bell />
      {$i18n('nav.notifications', {}, 'Notificaciones')}
      {#if counts.notifications}
        <span class="v2-count">{counts.notifications}</span>
      {/if}
    </a>
    <a class="v2-link" href={resolve('/profile')}>
      <CircleUser />
      {$i18n('nav.your_profile', {}, 'Mi perfil')}
    </a>
    <a class="v2-link" href={resolve('/help')}>
      <CircleHelp />
      {$i18n('nav.help', {}, 'Ayuda')}
    </a>
    <!-- The phone app for people on the hosted service. No pulsing dot. A
         download link is not something that needs you right now, and v2 keeps
         attention for the things that do. -->
    <a
      class="v2-link"
      href="https://play.google.com/store/apps/details?id=io.bottlecrm&hl=en"
      target="_blank"
      rel="noopener noreferrer"
    >
      <Smartphone />
      {$i18n('nav.download_app', {}, 'Descargar app')}
    </a>
    <!-- Leaving the app. Last in the list, and a plain link. /logout is a
         server load that clears the auth cookies and redirects to /login, so a
         GET navigation is all it takes and no data-fetching component follows. -->
    <a class="v2-link" href={resolve('/logout')} data-sveltekit-reload>
      <LogOut />
      {$i18n('nav.sign_out', {}, 'Cerrar sesión')}
    </a>
  </div>
</nav>

<style>
  /* Search opens an overlay rather than navigating, so it is a button. It
     borrows .v2-link for everything else. A control that sits in a list of
     links should not look like the odd one out. */
  .v2-nav-search {
    width: 100%;
    background: none;
    border: 0;
    font-family: inherit;
    font-size: inherit;
    text-align: left;
    cursor: pointer;
  }
  .v2-org-logo {
    width: 24px;
    height: 24px;
    border-radius: 6px;
    object-fit: contain;
    flex: none;
    background: var(--v2-paper);
  }
  :global(.dark) .v2-org-logo {
    background: #ffffff;
  }
</style>
