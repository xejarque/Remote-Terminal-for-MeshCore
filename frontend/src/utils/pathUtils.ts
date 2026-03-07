import type { Contact, RadioConfig, MessagePath } from '../types';
import { CONTACT_TYPE_REPEATER } from '../types';

export interface PathHop {
  prefix: string; // Hex prefix for a single hop
  matches: Contact[]; // Matched repeaters (empty=unknown, multiple=ambiguous)
  distanceFromPrev: number | null; // km from previous hop
}

export interface ResolvedPath {
  sender: { name: string; prefix: string; lat: number | null; lon: number | null };
  hops: PathHop[];
  receiver: {
    name: string;
    prefix: string;
    lat: number | null;
    lon: number | null;
    publicKey: string | null;
  };
  totalDistances: number[] | null; // Single-element array with sum of unambiguous distances
  /** True if path has any gaps (unknown, ambiguous, or missing location hops) */
  hasGaps: boolean;
}

export interface SenderInfo {
  name: string;
  publicKeyOrPrefix: string;
  lat: number | null;
  lon: number | null;
}

/**
 * Split hex string into hop-sized chunks.
 */
export function parsePathHops(path: string | null | undefined, pathLen?: number): string[] {
  if (!path || path.length === 0) {
    return [];
  }

  const normalized = path.toUpperCase();
  const hopCount = pathLen ?? Math.floor(normalized.length / 2);
  const charsPerHop =
    hopCount > 0 && normalized.length % hopCount === 0 ? normalized.length / hopCount : 2;
  const hops: string[] = [];

  for (let i = 0; i + charsPerHop <= normalized.length; i += charsPerHop) {
    hops.push(normalized.slice(i, i + charsPerHop));
  }

  return hops;
}

/**
 * Find contacts matching first 2 chars of public key (repeaters only for intermediate hops)
 */
export function findContactsByPrefix(
  prefix: string,
  contacts: Contact[],
  repeatersOnly: boolean = true
): Contact[] {
  const normalizedPrefix = prefix.toUpperCase();
  return contacts.filter((c) => {
    if (repeatersOnly && c.type !== CONTACT_TYPE_REPEATER) {
      return false;
    }
    return c.public_key.toUpperCase().startsWith(normalizedPrefix);
  });
}

/**
 * Calculate distance between two points using Haversine formula
 * @returns Distance in km, or null if coordinates are missing
 */
export function calculateDistance(
  lat1: number | null,
  lon1: number | null,
  lat2: number | null,
  lon2: number | null
): number | null {
  if (lat1 === null || lon1 === null || lat2 === null || lon2 === null) {
    return null;
  }

  const R = 6371; // Earth's radius in km
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a =
    Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) * Math.sin(dLon / 2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return R * c;
}

function toRad(deg: number): number {
  return (deg * Math.PI) / 180;
}

/**
 * Check if coordinates represent a valid location
 * Returns false for null or (0, 0) which indicates unset location
 */
export function isValidLocation(lat: number | null, lon: number | null): boolean {
  if (lat === null || lon === null) {
    return false;
  }
  // (0, 0) is in the Atlantic Ocean - treat as unset
  if (lat === 0 && lon === 0) {
    return false;
  }
  return true;
}

/**
 * Format distance in human-readable form (m or km)
 */
export function formatDistance(km: number): string {
  if (km < 1) {
    return `${Math.round(km * 1000)}m`;
  }
  return `${km.toFixed(1)}km`;
}

/**
 * Sort contacts by distance from a reference point
 * Contacts without location are placed at the end
 */
function sortContactsByDistance(
  contacts: Contact[],
  fromLat: number | null,
  fromLon: number | null
): Contact[] {
  if (fromLat === null || fromLon === null) {
    return contacts;
  }

  return [...contacts].sort((a, b) => {
    const distA = calculateDistance(fromLat, fromLon, a.lat, a.lon);
    const distB = calculateDistance(fromLat, fromLon, b.lat, b.lon);

    // Null distances go to the end
    if (distA === null && distB === null) return 0;
    if (distA === null) return 1;
    if (distB === null) return -1;

    return distA - distB;
  });
}

/**
 * Get simple hop count from path string
 */
function getHopCount(path: string | null | undefined, pathLen?: number): number {
  if (!path || path.length === 0) {
    return 0;
  }
  return pathLen ?? Math.floor(path.length / 2);
}

/**
 * Format hop counts from multiple paths for display.
 * Returns something like "d/1/3/3" for direct, 1-hop, 3-hop, 3-hop paths.
 * Returns null if no paths or only direct.
 */
export function formatHopCounts(paths: MessagePath[] | null | undefined): {
  display: string;
  allDirect: boolean;
  hasMultiple: boolean;
} {
  if (!paths || paths.length === 0) {
    return { display: '', allDirect: true, hasMultiple: false };
  }

  // Get hop counts for all paths and sort ascending
  const hopCounts = paths.map((p) => getHopCount(p.path, p.path_len)).sort((a, b) => a - b);

  const allDirect = hopCounts.every((h) => h === 0);
  const hasMultiple = paths.length > 1;

  // Format: "d" for 0, numbers for others
  const parts = hopCounts.map((h) => (h === 0 ? 'd' : h.toString()));
  const display = parts.join('/');

  return { display, allDirect, hasMultiple };
}

/**
 * Build complete path resolution with sender, hops, and receiver
 */
export function resolvePath(
  path: string | null | undefined,
  sender: SenderInfo,
  contacts: Contact[],
  config: RadioConfig | null,
  pathLen?: number
): ResolvedPath {
  const hopPrefixes = parsePathHops(path, pathLen);

  // Build sender info
  const senderPrefix = sender.publicKeyOrPrefix.toUpperCase().slice(0, 2);
  const resolvedSender = {
    name: sender.name,
    prefix: senderPrefix,
    lat: sender.lat,
    lon: sender.lon,
  };

  // Build receiver info from radio config
  const receiverPrefix = config?.public_key?.toUpperCase().slice(0, 2) || '??';
  const resolvedReceiver = {
    name: config?.name || 'Unknown',
    prefix: receiverPrefix,
    lat: config?.lat ?? null,
    lon: config?.lon ?? null,
    publicKey: config?.public_key ?? null,
  };

  // Build hops
  const hops: PathHop[] = [];
  let prevLat = sender.lat;
  let prevLon = sender.lon;
  // Start uncertain if sender has no valid location
  let prevHopUncertain = !isValidLocation(sender.lat, sender.lon);

  for (const prefix of hopPrefixes) {
    const matches = findContactsByPrefix(prefix, contacts, true);
    const sortedMatches = sortContactsByDistance(matches, prevLat, prevLon);

    // Calculate distance from previous hop
    // Can't calculate if previous hop was uncertain (unknown/ambiguous/no location) or current hop is unknown/invalid
    let distanceFromPrev: number | null = null;
    const currentHasValidLocation =
      sortedMatches.length === 1 && isValidLocation(sortedMatches[0].lat, sortedMatches[0].lon);
    if (!prevHopUncertain && currentHasValidLocation) {
      distanceFromPrev = calculateDistance(
        prevLat,
        prevLon,
        sortedMatches[0].lat,
        sortedMatches[0].lon
      );
    }

    hops.push({
      prefix,
      matches: sortedMatches,
      distanceFromPrev,
    });

    // Update previous location for next hop
    if (sortedMatches.length === 0) {
      // Unknown hop - can't calculate distance for next hop
      prevHopUncertain = true;
      prevLat = null;
      prevLon = null;
    } else if (sortedMatches.length > 1) {
      // Ambiguous hop - can't calculate distance for next hop (too many combinations)
      prevHopUncertain = true;
      // Use first match's location for sorting purposes, but distance won't be shown
      if (isValidLocation(sortedMatches[0].lat, sortedMatches[0].lon)) {
        prevLat = sortedMatches[0].lat;
        prevLon = sortedMatches[0].lon;
      } else {
        prevLat = null;
        prevLon = null;
      }
    } else if (isValidLocation(sortedMatches[0].lat, sortedMatches[0].lon)) {
      prevHopUncertain = false;
      prevLat = sortedMatches[0].lat;
      prevLon = sortedMatches[0].lon;
    } else {
      // Known hop but no valid location - treat as uncertain for distance purposes
      prevHopUncertain = true;
      prevLat = null;
      prevLon = null;
    }
  }

  // Calculate total distances (can be multiple if ambiguous)
  const totalDistances = calculateTotalDistances(resolvedSender, hops, resolvedReceiver);

  // Determine if path has any gaps (unknown, ambiguous, or missing location)
  const hasGaps =
    !isValidLocation(resolvedSender.lat, resolvedSender.lon) ||
    !isValidLocation(resolvedReceiver.lat, resolvedReceiver.lon) ||
    hops.some(
      (hop) => hop.matches.length !== 1 || !isValidLocation(hop.matches[0].lat, hop.matches[0].lon)
    );

  return {
    sender: resolvedSender,
    hops,
    receiver: resolvedReceiver,
    totalDistances,
    hasGaps,
  };
}

/**
 * Calculate total distance(s) for the path
 * Returns array for ambiguous paths, null if any segment can't be calculated
 * If sender has no location, starts calculating from first hop with location
 */
function calculateTotalDistances(
  sender: { lat: number | null; lon: number | null },
  hops: PathHop[],
  receiver: { lat: number | null; lon: number | null }
): number[] | null {
  // Simple case: no hops
  if (hops.length === 0) {
    if (!isValidLocation(sender.lat, sender.lon) || !isValidLocation(receiver.lat, receiver.lon)) {
      return null;
    }
    const dist = calculateDistance(sender.lat, sender.lon, receiver.lat, receiver.lon);
    return dist !== null ? [dist] : null;
  }

  // Start from sender if it has valid location, otherwise find first hop with valid location
  let prevLat = sender.lat;
  let prevLon = sender.lon;
  let startHopIndex = 0;

  if (!isValidLocation(prevLat, prevLon)) {
    // Find first hop with a known, unambiguous, valid location
    for (let i = 0; i < hops.length; i++) {
      const hop = hops[i];
      if (hop.matches.length === 1 && isValidLocation(hop.matches[0].lat, hop.matches[0].lon)) {
        prevLat = hop.matches[0].lat;
        prevLon = hop.matches[0].lon;
        startHopIndex = i + 1;
        break;
      }
    }
    // If no hop has valid location, can't calculate
    if (!isValidLocation(prevLat, prevLon)) {
      return null;
    }
  }

  // Sum up only unambiguous segments (where both endpoints are known and unambiguous)
  let totalDistance = 0;
  let hasAnyDistance = false;
  let lastUnambiguousHopIndex = -1; // Track last unambiguous hop for receiver distance

  for (let i = startHopIndex; i < hops.length; i++) {
    const hop = hops[i];

    // Skip if hop is unknown or ambiguous or has no valid location
    if (hop.matches.length !== 1 || !isValidLocation(hop.matches[0].lat, hop.matches[0].lon)) {
      // Can't include this segment - reset prevLat/prevLon for next potential segment
      prevLat = null;
      prevLon = null;
      continue;
    }

    // Only calculate distance if previous location is known (unambiguous)
    if (prevLat !== null && prevLon !== null) {
      const dist = calculateDistance(prevLat, prevLon, hop.matches[0].lat, hop.matches[0].lon);
      if (dist !== null) {
        totalDistance += dist;
        hasAnyDistance = true;
      }
    }

    // Update for next iteration
    prevLat = hop.matches[0].lat;
    prevLon = hop.matches[0].lon;
    lastUnambiguousHopIndex = i;
  }

  // Add final leg to receiver only if last hop was unambiguous and receiver has valid location
  if (lastUnambiguousHopIndex === hops.length - 1 && prevLat !== null && prevLon !== null) {
    if (isValidLocation(receiver.lat, receiver.lon)) {
      const finalDist = calculateDistance(prevLat, prevLon, receiver.lat, receiver.lon);
      if (finalDist !== null) {
        totalDistance += finalDist;
        hasAnyDistance = true;
      }
    }
  }

  // Return total if we calculated any distance
  return hasAnyDistance ? [totalDistance] : null;
}
