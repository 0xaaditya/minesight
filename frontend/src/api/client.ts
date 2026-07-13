import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

export type VehicleType = 'tipper' | 'excavator' | 'loader' | 'bowser' | 'drill' | 'surface_miner'

// Samarth-style 5-state taxonomy (CLAUDE.md) — always derived server-side, never persisted.
export type VehicleStatus = 'running' | 'idle' | 'breakdown' | 'no_comm' | 'not_installed'

// Haul-cycle state machine status; only meaningful for tipper/loader vehicle types.
export type TripCycleStatus = 'idle' | 'loading' | 'hauling' | 'dumping' | 'returning' | 'breakdown'

export type ZoneType = 'loading' | 'dumping' | 'parking' | 'no_go'

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
  created_at: string
  latest_position: Position | null
  status: VehicleStatus | null
  trip_status: TripCycleStatus | null
}

export interface Zone {
  id: string
  zone_key: string
  name: string
  zone_type: ZoneType
  geometry: { type: 'Polygon'; coordinates: number[][][] }
  valid_from: string
  valid_to: string | null
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
    mutationFn: (payload: { asset_id: string; vehicle_type?: VehicleType }) =>
      apiFetch<Vehicle>('/vehicles', { method: 'POST', body: JSON.stringify(payload) }),
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

export interface ZonePayload {
  name: string
  zone_type: ZoneType
  geometry: Zone['geometry']
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
