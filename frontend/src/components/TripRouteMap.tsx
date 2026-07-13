import { useEffect } from 'react'
import L from 'leaflet'
import { CircleMarker, MapContainer, Polyline, TileLayer, useMap } from 'react-leaflet'
import type { Position } from '../api/client'
import { DEFAULT_CENTER, ESRI_ATTRIBUTION, ESRI_WORLD_IMAGERY } from '../lib/map'

const ROUTE_COLOR = '#2563EB'
const START_COLOR = '#16A34A'
const END_COLOR = '#DC2626'

// Same recenter-once-per-route rule as LiveMap's FitRouteBounds: refit when a
// different trip loads, never on rerenders, so the user's own pan/zoom sticks.
function FitBounds({ positions }: { positions: Position[] }) {
  const map = useMap()
  useEffect(() => {
    if (positions.length === 0) return
    const bounds = L.latLngBounds(positions.map((p) => [p.latitude, p.longitude] as [number, number]))
    map.fitBounds(bounds, { padding: [30, 30] })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [positions.length > 0 ? positions[0].id : null, positions.length])
  return null
}

// Small single-purpose map for the vehicle detail page: one trip's breadcrumb with
// start/end markers. Deliberately NOT a LiveMap mode — no zones, fleet markers, or
// editor, just the route.
export function TripRouteMap({ positions, isLoading }: { positions: Position[]; isLoading: boolean }) {
  const start = positions[0]
  const end = positions[positions.length - 1]
  return (
    <div className="ls-trip-route-map">
      <MapContainer
        center={DEFAULT_CENTER}
        zoom={15}
        style={{ height: '100%', width: '100%' }}
        zoomControl={false}
      >
        <TileLayer url={ESRI_WORLD_IMAGERY} attribution={ESRI_ATTRIBUTION} />
        {positions.length > 0 && (
          <>
            <FitBounds positions={positions} />
            <Polyline
              positions={positions.map((p) => [p.latitude, p.longitude] as [number, number])}
              pathOptions={{ color: ROUTE_COLOR, weight: 3, opacity: 0.85 }}
            />
            <CircleMarker
              center={[start.latitude, start.longitude]}
              radius={7}
              pathOptions={{ color: '#fff', weight: 2, fillColor: START_COLOR, fillOpacity: 1 }}
            />
            <CircleMarker
              center={[end.latitude, end.longitude]}
              radius={7}
              pathOptions={{ color: '#fff', weight: 2, fillColor: END_COLOR, fillOpacity: 1 }}
            />
          </>
        )}
      </MapContainer>
      {(isLoading || positions.length === 0) && (
        <div className="ls-trip-route-overlay">{isLoading ? '…' : 'No route data for this trip'}</div>
      )}
    </div>
  )
}
