import { MeshCorePacketDecoder, bytesToHex, hexToBytes } from '@michaelhart/meshcore-decoder';

type DecoderClass = typeof MeshCorePacketDecoder & {
  __multiBytePathPatchApplied?: boolean;
};
type DecoderOptions = Parameters<typeof MeshCorePacketDecoder.decode>[1];

interface PathRewrite {
  hexData: string;
  hopCount: number;
  pathHashSize: number;
}

function decodePathMetadata(pathByte: number): {
  hopCount: number;
  pathHashSize: number;
  pathByteLength: number;
} {
  const pathHashSize = (pathByte >> 6) + 1;
  const hopCount = pathByte & 0x3f;
  return {
    hopCount,
    pathHashSize,
    pathByteLength: hopCount * pathHashSize,
  };
}

function getPackedPathOffset(bytes: Uint8Array): number | null {
  if (bytes.length < 2) return null;

  let offset = 1;
  const routeType = bytes[0] & 0x03;
  if (routeType === 0x00 || routeType === 0x03) {
    if (bytes.length < offset + 4) return null;
    offset += 4;
  }

  return bytes.length > offset ? offset : null;
}

function rewritePackedPathHex(hexData: string): PathRewrite | null {
  let bytes: Uint8Array;
  try {
    bytes = hexToBytes(hexData);
  } catch {
    return null;
  }

  const pathOffset = getPackedPathOffset(bytes);
  if (pathOffset === null) return null;

  const { hopCount, pathHashSize, pathByteLength } = decodePathMetadata(bytes[pathOffset]);
  if (pathHashSize === 1) return null;
  if (bytes.length < pathOffset + 1 + pathByteLength) return null;

  const rewritten = bytes.slice();
  rewritten[pathOffset] = pathByteLength;

  return {
    hexData: bytesToHex(rewritten),
    hopCount,
    pathHashSize,
  };
}

function regroupPath(path: string[] | null, pathHashSize: number): string[] | null {
  if (!path || pathHashSize <= 1) return path;

  const hops: string[] = [];
  for (let i = 0; i + pathHashSize <= path.length; i += pathHashSize) {
    hops.push(path.slice(i, i + pathHashSize).join(''));
  }
  return hops;
}

function normalizeDecodedPacket<
  T extends {
    isValid?: boolean;
    pathLength?: number;
    path?: string[] | null;
  },
>(packet: T, rewrite: PathRewrite | null): T {
  if (!rewrite || packet?.isValid === false) return packet;

  packet.pathLength = rewrite.hopCount;
  packet.path = regroupPath(packet.path ?? null, rewrite.pathHashSize);
  return packet;
}

const decoder = MeshCorePacketDecoder as DecoderClass;

if (!decoder.__multiBytePathPatchApplied) {
  const originalDecode = decoder.decode.bind(decoder);
  const originalDecodeWithVerification = decoder.decodeWithVerification.bind(decoder);
  const originalValidate = decoder.validate.bind(decoder);

  decoder.decode = ((hexData: string, options?: DecoderOptions) => {
    const rewrite = rewritePackedPathHex(hexData);
    const packet = originalDecode(rewrite?.hexData ?? hexData, options);
    return normalizeDecodedPacket(packet, rewrite);
  }) as typeof decoder.decode;

  decoder.decodeWithVerification = (async (hexData: string, options?: DecoderOptions) => {
    const rewrite = rewritePackedPathHex(hexData);
    const packet = await originalDecodeWithVerification(rewrite?.hexData ?? hexData, options);
    return normalizeDecodedPacket(packet, rewrite);
  }) as typeof decoder.decodeWithVerification;

  decoder.validate = ((hexData: string) => {
    const rewrite = rewritePackedPathHex(hexData);
    return originalValidate(rewrite?.hexData ?? hexData);
  }) as typeof decoder.validate;

  decoder.__multiBytePathPatchApplied = true;
}
