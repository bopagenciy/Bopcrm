import { writable, derived } from 'svelte/store';
import es from './locales/es.json';
import en from './locales/en.json';

const dictionaries = { es, en };

export const DEFAULT_LOCALE = 'es';

export const SUPPORTED_LOCALES = [
  { code: 'es', label: 'Español' },
  { code: 'en', label: 'English' }
];

function getInitialLocale() {
  if (typeof window !== 'undefined') {
    const saved = localStorage.getItem('bottlecrm_locale');
    if (saved && dictionaries[saved]) {
      return saved;
    }
  }
  return DEFAULT_LOCALE;
}

/**
 * Current locale store (default: 'es' or persisted)
 */
export const locale = writable(getInitialLocale());

/**
 * Helper to resolve nested key strings like "nav.pipeline" from a dictionary object
 * @param {object} dict
 * @param {string} keyPath
 * @returns {string|null}
 */
function getNestedValue(dict, keyPath) {
  if (!dict || !keyPath) return null;
  const parts = keyPath.split('.');
  let current = dict;
  for (const part of parts) {
    if (current && typeof current === 'object' && part in current) {
      current = current[part];
    } else {
      return null;
    }
  }
  return typeof current === 'string' ? current : null;
}

/**
 * Translate function that resolves a key against current locale dictionary,
 * falls back to English, interpolates {var} params, and supports fallback string.
 *
 * @param {string} currentLang - Active locale code (e.g. 'es', 'en')
 * @param {string} key - Dictionary key (e.g. 'nav.pipeline')
 * @param {Record<string, any>} [params] - Optional interpolation params
 * @param {string} [fallback] - Optional explicit fallback
 * @returns {string}
 */
export function translate(currentLang, key, params = {}, fallback = '') {
  const primaryDict = dictionaries[currentLang] || dictionaries[DEFAULT_LOCALE];
  const fallbackDict = dictionaries.en;

  let message = getNestedValue(primaryDict, key) || getNestedValue(fallbackDict, key) || fallback || key;

  if (params && typeof params === 'object') {
    Object.keys(params).forEach((paramKey) => {
      message = message.replace(new RegExp(`\\{${paramKey}\\}`, 'g'), String(params[paramKey]));
    });
  }

  return message;
}

/**
 * Reactive $t store for use in Svelte components: {$t('nav.pipeline')}
 */
export const t = derived(locale, ($locale) => (key, params = {}, fallback = '') => {
  return translate($locale, key, params, fallback);
});

/**
 * Change current locale and persist choice to localStorage and cookie
 * @param {string} newLocale
 */
export function setLocale(newLocale) {
  if (dictionaries[newLocale]) {
    locale.set(newLocale);
    if (typeof window !== 'undefined') {
      try {
        localStorage.setItem('bottlecrm_locale', newLocale);
        document.cookie = `bottlecrm_locale=${newLocale}; path=/; max-age=31536000; SameSite=Lax`;
      } catch (e) {
        // Silently handle quota / cookie security blocks if any
      }
    }
  }
}
