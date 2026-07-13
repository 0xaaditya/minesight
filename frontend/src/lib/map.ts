// Shared map constants — LiveMap (fleet view) and TripRouteMap (vehicle detail) render
// the same imagery so a route looks identical wherever it's shown.

// No Google Maps API per CLAUDE.md — Esri World Imagery (free) is the locked choice.
export const ESRI_WORLD_IMAGERY =
  'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'

export const ESRI_ATTRIBUTION = 'Tiles &copy; Esri'

export const DEFAULT_CENTER: [number, number] = [18.6129, 73.7433] // falls back near the field-test site
