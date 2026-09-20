import { describe, it, expect, vi, beforeEach } from 'vitest';

const apiRequest = vi.fn();
vi.mock('$lib/api-helpers.js', () => ({ apiRequest: (...a) => apiRequest(...a) }));
vi.mock('$lib/server/v2/files.js', () => ({ attachmentHref: () => '' }));

const { createLead, convertLead, getLead } = await import('$lib/server/v2/leads.js');
// Cast rather than shaping a full Cookies mock: createLead only ever calls
// `cookies.get`, and `apiRequest` itself is mocked above, so nothing here
// touches `getAll`/`set`/`delete`/`serialize`. Without the cast svelte-check
// flags this object against SvelteKit's full `Cookies` type on every call site
// below, which is noise for a shape the test deliberately keeps minimal.
const event = /** @type {any} */ ({ cookies: { get: () => 'token' } });

describe('createLead', () => {
  beforeEach(() => {
    apiRequest.mockReset();
  });

  it('POSTs to /leads/ and returns the created lead', async () => {
    apiRequest.mockResolvedValue({ id: 'abc', first_name: 'Ada' });
    const result = await createLead(event, { first_name: 'Ada', last_name: 'Lovelace' });

    expect(apiRequest).toHaveBeenCalledOnce();
    const [endpoint, options] = apiRequest.mock.calls[0];
    expect(endpoint).toBe('/leads/');
    expect(options.method).toBe('POST');
    expect(options.body.first_name).toBe('Ada');
    expect(result.id).toBe('abc');
  });

  it('sends an empty field as null rather than an empty string', async () => {
    apiRequest.mockResolvedValue({ id: 'abc' });
    await createLead(event, { first_name: 'Ada', job_title: '' });
    expect(apiRequest.mock.calls[0][1].body.job_title).toBeNull();
  });

  it('coerces opportunity_amount to a number', async () => {
    apiRequest.mockResolvedValue({ id: 'abc' });
    await createLead(event, { first_name: 'Ada', opportunity_amount: '4200.50' });
    expect(apiRequest.mock.calls[0][1].body.opportunity_amount).toBe(4200.5);
  });

  it('wraps a single owner id in a list, matching the API contract', async () => {
    apiRequest.mockResolvedValue({ id: 'abc' });
    await createLead(event, { first_name: 'Ada', assigned_to: 'profile-1' });
    expect(apiRequest.mock.calls[0][1].body.assigned_to).toEqual(['profile-1']);
  });

  it('never forwards a client-supplied org, which the backend derives from the JWT', async () => {
    apiRequest.mockResolvedValue({ id: 'abc' });
    await createLead(event, { first_name: 'Ada', org: 'attacker-org', created_by: 'someone' });
    const body = apiRequest.mock.calls[0][1].body;
    expect(body.org).toBeUndefined();
    expect(body.created_by).toBeUndefined();
  });
});

describe('convertLead', () => {
  beforeEach(() => {
    apiRequest.mockReset();
  });

  it('PATCHes the lead detail URL with status: converted, and nothing else', async () => {
    apiRequest.mockResolvedValue({
      error: false,
      account_id: 'acc-1',
      contact_id: 'con-1',
      opportunity_id: 'opp-1'
    });
    const result = await convertLead(event, 'lead-1');

    expect(apiRequest).toHaveBeenCalledOnce();
    const [endpoint, options] = apiRequest.mock.calls[0];
    expect(endpoint).toBe('/leads/lead-1/');
    expect(options.method).toBe('PATCH');
    expect(options.body).toEqual({ status: 'converted' });
    expect(result.account_id).toBe('acc-1');
  });

  it('refuses to call the API without a lead id', async () => {
    await expect(convertLead(event, '')).rejects.toThrow(/id is required/);
    expect(apiRequest).not.toHaveBeenCalled();
  });

  it('lets a rejected conversion (e.g. the email guard) propagate to the caller', async () => {
    const rejection = Object.assign(new Error('{"error":true,"errors":{"email":["required"]}}'), {
      status: 400
    });
    apiRequest.mockRejectedValue(rejection);
    await expect(convertLead(event, 'lead-1')).rejects.toBe(rejection);
  });
});

describe('getLead provenance', () => {
  beforeEach(() => {
    apiRequest.mockReset();
  });

  it('extracts and normalizes Bop Clients metadata when present', async () => {
    apiRequest.mockImplementation(async (endpoint) => {
      if (endpoint === '/leads/lead-bop/') {
        return {
          lead_obj: {
            id: 'lead-bop',
            first_name: '',
            last_name: '',
            company_name: 'Bop Test Co',
            source: 'manual',
            source_app: 'bopclients',
            custom_fields: {
              bop_clients: {
                prospect_id: '5d5cd7c6-df3d-400f-a94c-e6898d45aef9',
                lead_score: 50,
                priority: 'MEDIUM',
                source: 'manual',
                prospect_url: 'http://127.0.0.1:3000/prospects/5d5cd7c6-df3d-400f-a94c-e6898d45aef9'
              }
            }
          },
          comments: [],
          attachments: []
        };
      }
      if (endpoint.startsWith('/custom-fields/')) {
        return { results: [] };
      }
      return { open_leads: { open_leads: [] } };
    });

    const result = await getLead(event, 'lead-bop');
    expect(result.bopClients).toBeDefined();
    expect(result.bopClients).toEqual({
      isBopClients: true,
      origin: 'Bop Clients',
      prospectId: '5d5cd7c6-df3d-400f-a94c-e6898d45aef9',
      leadScore: 50,
      priority: 'MEDIUM',
      prospectSource: 'manual',
      prospectUrl: 'http://127.0.0.1:3000/prospects/5d5cd7c6-df3d-400f-a94c-e6898d45aef9'
    });
    // Verify lead object preserves original company_name and source
    expect(result.lead.company_name).toBe('Bop Test Co');
    expect(result.lead.source).toBe('manual');
  });

  it('returns bopClients: null for native CRM leads', async () => {
    apiRequest.mockImplementation(async (endpoint) => {
      if (endpoint === '/leads/lead-native/') {
        return {
          lead_obj: {
            id: 'lead-native',
            first_name: 'Regular',
            last_name: 'Lead',
            source_app: null,
            custom_fields: null
          },
          comments: [],
          attachments: []
        };
      }
      if (endpoint.startsWith('/custom-fields/')) {
        return { results: [] };
      }
      return { open_leads: { open_leads: [] } };
    });

    const result = await getLead(event, 'lead-native');
    expect(result.bopClients).toBeNull();
  });

  it('rejects unverified custom_fields.bop_clients when source_app is not bopclients', async () => {
    apiRequest.mockImplementation(async (endpoint) => {
      if (endpoint === '/leads/lead-unverified/') {
        return {
          lead_obj: {
            id: 'lead-unverified',
            first_name: 'Fake',
            last_name: 'Lead',
            source_app: null,
            custom_fields: {
              bop_clients: {
                prospect_id: 'injected-prospect-id',
                lead_score: 99
              }
            }
          },
          comments: [],
          attachments: []
        };
      }
      if (endpoint.startsWith('/custom-fields/')) {
        return { results: [] };
      }
      return { open_leads: { open_leads: [] } };
    });

    const result = await getLead(event, 'lead-unverified');
    expect(result.bopClients).toBeNull();
  });

  it('normalizes verified related account with valid UUID', async () => {
    apiRequest.mockImplementation(async (endpoint) => {
      if (endpoint === '/leads/lead-with-account/') {
        return {
          lead_obj: {
            id: 'lead-with-account',
            first_name: 'Contact',
            last_name: 'Person',
            company_name: 'Acme Corp',
            account: {
              id: '4eccb255-5745-4f59-ae8a-b2edf5466290',
              name: 'Acme Corp'
            }
          },
          comments: [],
          attachments: []
        };
      }
      if (endpoint.startsWith('/custom-fields/')) {
        return { results: [] };
      }
      return { open_leads: { open_leads: [] } };
    });

    const result = await getLead(event, 'lead-with-account');
    expect(result.lead.account).toEqual({
      id: '4eccb255-5745-4f59-ae8a-b2edf5466290',
      name: 'Acme Corp'
    });
  });

  it('normalizes account to null when account is absent or invalid', async () => {
    apiRequest.mockImplementation(async (endpoint) => {
      if (endpoint === '/leads/lead-no-account/') {
        return {
          lead_obj: {
            id: 'lead-no-account',
            first_name: 'Contact',
            last_name: 'Person',
            account: null
          },
          comments: [],
          attachments: []
        };
      }
      if (endpoint === '/leads/lead-bad-account/') {
        return {
          lead_obj: {
            id: 'lead-bad-account',
            first_name: 'Contact',
            last_name: 'Person',
            account: {
              id: 'not-a-valid-uuid',
              name: 'Fake'
            }
          },
          comments: [],
          attachments: []
        };
      }
      if (endpoint.startsWith('/custom-fields/')) {
        return { results: [] };
      }
      return { open_leads: { open_leads: [] } };
    });

    const res1 = await getLead(event, 'lead-no-account');
    expect(res1.lead.account).toBeNull();

    const res2 = await getLead(event, 'lead-bad-account');
    expect(res2.lead.account).toBeNull();
  });
});
