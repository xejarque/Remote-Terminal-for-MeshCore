function decodePathMetadata(pathByteHex: string): { pathByteLength: number } {
  const pathByte = parseInt(pathByteHex, 16);
  const pathHashSize = (pathByte >> 6) + 1;
  const pathLength = pathByte & 0x3f;
  return {
    pathByteLength: pathLength * pathHashSize,
  };
}

/**
 * Extract the payload from a raw packet hex string, skipping header and path.
 * Returns the payload as a hex string, or null if malformed.
 */
export function extractRawPacketPayload(packetHex: string): string | null {
  if (packetHex.length < 4) return null;

  try {
    const header = parseInt(packetHex.slice(0, 2), 16);
    const routeType = header & 0x03;
    let offset = 2;

    if (routeType === 0x00 || routeType === 0x03) {
      if (packetHex.length < offset + 8) return null;
      offset += 8;
    }

    if (packetHex.length < offset + 2) return null;
    const { pathByteLength } = decodePathMetadata(packetHex.slice(offset, offset + 2));
    offset += 2;

    const pathChars = pathByteLength * 2;
    if (packetHex.length < offset + pathChars) return null;
    offset += pathChars;

    return packetHex.slice(offset);
  } catch {
    return null;
  }
}
