import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { api } from '../api';
import { ContactInfoPane } from '../components/ContactInfoPane';
import type { Contact, ContactDetail } from '../types';

vi.mock('../api', () => ({
  api: {
    getContactDetail: vi.fn(),
  },
}));

const baseContact: Contact = {
  public_key: 'aa'.repeat(32),
  name: 'Repeater Alpha',
  type: 2,
  flags: 0,
  last_path: null,
  last_path_len: 2,
  last_advert: 1700000000,
  lat: null,
  lon: null,
  last_seen: 1700000000,
  on_radio: false,
  last_contacted: null,
  last_read_at: null,
  first_seen: 1699990000,
};

describe('ContactInfoPane', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders advert paths using hop-aware grouping', async () => {
    const detail: ContactDetail = {
      contact: baseContact,
      name_history: [],
      dm_message_count: 0,
      channel_message_count: 0,
      most_active_rooms: [],
      advert_paths: [
        {
          path: '20273031',
          path_len: 2,
          next_hop: '2027',
          first_seen: 1700000000,
          last_seen: 1700000100,
          heard_count: 3,
        },
      ],
      advert_frequency: null,
      nearest_repeaters: [],
    };

    vi.mocked(api.getContactDetail).mockResolvedValue(detail);

    render(
      <ContactInfoPane
        contactKey={baseContact.public_key}
        onClose={vi.fn()}
        contacts={[baseContact]}
        config={null}
        favorites={[]}
        onToggleFavorite={vi.fn()}
      />
    );

    expect(await screen.findByText('2027 → 3031')).toBeInTheDocument();
  });
});
