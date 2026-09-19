import { describe, it, expect } from 'vitest';

describe('Lead Title Fallback Logic', () => {
  function getDisplayTitle(lead, fallback = 'Lead') {
    const contactName = `${lead?.first_name ?? ''} ${lead?.last_name ?? ''}`.trim();
    return contactName || (lead?.company_name ?? '').trim() || fallback;
  }

  it('uses full contact name when first and last name are present', () => {
    expect(getDisplayTitle({ first_name: 'John', last_name: 'Doe', company_name: 'Acme Corp' })).toBe('John Doe');
  });

  it('uses first name when only first name is present', () => {
    expect(getDisplayTitle({ first_name: 'Alice', last_name: '', company_name: 'Acme Corp' })).toBe('Alice');
  });

  it('falls back to company_name when contact name is completely empty or whitespace', () => {
    expect(getDisplayTitle({ first_name: '', last_name: '   ', company_name: 'BOP E2E Synthetic Industrial Supply 001' })).toBe(
      'BOP E2E Synthetic Industrial Supply 001'
    );
  });

  it('falls back to "Lead" when contact names and company name are all absent', () => {
    expect(getDisplayTitle({ first_name: null, last_name: null, company_name: '' })).toBe('Lead');
    expect(getDisplayTitle({})).toBe('Lead');
  });

  it('supports localized fallback title', () => {
    expect(getDisplayTitle({}, 'Prospecto')).toBe('Prospecto');
  });
});

describe('Lead Score Validation', () => {
  function validateLeadScore(raw) {
    if (typeof raw === 'number' && Number.isFinite(raw)) {
      if (raw >= 0 && raw <= 100) return raw;
    } else if (typeof raw === 'string' && raw.trim() !== '') {
      const parsed = Number(raw);
      if (Number.isFinite(parsed) && parsed >= 0 && parsed <= 100) return parsed;
    }
    return null;
  }

  it('accepts valid scores within [0, 100]', () => {
    expect(validateLeadScore(50)).toBe(50);
    expect(validateLeadScore(0)).toBe(0);
    expect(validateLeadScore(100)).toBe(100);
    expect(validateLeadScore('75')).toBe(75);
    expect(validateLeadScore('0')).toBe(0);
  });

  it('rejects invalid, negative, out-of-range, and malformed scores', () => {
    expect(validateLeadScore(-1)).toBeNull();
    expect(validateLeadScore(101)).toBeNull();
    expect(validateLeadScore(null)).toBeNull();
    expect(validateLeadScore(undefined)).toBeNull();
    expect(validateLeadScore('invalid')).toBeNull();
    expect(validateLeadScore(NaN)).toBeNull();
    expect(validateLeadScore(Infinity)).toBeNull();
  });
});

describe('Safe Prospect URL Validation', () => {
  function validateProspectUrl(raw) {
    if (!raw || typeof raw !== 'string') return null;
    try {
      const parsed = new URL(raw);
      if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
        return raw;
      }
    } catch {
      // invalid URL
    }
    return null;
  }

  it('accepts valid http and https URLs', () => {
    expect(validateProspectUrl('http://127.0.0.1:3000/prospects/123')).toBe('http://127.0.0.1:3000/prospects/123');
    expect(validateProspectUrl('https://app.bopclients.com/prospects/xyz')).toBe('https://app.bopclients.com/prospects/xyz');
  });

  it('rejects unsafe schemes, relative paths, and malformed URLs', () => {
    expect(validateProspectUrl('javascript:alert(1)')).toBeNull();
    expect(validateProspectUrl('data:text/html,<script>')).toBeNull();
    expect(validateProspectUrl('file:///etc/passwd')).toBeNull();
    expect(validateProspectUrl('/relative/path')).toBeNull();
    expect(validateProspectUrl('not-a-url')).toBeNull();
    expect(validateProspectUrl(null)).toBeNull();
  });
});

describe('Priority Tone Mapping', () => {
  function priorityTone(priority) {
    if (!priority) return 'slate';
    const p = priority.toLowerCase();
    if (p === 'urgent') return 'rust';
    if (p === 'high') return 'clay';
    if (p === 'medium') return 'ink';
    if (p === 'low') return 'moss';
    return 'slate';
  }

  it('maps known priority levels to supported design system tones', () => {
    expect(priorityTone('URGENT')).toBe('rust');
    expect(priorityTone('urgent')).toBe('rust');
    expect(priorityTone('HIGH')).toBe('clay');
    expect(priorityTone('Medium')).toBe('ink');
    expect(priorityTone('LOW')).toBe('moss');
    expect(priorityTone('unknown')).toBe('slate');
    expect(priorityTone(null)).toBe('slate');
  });
});
