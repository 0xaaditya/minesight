import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

export type VehicleType = 'tipper' | 'excavator' | 'loader' | 'bowser' | 'drill' | 'surface_miner'

// Samarth-style 5-state taxonomy (CLAUDE.md) — always derived server-side, never persisted.
export type VehicleStatus = 'running' | 'idle' | 'breakdown' | 'no_comm' | 'not_installed'

// Haul-cycle state machine status; only meaningful for tipper/loader vehicle types.
export type TripCycleStatus = 'idle' | 'loading' | 'hauling' | 'dumping' | 'returning' | 'breakdown'

// mine_boundary is the whole-site perimeter — display/reporting only; the backend trip
// engine excludes it so it can't suppress breakdown detection (see trip_engine._active_zones).
export type ZoneType = 'loading' | 'dumping' | 'parking' | 'no_go' | 'mine_boundary'

export type TripRowStatus = 'in_progress' | 'completed' | 'aborted'

export interface Position {
  id: string
  event_time: string
  received_at: string
  latitude: number
  longitude: number
  speed_knots: number | null
  course: number | null
  hdop: number | null
  satellites: number | null
}

export interface Vehicle {
  id: string
  asset_id: string
  vehicle_type: VehicleType
  traccar_unique_id: string
  registration_number: string | null
  manufacturer: string | null
  capacity_tonnes: number | null
  created_at: string
  deactivated_at: string | null
  latest_position: Position | null
  status: VehicleStatus | null
  trip_status: TripCycleStatus | null
  // POST/PATCH /vehicles responses only: outcome of registering the device in Traccar.
  traccar_status: 'created' | 'exists' | 'failed' | 'skipped' | null
  traccar_detail: string | null
}

export interface VehicleCreatePayload {
  asset_id: string
  vehicle_type?: VehicleType
  traccar_unique_id?: string
  registration_number?: string
  manufacturer?: string
  capacity_tonnes?: number
}

export type VehicleUpdatePayload = Partial<VehicleCreatePayload>

export interface VehicleDeleteResult {
  action: 'deleted' | 'deactivated'
  vehicle: Vehicle | null
}

export interface Zone {
  id: string
  zone_key: string
  name: string
  zone_type: ZoneType
  geometry: { type: 'Polygon'; coordinates: number[][][] }
  speed_limit_kmph: number | null
  valid_from: string
  valid_to: string | null
}

// Named FleetEvent, not Event, to avoid shadowing the DOM Event type.
export type EventType = 'night_movement' | 'boundary_exit' | 'zone_overspeed' | 'breakdown'
export type EventSeverity = 'critical' | 'warning'

export interface FleetEvent {
  id: string
  vehicle_id: string
  event_type: EventType
  severity: EventSeverity
  event_time: string
  detected_at: string
  ended_at: string | null
  latitude: number
  longitude: number
  zone_id: string | null
  details: Record<string, unknown> | null
  delayed: boolean
  acknowledged_at: string | null
  notified_at: string | null
  vehicle_asset_id: string | null
  zone_name: string | null
}

export interface Trip {
  id: string
  vehicle_id: string
  cycle_number: number | null
  load_zone_id: string | null
  load_excavator_vehicle_id: string | null
  dump_zone_id: string | null
  started_at: string
  loaded_at: string | null
  dumped_at: string | null
  completed_at: string | null
  haul_distance_m: number | null // lead distance: loaded -> dumped breadcrumb path
  trip_distance_m: number | null // full trip-row path: started -> completed
  status: TripRowStatus
  had_anomalous_entry: boolean
  cycle_time_seconds: number | null
  load_excavator_asset_id: string | null // which excavator filled this truck
  vehicle_asset_id: string | null // /loads view only: which truck was filled
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail ?? `Request failed: ${res.status}`)
  }
  if (res.status === 204) return undefined as T
  return res.json()
}

export function useVehicles() {
  return useQuery({
    queryKey: ['vehicles'],
    queryFn: () => apiFetch<Vehicle[]>('/vehicles'),
    refetchInterval: 5000, // v0: polling. WebSocket push is a later phase (CLAUDE.md dashboard spec).
  })
}

export function useCreateVehicle() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: VehicleCreatePayload) =>
      apiFetch<Vehicle>('/vehicles', { method: 'POST', body: JSON.stringify(payload) }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['vehicles'] }),
  })
}

// Single-vehicle read for the deep-linkable detail page — the /vehicles list poll
// doesn't help someone landing directly on /vehicles/:id.
export function useVehicle(vehicleId: string | undefined) {
  return useQuery({
    queryKey: ['vehicle', vehicleId],
    queryFn: () => apiFetch<Vehicle>(`/vehicles/${vehicleId}`),
    enabled: !!vehicleId,
    refetchInterval: 5000,
  })
}

export function useUpdateVehicle() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ vehicleId, ...payload }: VehicleUpdatePayload & { vehicleId: string }) =>
      apiFetch<Vehicle>(`/vehicles/${vehicleId}`, { method: 'PATCH', body: JSON.stringify(payload) }),
    onSuccess: (vehicle) => {
      queryClient.invalidateQueries({ queryKey: ['vehicles'] })
      queryClient.invalidateQueries({ queryKey: ['vehicle', vehicle.id] })
    },
  })
}

// Guarded on the backend: hard-deletes only if the vehicle has zero trip/position
// history, otherwise soft-deactivates it (result.action tells the UI which happened).
export function useDeleteVehicle() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vehicleId: string) =>
      apiFetch<VehicleDeleteResult>(`/vehicles/${vehicleId}`, { method: 'DELETE' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['vehicles'] }),
  })
}

export function useVehiclePositions(vehicleId: string | undefined) {
  return useQuery({
    queryKey: ['positions', vehicleId],
    queryFn: () => apiFetch<Position[]>(`/vehicles/${vehicleId}/positions`),
    enabled: !!vehicleId,
    refetchInterval: 5000,
  })
}

// Route replay: the full breadcrumb for one IST day. Historical once fetched — no
// polling, unlike the live position feed above.
export function useVehicleRoute(vehicleId: string | undefined, date: string) {
  return useQuery({
    queryKey: ['route', vehicleId, date],
    queryFn: () => apiFetch<Position[]>(`/vehicles/${vehicleId}/positions?date=${date}`),
    enabled: !!vehicleId,
  })
}

export function useZones() {
  return useQuery({
    queryKey: ['zones'],
    queryFn: () => apiFetch<Zone[]>('/zones'),
    refetchInterval: 30000, // zone shapes change rarely — no need to poll as fast as positions
  })
}

// Backend day-bucketing is IST-based (CLAUDE.md: "all times stored UTC, displayed IST"),
// so "today" must be computed in IST or a shift spanning UTC midnight gets split in two.
export function todayIST(): string {
  return new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Kolkata' })
}

export function useVehicleTrips(vehicleId: string | undefined, date: string, enabled = true) {
  return useQuery({
    queryKey: ['trips', vehicleId, date],
    queryFn: () => apiFetch<Trip[]>(`/vehicles/${vehicleId}/trips?date=${date}`),
    enabled: enabled && !!vehicleId,
    refetchInterval: 5000,
  })
}

// Excavator-facing view of the trips table: every trip this excavator loaded. Trips
// make no sense on an excavator card — the owner wants "how many trucks did it fill".
export function useExcavatorLoads(vehicleId: string | undefined, date: string, enabled = true) {
  return useQuery({
    queryKey: ['loads', vehicleId, date],
    queryFn: () => apiFetch<Trip[]>(`/vehicles/${vehicleId}/loads?date=${date}`),
    enabled: enabled && !!vehicleId,
    refetchInterval: 5000,
  })
}

// Detail-page period filters: inclusive IST day range, or omit both for all-time.
function rangeQuery(start?: string, end?: string): string {
  return start && end ? `?start_date=${start}&end_date=${end}` : ''
}

export function useVehicleTripsRange(
  vehicleId: string | undefined,
  start: string | undefined,
  end: string | undefined,
  enabled = true,
) {
  return useQuery({
    queryKey: ['trips-range', vehicleId, start ?? 'all', end ?? 'all'],
    queryFn: () => apiFetch<Trip[]>(`/vehicles/${vehicleId}/trips${rangeQuery(start, end)}`),
    enabled: enabled && !!vehicleId,
    refetchInterval: 5000,
  })
}

export function useExcavatorLoadsRange(
  vehicleId: string | undefined,
  start: string | undefined,
  end: string | undefined,
  enabled = true,
) {
  return useQuery({
    queryKey: ['loads-range', vehicleId, start ?? 'all', end ?? 'all'],
    queryFn: () => apiFetch<Trip[]>(`/vehicles/${vehicleId}/loads${rangeQuery(start, end)}`),
    enabled: enabled && !!vehicleId,
    refetchInterval: 5000,
  })
}

export interface VehicleStats {
  distance_m: number | null
}

// Live "Distance" tile — works for every vehicle type (excavators/bowsers included),
// unlike the trip-derived tiles which only make sense for haul-cycle vehicles.
export function useVehicleStats(vehicleId: string | undefined, start: string | undefined, end: string | undefined) {
  return useQuery({
    queryKey: ['vehicle-stats', vehicleId, start ?? 'all', end ?? 'all'],
    queryFn: () => apiFetch<VehicleStats>(`/vehicles/${vehicleId}/stats${rangeQuery(start, end)}`),
    enabled: !!vehicleId,
    refetchInterval: 5000,
  })
}

// One trip's breadcrumb: bounded on both ends so it doesn't drag in the rest of the
// day. Historical once fetched — no polling.
export function useTripRoute(vehicleId: string | undefined, sinceIso: string | undefined, untilIso: string | undefined) {
  return useQuery({
    queryKey: ['trip-route', vehicleId, sinceIso, untilIso],
    queryFn: () => apiFetch<Position[]>(`/vehicles/${vehicleId}/positions?since=${sinceIso}&until=${untilIso}`),
    enabled: !!vehicleId && !!sinceIso && !!untilIso,
  })
}

export interface ZonePayload {
  name: string
  zone_type: ZoneType
  geometry: Zone['geometry']
  speed_limit_kmph?: number
}

export function useCreateZone() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: ZonePayload) =>
      apiFetch<Zone>('/zones', { method: 'POST', body: JSON.stringify(payload) }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['zones'] }),
  })
}

// PUT closes the current version (valid_to=now) and inserts a new one under the same
// zone_key (see backend/app/routers/zones.py) — this is how "moving" a zone works, since
// zone history is versioned rather than mutated in place.
export function useUpdateZone() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ zoneKey, ...payload }: ZonePayload & { zoneKey: string }) =>
      apiFetch<Zone>(`/zones/${zoneKey}`, { method: 'PUT', body: JSON.stringify(payload) }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['zones'] }),
  })
}

// DELETE closes the current version (valid_to=now) — the zone row itself is never hard
// deleted, so historical Trips that reference it by id stay intact.
export function useDeleteZone() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (zoneKey: string) => apiFetch<void>(`/zones/${zoneKey}`, { method: 'DELETE' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['zones'] }),
  })
}

export function useEvents() {
  return useQuery({
    queryKey: ['events'],
    queryFn: () => apiFetch<FleetEvent[]>('/events?limit=50'),
    refetchInterval: 5000,
  })
}

export function useAckEvent() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (eventId: string) => apiFetch<FleetEvent>(`/events/${eventId}/ack`, { method: 'POST' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['events'] }),
  })
}
