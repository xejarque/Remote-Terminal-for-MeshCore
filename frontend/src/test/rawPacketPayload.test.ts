import { describe, expect, it } from 'vitest';

import { extractRawPacketPayload } from '../utils/rawPacketPayload';

describe('extractRawPacketPayload', () => {
  it('extracts payload for legacy one-byte hops', () => {
    expect(extractRawPacketPayload('1502AABBDEADBEEF')).toBe('DEADBEEF');
  });

  it('extracts payload for multi-byte hops', () => {
    expect(extractRawPacketPayload('154220273031DEADBEEF')).toBe('DEADBEEF');
  });

  it('extracts payload for transport packets with multi-byte hops', () => {
    expect(extractRawPacketPayload('14010203044220273031DEADBEEF')).toBe('DEADBEEF');
  });

  it('returns null for truncated multi-byte path data', () => {
    expect(extractRawPacketPayload('15422027')).toBeNull();
  });
});
