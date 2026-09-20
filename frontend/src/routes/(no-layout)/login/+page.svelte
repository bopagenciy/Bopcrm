<script>
  import { resolve } from '$app/paths';
  import '../../../app.css';
  import '$lib/v2/styles/v2.css';
  import { enhance } from '$app/forms';
  import { t } from '$lib/i18n';

  import imgGoogle from '$lib/assets/images/google.svg';
  import imgLogo from '$lib/assets/images/logo.png';
  import { Mail, Check } from '@lucide/svelte';

  let { data = {} } = $props();

  let isLoading = $state(false);
  let email = $state('');
  let magicLinkSent = $state(false);
  let isSendingLink = $state(false);
  let magicLinkError = $state('');

  function handleGoogleLogin() {
    isLoading = true;
  }

  function handleMagicLink() {
    isSendingLink = true;
    magicLinkError = '';
    return async ({ result }) => {
      isSendingLink = false;
      if (result?.type === 'success') {
        magicLinkSent = true;
      } else if (result?.type === 'failure') {
        magicLinkError = result.data?.error || $t('common.error_occurred');
      } else if (!result) {
        magicLinkError = $t('common.error_occurred');
      }
    };
  }
</script>

<svelte:head>
  <title>{$t('auth.sign_in')} · BOP CRM</title>
  <meta
    name="description"
    content="Sign in to BOP CRM to manage your contacts, deals, and grow your business."
  />
</svelte:head>

<div class="v2-root v2-auth">
  <div class="v2-auth-box">
    <a href={resolve('/')} class="v2-auth-brand">
      <img src={imgLogo} alt="BOP CRM" />
    </a>

    <div class="v2-auth-card">
      <div class="v2-auth-head">
        <h1>{$t('auth.sign_in')}</h1>
        <p>{$t('auth.welcome_back')}</p>
      </div>

      <!-- Primary path. Google's mark keeps a white tile so it stays legible on
           Ember; the whole button is the one Ember action on this screen. -->
      <a
        href={data['google_url']}
        rel="external"
        onclick={handleGoogleLogin}
        class="v2-btn v2-btn-primary v2-btn-block"
        style:pointer-events={isLoading ? 'none' : null}
        style:opacity={isLoading ? '0.85' : null}
      >
        {#if isLoading}
          <span class="v2-spin"></span>
          <span>{$t('auth.redirecting')}</span>
        {:else}
          <img src={imgGoogle} alt="" class="v2-auth-gicon" />
          <span>{$t('auth.continue_google')}</span>
        {/if}
      </a>

      <div class="v2-auth-divider">o</div>

      {#if magicLinkSent}
        <div class="v2-auth-note v2-auth-note-ok">
          <Check />
          <div>
            <b>{$t('auth.check_email')}</b>
            <div style="font-weight:400;margin-top:2px">
              {$t('auth.link_sent')}
            </div>
          </div>
        </div>
      {:else}
        <form
          method="POST"
          use:enhance={handleMagicLink}
          style="display:flex;flex-direction:column;gap:9px"
        >
          <label for="email" class="v2-sr-only">Correo electrónico</label>
          <input
            id="email"
            type="email"
            name="email"
            class="v2-input"
            placeholder={$t('auth.email_placeholder')}
            required
            bind:value={email}
            disabled={isSendingLink}
          />
          <button type="submit" class="v2-btn v2-btn-block" disabled={isSendingLink}>
            {#if isSendingLink}
              <span class="v2-spin"></span>
              <span>{$t('auth.sending')}</span>
            {:else}
              <Mail size={15} />
              <span>{$t('auth.continue_email')}</span>
            {/if}
          </button>
        </form>
        {#if magicLinkError}
          <div class="v2-auth-note v2-auth-note-bad" style="margin-top:11px">
            <span>{magicLinkError}</span>
          </div>
        {/if}
      {/if}
    </div>

    <p class="v2-sub" style="text-align:center;margin:14px 0 0">
      {$t('auth.new_here')}
    </p>

    <div class="v2-auth-foot">
      <a href="https://bottlecrm.io/privacy-policy">{$t('auth.privacy')}</a>
      <span class="v2-auth-dot"></span>
      <a href="https://bottlecrm.io/terms">{$t('auth.terms')}</a>
      <span class="v2-auth-dot"></span>
      <a href="https://github.com/django-crm/Django-CRM" target="_blank" rel="noopener">GitHub</a>
    </div>
  </div>
</div>
