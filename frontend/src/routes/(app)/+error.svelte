<script>
  import { resolve } from '$app/paths';
  import { page } from '$app/state';
  import EmptyState from '$lib/v2/components/EmptyState.svelte';
  import { FileQuestion, Lock, TriangleAlert } from '@lucide/svelte';
  import { t as i18n } from '$lib/i18n';

  let status = $derived(page.status);

  let shape = $derived(
    status === 404
      ? {
          icon: FileQuestion,
          title: 'Ese registro no existe aquí',
          body:
            page.error?.message ||
            'Es posible que haya sido eliminado o pertenezca a un equipo del que no formas parte.'
        }
      : status === 403
        ? {
            icon: Lock,
            title: 'No tienes acceso a esto',
            body: 'Pide a un administrador de tu organización que te dé acceso, o vuelve a Hoy.'
          }
        : {
            icon: TriangleAlert,
            title: $i18n('error.title', {}, 'No se pudo cargar'),
            body:
              page.error?.message ||
              'El servidor no respondió. Nada de lo que hiciste causó esto y ningún dato se perdió.'
          }
  );
</script>

<div class="v2-scroll">
  <EmptyState title={shape.title} body={shape.body}>
    {#snippet icon()}
      <shape.icon size={21} />
    {/snippet}
    {#snippet actions()}
      {#if status >= 500}
        <button class="v2-btn v2-btn-primary" onclick={() => location.reload()}>
          {$i18n('error.try_again', {}, 'Intentar de nuevo')}
        </button>
      {/if}
      <a class="v2-btn" href={resolve('/')}>{$i18n('error.back_to_today', {}, 'Volver a Hoy')}</a>
    {/snippet}
  </EmptyState>

  <p class="v2-sub" style="text-align:center;font-size:11.5px">
    <span class="v2-num">{status}</span>
    · {page.url.pathname}
  </p>
</div>
