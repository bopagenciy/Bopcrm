<script>
  import { resolve } from '$app/paths';
  import { enhance } from '$app/forms';
  import PageHeader from '$lib/v2/components/PageHeader.svelte';
  import Pill from '$lib/v2/components/Pill.svelte';
  import Avatar from '$lib/v2/components/Avatar.svelte';
  import { relativeDays, shortDate, count } from '$lib/v2/format.js';
  import { ROLE_LABEL, ROLE_TONE } from '$lib/v2/enums.js';
  import { KeyRound, Lock, ArrowLeftRight, Globe } from '@lucide/svelte';
  import { t as i18n, locale, setLocale, SUPPORTED_LOCALES } from '$lib/i18n';

  /** @type {{ data: any, form: any }} */
  let { data, form } = $props();

  let p = $derived(data.profile);
  let name = $derived(`${p.user_details.first_name} ${p.user_details.last_name}`.trim());

  let editing = $state(false);
  let editName = $state('');
  let editPhone = $state('');

  function openEdit() {
    editName = name;
    editPhone = p.phone || '';
    editing = true;
  }

  const onEdit = (/** @type {any} */ { formData }) => {
    if ((formData.get('name') ?? '') === name) formData.delete('name');
    if ((formData.get('phone') ?? '') === (p.phone || '')) formData.delete('phone');

    return async (/** @type {any} */ { result, update }) => {
      if (result.type === 'success') {
        editing = false;
        await update();
      } else {
        await update({ reset: false });
      }
    };
  };

  let editError = $derived(form?.scope === 'switch' ? '' : (form?.message ?? ''));
  let switchError = $derived(form?.scope === 'switch' ? (form?.message ?? '') : '');

  function handleLanguageChange(e) {
    setLocale(e.target.value);
  }
</script>

<PageHeader title={name} record>
  {#snippet sub()}
    {ROLE_LABEL[p.role]} · {data.org.name} · {$i18n('profile.joined', {}, 'se unió')} {shortDate(p.joined_at)}
  {/snippet}
  {#snippet actions()}
    {#if !editing}
      <button class="v2-btn v2-btn-primary" onclick={openEdit}>
        {$i18n('profile.edit_details', {}, 'Editar detalles')}
      </button>
    {/if}
  {/snippet}
</PageHeader>

<div class="v2-scroll">
  <div class="v2-pad" style="padding-top:18px;padding-bottom:32px">
    <div class="v2-split">
      <div>
        <div class="v2-label" style="margin-bottom:10px">{$i18n('profile.you', {}, 'TÚ')}</div>

        {#if editing}
          <form
            class="v2-card"
            method="POST"
            action="?/edit"
            use:enhance={onEdit}
            style="padding:17px 18px;margin-bottom:20px"
          >
            <div class="v2-field">
              <label for="f-name">{$i18n('common.full_name', {}, 'Nombre completo')}</label>
              <input
                id="f-name"
                name="name"
                class="v2-input"
                bind:value={editName}
                maxlength="255"
              />
            </div>
            <div class="v2-field" style="margin-top:12px">
              <label for="f-phone">{$i18n('profile.phone', {}, 'Teléfono')}</label>
              <input
                id="f-phone"
                name="phone"
                class="v2-input"
                bind:value={editPhone}
                placeholder="+44 20 7946 0100"
              />
              <p class="v2-hint">Solo dígitos y separadores. Déjalo en blanco para eliminarlo.</p>
            </div>
            {#if editError}
              <p class="v2-error" style="margin-top:10px">{editError}</p>
            {/if}
            <div style="display:flex;gap:8px;margin-top:16px">
              <button class="v2-btn v2-btn-primary" type="submit">{$i18n('common.save', {}, 'Guardar')}</button>
              <button class="v2-btn" type="button" onclick={() => (editing = false)}>{$i18n('common.cancel', {}, 'Cancelar')}</button>
            </div>
          </form>
        {:else}
          <div class="v2-card" style="padding:17px 18px;margin-bottom:20px">
            <div style="display:flex;gap:13px;align-items:center;margin-bottom:16px">
              <Avatar {name} size={46} />
              <div style="min-width:0">
                <div style="font-weight:640;font-size:15px">{name}</div>
                <div class="v2-sub" style="font-size:12.5px">{p.user_details.email}</div>
              </div>
            </div>
            <dl class="v2-kv">
              <dt>{$i18n('profile.phone', {}, 'Teléfono')}</dt>
              <dd class="v2-num" style="font-size:12px">{p.phone || '—'}</dd>
              <dt>{$i18n('profile.teams', {}, 'Equipos')}</dt>
              <dd>{p.teams.join(', ') || '—'}</dd>
              <dt>{$i18n('profile.joined', {}, 'Se unió')}</dt>
              <dd>{shortDate(p.joined_at)}</dd>
              <dt>{$i18n('profile.last_signed_in', {}, 'Último inicio de sesión')}</dt>
              <dd>{relativeDays(p.last_login)}</dd>
            </dl>
          </div>
        {/if}

        <div class="v2-label" style="margin-bottom:10px">{$i18n('profile.preferences', {}, 'PREFERENCIAS')}</div>
        <div class="v2-card" style="padding:17px 18px;margin-bottom:20px">
          <div style="display:flex;align-items:center;justify-content:space-between;gap:16px">
            <div style="display:flex;align-items:center;gap:10px">
              <Globe size={18} style="color:var(--v2-slate)" />
              <div>
                <b style="font-size:13.5px;display:block">{$i18n('profile.interface_language', {}, 'Idioma de la interfaz')}</b>
                <span class="v2-sub" style="font-size:11.5px">Selecciona tu idioma de preferencia</span>
              </div>
            </div>
            <select class="v2-input" style="width:auto;min-width:140px;padding:6px 10px" value={$locale} onchange={handleLanguageChange}>
              {#each SUPPORTED_LOCALES as loc}
                <option value={loc.code}>{loc.label}</option>
              {/each}
            </select>
          </div>
        </div>

        <div class="v2-label" style="margin-bottom:10px">{$i18n('profile.organisations', {}, 'ORGANIZACIONES')}</div>
        <div class="v2-card" style="overflow:hidden">
          {#each p.orgs as o (o.id)}
            <div class="v2-setting">
              <div class="v2-setting-body">
                <b>{o.name}</b>
                <span class="v2-sub" style="font-size:11.5px">
                  {ROLE_LABEL[o.role] === 'Admin' ? 'Administrador aquí' : 'Miembro aquí'}
                </span>
              </div>
              {#if o.is_current}
                <Pill tone="ink" dot>{$i18n('profile.current', {}, 'Actual')}</Pill>
              {:else}
                <form method="POST" action="?/switchOrg" use:enhance class="v2-inline-form">
                  <input type="hidden" name="org_id" value={o.id} />
                  <button class="v2-btn v2-btn-sm" type="submit">
                    <ArrowLeftRight size={12} />Cambiar
                  </button>
                </form>
              {/if}
            </div>
          {/each}
        </div>
        {#if switchError}
          <p class="v2-error" style="margin-top:9px">{switchError}</p>
        {/if}
        <p class="v2-sub" style="font-size:11.5px;margin-top:11px">
          Al cambiar de organización se inicia sesión nuevamente con un nuevo token. La organización activa determina los registros visibles.
        </p>
      </div>

      <div>
        <div class="v2-label" style="margin-bottom:10px">{$i18n('profile.access', {}, 'ACCESO')}</div>
        <div class="v2-card" style="overflow:hidden;margin-bottom:20px">
          <div class="v2-setting">
            <div class="v2-setting-body">
              <b>{$i18n('profile.role', {}, 'Rol')}</b>
              <span class="v2-sub" style="font-size:11.5px">
                Asignado por un administrador. No puedes cambiar tu propio rol.
              </span>
            </div>
            <Lock size={14} style="color:var(--v2-slate);flex:none" />
            <Pill tone={ROLE_TONE[p.role]}>{ROLE_LABEL[p.role]}</Pill>
          </div>
          <a class="v2-setting" href={resolve('/profile/tokens')}>
            <div class="v2-setting-body">
              <b>{$i18n('profile.api_tokens', {}, 'Tokens de API')}</b>
              <span class="v2-sub" style="font-size:11.5px">
                Cada token permite iniciar sesión con tu cuenta y tu rol.
              </span>
            </div>
            <KeyRound size={14} style="color:var(--v2-slate);flex:none" />
            <span class="v2-num" style="font-size:13px;font-weight:600">
              {count(p.active_token_count)}
            </span>
          </a>
          <div class="v2-setting">
            <div class="v2-setting-body">
              <b>{$i18n('profile.sign_in_method', {}, 'Método de inicio de sesión')}</b>
              <span class="v2-sub" style="font-size:11.5px">
                {p.user_details.email}, mediante Google o código enviado por correo. No hay contraseña que cambiar.
              </span>
            </div>
          </div>
        </div>

        <div class="v2-label" style="margin-bottom:10px">{$i18n('profile.work_shows_up', {}, 'DONDE APARECE TU TRABAJO')}</div>
        <div class="v2-card" style="overflow:hidden">
          <a class="v2-setting" href={resolve('/goals')}>
            <div class="v2-setting-body">
              <b>{$i18n('profile.goals', {}, 'Objetivos')}</b>
              <span class="v2-sub" style="font-size:11.5px">Tu cuota y progreso actual</span>
            </div>
          </a>
          <a class="v2-setting" href={resolve('/timesheet')}>
            <div class="v2-setting-body">
              <b>{$i18n('profile.timesheet', {}, 'Registro de tiempo')}</b>
              <span class="v2-sub" style="font-size:11.5px">Horas registradas esta semana</span>
            </div>
          </a>
          <a class="v2-setting" href={resolve('/tasks')}>
            <div class="v2-setting-body">
              <b>{$i18n('profile.tasks', {}, 'Tareas')}</b>
              <span class="v2-sub" style="font-size:11.5px">Lo que tienes asignado</span>
            </div>
          </a>
        </div>
      </div>
    </div>
  </div>
</div>

<style>
  /* The Switch button sits in a form so it can POST; keep it laid out exactly
     as the bare button was (the row uses flex; the form must not add a box). */
  .v2-inline-form {
    display: contents;
  }
</style>
