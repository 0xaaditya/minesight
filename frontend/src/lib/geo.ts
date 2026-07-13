import type { Zone } from '../api/client'

// Ray-casting point-in-polygon test. GeoJSON rings are [lon, lat]; callers pass
// real lat/lon. Only checks the outer ring (coordinates[0]) — MineSight zones
// aren't drawn with holes.
export function pointInPolygon(lat: number, lon: number, zone: Zone): boolean {
  const ring = zone.geometry.coordinates[0]
  let inside = false
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i]
    const [xj, yj] = ring[j]
    const intersects =
      yi > lat !== yj > lat && lon < ((xj - xi) * (lat - yi)) / (yj - yi) + xi
    if (intersects) inside = !inside
  }
  return inside
}

export function isInsideAnyZone(lat: number, lon: number, zones: Zone[]): boolean {
  // The mine boundary contains the whole site by definition — counting it would make
  // every vehicle "inside a zone" and turn the in/out-of-zone card into a constant.
  // Mirrors the same exclusion in backend trip_engine._active_zones.
  return zones.some((zone) => zone.zone_type !== 'mine_boundary' && pointInPolygon(lat, lon, zone))
}
