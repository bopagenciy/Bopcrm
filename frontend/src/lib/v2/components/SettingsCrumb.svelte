<script>
  import { resolve } from '$app/paths';
  import { ChevronLeft } from '@lucide/svelte';
  import { t as i18n } from '$lib/i18n';
</script>

<a href={resolve('/settings')}><ChevronLeft size={13} />{$i18n('settings.title', {}, 'Configuración')}</a>

<style>
  a {
    display: inline-flex;
    align-items: center;
    gap: 2px;
    color: inherit;
    text-decoration: none;
  }
  a:hover {
    color: var(--v2-ink);
    text-decoration: underline;
  }
</style>
