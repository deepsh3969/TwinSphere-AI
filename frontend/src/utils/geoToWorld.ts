/**
 * Deterministic local coordinate conversion: campus latitude/longitude →
 * Three.js world meters using a local tangent-plane (equirectangular) model.
 *
 * The backend already provides authoritative `position.x/z` world coordinates
 * for every building — this utility is the fallback/reference layer for
 * geo-located entities (spec §45). No external map API is used.
 */

export interface WorldPoint {
  x: number;
  z: number;
}

/** Campus origin ≈ centroid of the six seeded building coordinates. */
export const CAMPUS_ORIGIN = {
  latitude: 6.524262,
  longitude: 3.379443,
} as const;

const METERS_PER_DEGREE_LAT = 111_320;

function metersPerDegreeLon(latitudeDeg: number): number {
  return 111_320 * Math.cos((latitudeDeg * Math.PI) / 180);
}

/**
 * Convert WGS84 coordinates to local world meters around the campus origin.
 * Positive x = east, negative z = north (map-style "up").
 */
export function geoToWorld(
  latitude: number,
  longitude: number,
  origin: { latitude: number; longitude: number } = CAMPUS_ORIGIN,
): WorldPoint {
  const dLat = latitude - origin.latitude;
  const dLon = longitude - origin.longitude;
  return {
    x: dLon * metersPerDegreeLon(origin.latitude),
    z: -dLat * METERS_PER_DEGREE_LAT,
  };
}

/** Inverse of {@link geoToWorld} (used for inspector coordinate readouts). */
export function worldToGeo(
  point: WorldPoint,
  origin: { latitude: number; longitude: number } = CAMPUS_ORIGIN,
): { latitude: number; longitude: number } {
  return {
    latitude: origin.latitude - point.z / METERS_PER_DEGREE_LAT,
    longitude: origin.longitude + point.x / metersPerDegreeLon(origin.latitude),
  };
}

/** Great-circle distance in meters between two geo points (sanity checks). */
export function geoDistanceMeters(
  a: { latitude: number; longitude: number },
  b: { latitude: number; longitude: number },
): number {
  return Math.hypot(
    (a.latitude - b.latitude) * METERS_PER_DEGREE_LAT,
    (a.longitude - b.longitude) * metersPerDegreeLon((a.latitude + b.latitude) / 2),
  );
}
