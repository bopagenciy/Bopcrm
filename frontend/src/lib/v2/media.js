import { env } from '$env/dynamic/public';

/**
 * Normalizes a media URL so that it is safe to render in client browsers.
 *
 * It guarantees that:
 * 1. Docker-internal hostnames (e.g. `http://backend:8000`) are rewritten to use
 *    the browser-accessible `PUBLIC_DJANGO_API_URL`.
 * 2. Root-relative media paths (e.g. `/media/org_logos/...`) are prefixed with
 *    `PUBLIC_DJANGO_API_URL`.
 * 3. `blob:`, `data:`, and external URLs (e.g. `https://s3...`, `https://...`) are left intact.
 * 4. Falsy/empty values safely return `null`.
 *
 * @param {string | null | undefined} url
 * @returns{string | null}
 */
export function resolveMediaUrl(url) {
  if (!url || typeof url !== 'string') {
    return null;
  }

  const trimmed = url.trim();
  if (!trimmed) {
    return null;
  }

  // Preserve client-side previews and inline data
  if (trimmed.startsWith('blob:') || trimmed.startsWith('data:')) {
    return trimmed;
  }

  const publicOrigin = (env?.PUBLIC_DJANGO_API_URL || 'http://localhost:8000').replace(/\/+$/, '');

  // Relative path (e.g. /media/org_logos/...)
  if (trimmed.startsWith('/')) {
    return `${publicOrigin}${trimmed}`;
  }

  // Check absolute URLs
  try {
    const parsed = new URL(trimmed);
    if (parsed.hostname === 'backend') {
      return `${publicOrigin}${parsed.pathname}${parsed.search}`;
    }
    return trimmed;
  } catch {
    // If not avalid URL or relative path, return trimmed as fallback
    return trimmed;
  }
}
