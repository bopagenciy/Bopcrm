import { describe, it, expect } from 'vitest';
import { resolveMediaUrl } from './media.js';

describe('resolveMediaUrl', () => {
  it('handles null, undefined, and empty string', () => {
    expect(resolveMediaUrl(null)).toBeNull();
    expect(resolveMediaUrl(undefined)).toBeNull();
    expect(resolveMediaUrl('')).toBeNull();
    expect(resolveMediaUrl('   ')).toBeNull();
  });

  it('normalizes relative /media path to public API URL', () => {
    expect(resolveMediaUrl('/media/org_logos/logo.png')).toBe(
      'http://localhost:8000/media/org_logos/logo.png'
    );
  });

  it('normalizes internal Docker backend URL (backend:8000) to public origin', () => {
    expect(
      resolveMediaUrl('http://backend:8000/media/org_logos/logo.png')
    ).toBe(
      'http://localhost:8000/media/org_logos/logo.png'
    );
  });

  it('normalizes internal Docker backend URL without port to public origin', () => {
    expect(
      resolveMediaUrl('http://backend/media/org_logos/logo.png')
    ).toBe(
      'http://localhost:8000/media/org_logos/logo.png'
    );
  });

  it('preserves query strings when rewriting internal backend UPLs', () => {
    expect(
      resolveMediaUrl('http://backend:8000/media/org_logos/logo.png?v=123')
    ).toBe(
      'http://localhost:8000/media/org_logos/logo.png?v=123'
    );
  });

  it('preserves external HTTPS and S3 URLs unchanged', () => {
    const s3Url = 'https://my-bucket.s3.amazonaws.com/org_logos/logo.png';
    expect(resolveMediaUrl(s3Url)).toBe(s3Url);

    const cdnUrl = 'https://cdn.example.com/images/avatar.jpg?token=abc';
    expect(resolveMediaUrl(cdnUrl)).toBe(cdnUrl);
  });

  it('preserves blob: and data: URLs unchanged', () => {
    const blobUrl = 'blob:http://localhost:5173/93802428-c1e1-45be';
    expect(resolveMediaUrl(blobUrl)).toBe(blobUrl);

    const dataUrl = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAffcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRUE5ErkJggg==';
    expect(resolveMediaUrl(dataUrl)).toBe(dataUrl);
  });
});
