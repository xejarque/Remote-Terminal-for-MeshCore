import { describe, it, expect } from 'vitest';
import {
  parsePathHops,
  findContactsByPrefix,
  calculateDistance,
  resolvePath,
  formatDistance,
  formatHopCounts,
} from '../utils/pathUtils';
import type { Contact, RadioConfig } from '../types';
import { CONTACT_TYPE_REPEATER } from '../types';

// Helper to create mock contacts
function createContact(overrides: Partial<Contact> = {}): Contact {
  return {
    public_key: 'AAAAAAAAAAAABBBBBBBBBBBBCCCCCCCCCCCCDDDDDDDDDDDDEEEEEEEEEEEE',
    name: 'Test Contact',
    type: CONTACT_TYPE_REPEATER,
    flags: 0,
    last_path: null,
    last_path_len: -1,
    last_advert: null,
    lat: null,
    lon: null,
    last_seen: null,
    on_radio: false,
    last_contacted: null,
    last_read_at: null,
    first_seen: null,
    ...overrides,
  };
}

// Helper to create mock config
function createConfig(overrides: Partial<RadioConfig> = {}): RadioConfig {
  return {
    public_key: 'FFFFFFFFFFFFEEEEEEEEEEEEDDDDDDDDDDDDCCCCCCCCCCCCBBBBBBBBBBBB',
    name: 'MyRadio',
    lat: 40.7128,
    lon: -74.006,
    tx_power: 10,
    max_tx_power: 20,
    path_hash_mode: 0,
    path_hash_mode_supported: true,
    radio: { freq: 915, bw: 250, sf: 10, cr: 8 },
    ...overrides,
  };
}

describe('parsePathHops', () => {
  it('returns empty array for null/empty path', () => {
    expect(parsePathHops(null)).toEqual([]);
    expect(parsePathHops(undefined)).toEqual([]);
    expect(parsePathHops('')).toEqual([]);
  });

  it('parses single hop', () => {
    expect(parsePathHops('1A')).toEqual(['1A']);
  });

  it('parses multiple hops', () => {
    expect(parsePathHops('1A2B3C')).toEqual(['1A', '2B', '3C']);
  });

  it('parses multi-byte hops when path length is provided', () => {
    expect(parsePathHops('1A2B3C4D', 2)).toEqual(['1A2B', '3C4D']);
  });

  it('converts to uppercase', () => {
    expect(parsePathHops('1a2b')).toEqual(['1A', '2B']);
  });

  it('handles odd length by ignoring last character', () => {
    expect(parsePathHops('1A2B3')).toEqual(['1A', '2B']);
  });
});

describe('findContactsByPrefix', () => {
  const contacts: Contact[] = [
    createContact({
      public_key: '1AAAAA' + 'A'.repeat(52),
      name: 'Repeater1',
      type: CONTACT_TYPE_REPEATER,
    }),
    createContact({
      public_key: '1ABBBB' + 'B'.repeat(52),
      name: 'Repeater2',
      type: CONTACT_TYPE_REPEATER,
    }),
    createContact({
      public_key: '2BAAAA' + 'A'.repeat(52),
      name: 'Repeater3',
      type: CONTACT_TYPE_REPEATER,
    }),
    createContact({
      public_key: '1ACCCC' + 'C'.repeat(52),
      name: 'Client1',
      type: 1, // client
    }),
  ];

  it('finds matching repeaters', () => {
    const matches = findContactsByPrefix('1A', contacts, true);
    expect(matches).toHaveLength(2);
    expect(matches.map((c) => c.name)).toContain('Repeater1');
    expect(matches.map((c) => c.name)).toContain('Repeater2');
  });

  it('returns empty array for no match', () => {
    expect(findContactsByPrefix('XX', contacts, true)).toEqual([]);
  });

  it('is case insensitive', () => {
    expect(findContactsByPrefix('1a', contacts, true)).toHaveLength(2);
  });

  it('excludes non-repeaters when repeatersOnly is true', () => {
    const matches = findContactsByPrefix('1A', contacts, true);
    expect(matches.every((c) => c.type === CONTACT_TYPE_REPEATER)).toBe(true);
    expect(matches.map((c) => c.name)).not.toContain('Client1');
  });

  it('includes all types when repeatersOnly is false', () => {
    const matches = findContactsByPrefix('1A', contacts, false);
    expect(matches).toHaveLength(3);
    expect(matches.map((c) => c.name)).toContain('Client1');
  });
});

describe('calculateDistance', () => {
  it('returns null for null coordinates', () => {
    expect(calculateDistance(null, 0, 0, 0)).toBeNull();
    expect(calculateDistance(0, null, 0, 0)).toBeNull();
    expect(calculateDistance(0, 0, null, 0)).toBeNull();
    expect(calculateDistance(0, 0, 0, null)).toBeNull();
  });

  it('returns 0 for same point', () => {
    expect(calculateDistance(40.7128, -74.006, 40.7128, -74.006)).toBe(0);
  });

  it('calculates known distances approximately correctly', () => {
    // NYC (40.7128, -74.0060) to LA (34.0522, -118.2437) is approximately 3944 km
    const distance = calculateDistance(40.7128, -74.006, 34.0522, -118.2437);
    expect(distance).not.toBeNull();
    expect(distance).toBeGreaterThan(3900);
    expect(distance).toBeLessThan(4000);
  });

  it('handles short distances', () => {
    // About 1km apart in NYC
    const distance = calculateDistance(40.7128, -74.006, 40.7218, -74.006);
    expect(distance).not.toBeNull();
    expect(distance).toBeGreaterThan(0.9);
    expect(distance).toBeLessThan(1.1);
  });
});

describe('resolvePath', () => {
  const repeater1 = createContact({
    public_key: '1A' + 'A'.repeat(62),
    name: 'Repeater1',
    type: CONTACT_TYPE_REPEATER,
    lat: 40.75,
    lon: -74.0,
  });
  const repeater2 = createContact({
    public_key: '2B' + 'B'.repeat(62),
    name: 'Repeater2',
    type: CONTACT_TYPE_REPEATER,
    lat: 40.8,
    lon: -73.95,
  });
  const contacts = [repeater1, repeater2];

  const sender = {
    name: 'Sender',
    publicKeyOrPrefix: '5E' + 'E'.repeat(62),
    lat: 40.7,
    lon: -74.05,
  };

  const config = createConfig({
    public_key: 'FF' + 'F'.repeat(62),
    name: 'MyRadio',
    lat: 40.85,
    lon: -73.9,
  });

  it('resolves simple path with known repeaters', () => {
    const result = resolvePath('1A2B', sender, contacts, config);

    expect(result.sender.name).toBe('Sender');
    expect(result.sender.prefix).toBe('5E');
    expect(result.hops).toHaveLength(2);
    expect(result.hops[0].prefix).toBe('1A');
    expect(result.hops[0].matches).toHaveLength(1);
    expect(result.hops[0].matches[0].name).toBe('Repeater1');
    expect(result.hops[1].prefix).toBe('2B');
    expect(result.hops[1].matches).toHaveLength(1);
    expect(result.hops[1].matches[0].name).toBe('Repeater2');
    expect(result.receiver.name).toBe('MyRadio');
    expect(result.receiver.prefix).toBe('FF');
  });

  it('resolves multi-byte hop prefixes when path length is provided', () => {
    const wideContacts = [
      createContact({
        public_key: '1A2B' + 'A'.repeat(60),
        name: 'WideRepeater1',
        type: CONTACT_TYPE_REPEATER,
      }),
      createContact({
        public_key: '3C4D' + 'B'.repeat(60),
        name: 'WideRepeater2',
        type: CONTACT_TYPE_REPEATER,
      }),
    ];

    const result = resolvePath('1A2B3C4D', sender, wideContacts, config, 2);

    expect(result.hops).toHaveLength(2);
    expect(result.hops[0].prefix).toBe('1A2B');
    expect(result.hops[0].matches[0].name).toBe('WideRepeater1');
    expect(result.hops[1].prefix).toBe('3C4D');
    expect(result.hops[1].matches[0].name).toBe('WideRepeater2');
  });

  it('handles unknown repeaters (no matches)', () => {
    const result = resolvePath('XX', sender, contacts, config);

    expect(result.hops).toHaveLength(1);
    expect(result.hops[0].prefix).toBe('XX');
    expect(result.hops[0].matches).toHaveLength(0);
  });

  it('handles ambiguous repeaters (multiple matches)', () => {
    // Create two repeaters with same prefix
    const ambiguousContacts = [
      createContact({
        public_key: '1A' + 'A'.repeat(62),
        name: 'Repeater1A',
        type: CONTACT_TYPE_REPEATER,
        lat: 40.75,
        lon: -74.0,
      }),
      createContact({
        public_key: '1A' + 'B'.repeat(62),
        name: 'Repeater1B',
        type: CONTACT_TYPE_REPEATER,
        lat: 40.76,
        lon: -73.99,
      }),
    ];

    const result = resolvePath('1A', sender, ambiguousContacts, config);

    expect(result.hops).toHaveLength(1);
    expect(result.hops[0].matches).toHaveLength(2);
    // Should be sorted by distance from sender
    expect(result.hops[0].matches[0].name).toBe('Repeater1A');
  });

  it('calculates total distance when all locations known', () => {
    const result = resolvePath('1A2B', sender, contacts, config);

    expect(result.totalDistances).not.toBeNull();
    expect(result.totalDistances!.length).toBeGreaterThan(0);
    expect(result.totalDistances![0]).toBeGreaterThan(0);
  });

  it('returns null totalDistances when locations unknown', () => {
    const unknownRepeater = createContact({
      public_key: 'XX' + 'X'.repeat(62),
      name: 'Unknown',
      type: CONTACT_TYPE_REPEATER,
      lat: null,
      lon: null,
    });

    const result = resolvePath('XX', sender, [unknownRepeater], config);

    expect(result.totalDistances).toBeNull();
  });

  it('handles empty path', () => {
    const result = resolvePath('', sender, contacts, config);

    expect(result.hops).toHaveLength(0);
    expect(result.sender.name).toBe('Sender');
    expect(result.receiver.name).toBe('MyRadio');
  });

  it('handles null config gracefully', () => {
    const result = resolvePath('1A', sender, contacts, null);

    expect(result.receiver.name).toBe('Unknown');
    expect(result.receiver.prefix).toBe('??');
  });

  it('excludes receiver distance when receiver location is (0, 0)', () => {
    const configAtOrigin = createConfig({
      public_key: 'FF' + 'F'.repeat(62),
      name: 'MyRadio',
      lat: 0,
      lon: 0,
    });

    const result = resolvePath('1A', sender, contacts, configAtOrigin);

    // Total distance should NOT include the final leg to receiver
    // It should only be sender -> repeater1
    expect(result.totalDistances).not.toBeNull();
    const senderToRepeater = calculateDistance(
      sender.lat,
      sender.lon,
      repeater1.lat,
      repeater1.lon
    );
    expect(result.totalDistances![0]).toBeCloseTo(senderToRepeater!, 1);
  });

  it('skips distance after ambiguous hops', () => {
    // Create two repeaters with same prefix (ambiguous)
    const ambiguousContacts = [
      createContact({
        public_key: '1A' + 'A'.repeat(62),
        name: 'Repeater1A',
        type: CONTACT_TYPE_REPEATER,
        lat: 40.75,
        lon: -74.0,
      }),
      createContact({
        public_key: '1A' + 'B'.repeat(62),
        name: 'Repeater1B',
        type: CONTACT_TYPE_REPEATER,
        lat: 40.76,
        lon: -73.99,
      }),
      // Known repeater after the ambiguous one
      createContact({
        public_key: '2B' + 'B'.repeat(62),
        name: 'Repeater2',
        type: CONTACT_TYPE_REPEATER,
        lat: 40.8,
        lon: -73.95,
      }),
    ];

    const result = resolvePath('1A2B', sender, ambiguousContacts, config);

    // First hop is ambiguous, second hop is known
    expect(result.hops[0].matches).toHaveLength(2);
    expect(result.hops[1].matches).toHaveLength(1);

    // First hop is ambiguous, so no single distanceFromPrev
    // (UI shows individual distances for each match via getDistanceForContact)
    expect(result.hops[0].distanceFromPrev).toBeNull();

    // Second hop should also NOT have distanceFromPrev because previous hop was ambiguous
    expect(result.hops[1].distanceFromPrev).toBeNull();
  });

  it('calculates partial distance when sender has no location', () => {
    const senderNoLocation = {
      name: 'SenderNoLoc',
      publicKeyOrPrefix: '5E' + 'E'.repeat(62),
      lat: null,
      lon: null,
    };

    const result = resolvePath('1A2B', senderNoLocation, contacts, config);

    // First hop has no distance (can't calculate from unknown sender location)
    expect(result.hops[0].distanceFromPrev).toBeNull();

    // Second hop has distance (from first hop to second hop)
    expect(result.hops[1].distanceFromPrev).not.toBeNull();

    // Total distance should start from first known hop
    expect(result.totalDistances).not.toBeNull();
    expect(result.totalDistances![0]).toBeGreaterThan(0);
  });

  it('returns null totalDistances when all hops have no location', () => {
    const noLocationContacts = [
      createContact({
        public_key: '1A' + 'A'.repeat(62),
        name: 'NoLoc1',
        type: CONTACT_TYPE_REPEATER,
        lat: null,
        lon: null,
      }),
      createContact({
        public_key: '2B' + 'B'.repeat(62),
        name: 'NoLoc2',
        type: CONTACT_TYPE_REPEATER,
        lat: null,
        lon: null,
      }),
    ];

    const senderNoLocation = {
      name: 'SenderNoLoc',
      publicKeyOrPrefix: '5E' + 'E'.repeat(62),
      lat: null,
      lon: null,
    };

    const result = resolvePath('1A2B', senderNoLocation, noLocationContacts, config);

    expect(result.totalDistances).toBeNull();
  });

  it('treats contact at (0, 0) as having no location', () => {
    const contactAtOrigin = createContact({
      public_key: '1A' + 'A'.repeat(62),
      name: 'AtOrigin',
      type: CONTACT_TYPE_REPEATER,
      lat: 0,
      lon: 0,
    });

    const result = resolvePath('1A', sender, [contactAtOrigin], config);

    // Hop should match but have no distance (0, 0 treated as invalid)
    expect(result.hops).toHaveLength(1);
    expect(result.hops[0].matches).toHaveLength(1);
    expect(result.hops[0].distanceFromPrev).toBeNull();
  });

  it('treats sender at (0, 0) as having no location', () => {
    const senderAtOrigin = {
      name: 'SenderAtOrigin',
      publicKeyOrPrefix: '5E' + 'E'.repeat(62),
      lat: 0,
      lon: 0,
    };

    const result = resolvePath('1A2B', senderAtOrigin, contacts, config);

    // First hop should have no distance (sender at 0,0 treated as invalid)
    expect(result.hops[0].distanceFromPrev).toBeNull();

    // But second hop CAN have distance (from first hop)
    expect(result.hops[1].distanceFromPrev).not.toBeNull();
  });

  it('sets hasGaps to false when all hops are unambiguous with locations', () => {
    const result = resolvePath('1A2B', sender, contacts, config);

    expect(result.hasGaps).toBe(false);
  });

  it('sets hasGaps to true when path has unknown hops', () => {
    const result = resolvePath('XX', sender, contacts, config);

    expect(result.hasGaps).toBe(true);
  });

  it('sets hasGaps to true when path has ambiguous hops', () => {
    const ambiguousContacts = [
      createContact({
        public_key: '1A' + 'A'.repeat(62),
        name: 'Repeater1A',
        type: CONTACT_TYPE_REPEATER,
        lat: 40.75,
        lon: -74.0,
      }),
      createContact({
        public_key: '1A' + 'B'.repeat(62),
        name: 'Repeater1B',
        type: CONTACT_TYPE_REPEATER,
        lat: 40.76,
        lon: -73.99,
      }),
    ];

    const result = resolvePath('1A', sender, ambiguousContacts, config);

    expect(result.hasGaps).toBe(true);
  });

  it('sets hasGaps to true when sender has no location', () => {
    const senderNoLocation = {
      name: 'SenderNoLoc',
      publicKeyOrPrefix: '5E' + 'E'.repeat(62),
      lat: null,
      lon: null,
    };

    const result = resolvePath('1A', senderNoLocation, contacts, config);

    expect(result.hasGaps).toBe(true);
  });

  it('sets hasGaps to true when receiver has no valid location', () => {
    const configNoLocation = createConfig({
      public_key: 'FF' + 'F'.repeat(62),
      name: 'MyRadio',
      lat: 0,
      lon: 0,
    });

    const result = resolvePath('1A', sender, contacts, configNoLocation);

    expect(result.hasGaps).toBe(true);
  });

  it('includes receiver public key when config has one', () => {
    const result = resolvePath('1A', sender, contacts, config);

    expect(result.receiver.publicKey).toBe(config.public_key);
  });

  it('sets receiver public key to null when config has no public key', () => {
    const configNoKey = createConfig({
      public_key: undefined as unknown as string,
      name: 'NoKeyRadio',
    });

    const result = resolvePath('1A', sender, contacts, configNoKey);

    expect(result.receiver.publicKey).toBeNull();
  });
});

describe('formatDistance', () => {
  it('formats distances under 1km in meters', () => {
    expect(formatDistance(0.5)).toBe('500m');
    expect(formatDistance(0.123)).toBe('123m');
    expect(formatDistance(0.9999)).toBe('1000m');
  });

  it('formats distances at or above 1km with one decimal', () => {
    expect(formatDistance(1)).toBe('1.0km');
    expect(formatDistance(1.5)).toBe('1.5km');
    expect(formatDistance(12.34)).toBe('12.3km');
    expect(formatDistance(100)).toBe('100.0km');
  });

  it('rounds meters to nearest integer', () => {
    expect(formatDistance(0.4567)).toBe('457m');
    expect(formatDistance(0.001)).toBe('1m');
  });
});

describe('formatHopCounts', () => {
  it('returns empty for null paths', () => {
    const result = formatHopCounts(null);
    expect(result.display).toBe('');
    expect(result.allDirect).toBe(true);
    expect(result.hasMultiple).toBe(false);
  });

  it('returns empty for empty paths array', () => {
    const result = formatHopCounts([]);
    expect(result.display).toBe('');
    expect(result.allDirect).toBe(true);
    expect(result.hasMultiple).toBe(false);
  });

  it('formats single direct path as "d"', () => {
    const result = formatHopCounts([{ path: '', received_at: 1700000000 }]);
    expect(result.display).toBe('d');
    expect(result.allDirect).toBe(true);
    expect(result.hasMultiple).toBe(false);
  });

  it('formats single multi-hop path with hop count', () => {
    const result = formatHopCounts([{ path: '1A2B', received_at: 1700000000 }]);
    expect(result.display).toBe('2');
    expect(result.allDirect).toBe(false);
    expect(result.hasMultiple).toBe(false);
  });

  it('uses explicit path_len for multi-byte hop counts', () => {
    const result = formatHopCounts([{ path: '1A2B3C4D', path_len: 2, received_at: 1700000000 }]);
    expect(result.display).toBe('2');
    expect(result.allDirect).toBe(false);
    expect(result.hasMultiple).toBe(false);
  });

  it('formats multiple paths sorted by hop count', () => {
    const result = formatHopCounts([
      { path: '1A2B3C', received_at: 1700000000 }, // 3 hops
      { path: '', received_at: 1700000001 }, // direct
      { path: '1A', received_at: 1700000002 }, // 1 hop
      { path: '1A2B3C', received_at: 1700000003 }, // 3 hops
    ]);
    expect(result.display).toBe('d/1/3/3');
    expect(result.allDirect).toBe(false);
    expect(result.hasMultiple).toBe(true);
  });

  it('formats multiple direct paths', () => {
    const result = formatHopCounts([
      { path: '', received_at: 1700000000 },
      { path: '', received_at: 1700000001 },
    ]);
    expect(result.display).toBe('d/d');
    expect(result.allDirect).toBe(true);
    expect(result.hasMultiple).toBe(true);
  });

  it('handles mixed paths with multiple direct routes', () => {
    const result = formatHopCounts([
      { path: '1A', received_at: 1700000000 }, // 1 hop
      { path: '', received_at: 1700000001 }, // direct
      { path: '', received_at: 1700000002 }, // direct
    ]);
    expect(result.display).toBe('d/d/1');
    expect(result.allDirect).toBe(false);
    expect(result.hasMultiple).toBe(true);
  });
});
