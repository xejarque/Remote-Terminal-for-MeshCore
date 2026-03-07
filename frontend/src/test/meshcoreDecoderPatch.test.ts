import { describe, expect, it } from 'vitest';

import '../utils/meshcoreDecoderPatch';
import { MeshCoreDecoder } from '@michaelhart/meshcore-decoder';

describe('meshcoreDecoderPatch', () => {
  it('groups two-byte hops and preserves payload extraction', () => {
    const decoded = MeshCoreDecoder.decode('3E4220273031DEADBEEF');

    expect(decoded.isValid).toBe(true);
    expect(decoded.pathLength).toBe(2);
    expect(decoded.path).toEqual(['2027', '3031']);
    expect(decoded.payload.raw).toBe('DEADBEEF');
  });

  it('groups three-byte hops and preserves payload extraction', () => {
    const decoded = MeshCoreDecoder.decode('3E82112233445566DEADBEEF');

    expect(decoded.isValid).toBe(true);
    expect(decoded.pathLength).toBe(2);
    expect(decoded.path).toEqual(['112233', '445566']);
    expect(decoded.payload.raw).toBe('DEADBEEF');
  });

  it('patches async decode entrypoints used by the cracker', async () => {
    const decoded = await MeshCoreDecoder.decodeWithVerification('3E4220273031DEADBEEF');

    expect(decoded.isValid).toBe(true);
    expect(decoded.pathLength).toBe(2);
    expect(decoded.path).toEqual(['2027', '3031']);
    expect(decoded.payload.raw).toBe('DEADBEEF');
  });

  it('validates multi-byte packets using rewritten byte lengths', () => {
    const result = MeshCoreDecoder.validate('3E82112233445566DEADBEEF');

    expect(result.isValid).toBe(true);
  });
});
