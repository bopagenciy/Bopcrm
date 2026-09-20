<script>
  import { resolve } from '$app/paths';
  import '../../../app.css';
  import '$lib/v2/styles/v2.css';
  import imgLogo from '$lib/assets/images/logo.png';
  import { Building2, LogOut, Plus, ChevronRight } from '@lucide/svelte';
  import { enhance } from '$app/forms';
  import { t } from '$lib/i18n';

  let { data = { orgs: [] } } = $props();
  let orgs = $derived(data?.orgs ?? []);

  let loading = $state(false);
  let selectedOrgId = $state(null);
</script>

<svelte:head>
  <title>{$t('org.title')} · BOP CRM</title>
</svelte:head>

<div class="v2-root v2-auth">
  <div class="v2-auth-box">
    <a href={resolve('/')} class="v2-auth-brand">
      <img src={imgLogo} alt="BOP CRM" />
    </a>

    <div class="v2-auth-card">
      <div class="v2-auth-head">
        <h1>{$t('org.title')}</h1>
        <p>
          {orgs.length
            ? $t('org.subtitle')
            : $t('org.no_orgs_desc')}
        </p>
      </div>

      {#if orgs.length > 0}
        {#each orgs as org (org.id)}
          <form
            method="POST"
            action="?/selectOrg"
            use:enhance={() => {
              loading = true;
              selectedOrgId = org.id;
              return async ({ update }) => {
                await update();
                loading = false;
                selectedOrgId = null;
              };
            }}
          >
            <input type="hidden" name="org_id" value={org.id} />
            <input type="hidden" name="org_name" value={org.name} />
            <button type="submit" class="v2-auth-org" disabled={loading}>
              <span class="v2-mark" style="width:30px;height:30px;border-radius:8px;font-size:13px">
                {org.name?.slice(0, 1)?.toUpperCase() || '?'}
              </span>
              <span class="v2-auth-org-body">
                <b>{org.name}</b>
                <span class="v2-sub" style="display:block;text-transform:capitalize">
                  {org.role?.toLowerCase() || 'miembro'}
                </span>
              </span>
              {#if loading && selectedOrgId === org.id}
                <span class="v2-spin"></span>
              {:else}
                <ChevronRight />
              {/if}
            </button>
          </form>
        {/each}

        <a href={resolve('/org/new')} class="v2-auth-add">
          <Plus />
          {$t('org.create')}
        </a>
      {:else}
        <div class="v2-state" style="padding:22px 0 8px">
          <div class="v2-state-icon"><Building2 size={22} /></div>
          <h3>{$t('org.no_orgs')}</h3>
          <p>{$t('org.no_orgs_desc')}</p>
          <a href={resolve('/org/new')} class="v2-btn v2-btn-primary">
            <Plus size={15} />
            {$t('org.create')}
          </a>
        </div>
      {/if}
    </div>

    <div class="v2-auth-foot">
      <a href={resolve('/logout')} style="display:inline-flex;align-items:center;gap:5px">
        <LogOut size={13} /> {$t('nav.sign_out')}
      </a>
    </div>
  </div>
</div>
