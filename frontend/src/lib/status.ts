import type { VehicleStatus, VehicleType, ZoneType } from '../api/client'

// Lodestar palette. Single source of truth for status colors — previously
// duplicated ad hoc between LiveMap.tsx and any dashboard cards.
export const STATUS_META: Record<VehicleStatus, { color: string; tint: string; label: string }> = {
  running: { color: '#16A34A', tint: '#F0FDF4', label: 'Running' },
  idle: { color: '#F59E0B', tint: '#FFFBEB', label: 'Idle' },
  breakdown: { color: '#DC2626', tint: '#FEF2F2', label: 'Breakdown' },
  no_comm: { color: '#6B7280', tint: '#F3F4F6', label: 'No-Comm' },
  not_installed: { color: '#D1D5DB', tint: '#F7F7F5', label: 'Not Installed' },
}

// Status is only known once the backend has computed it — before that (or for
// a vehicle with no positions yet) render a neutral "unknown" state rather
// than guessing.
export const UNKNOWN_STATUS_META = { color: '#9AA0A6', tint: '#F3F4F6', label: 'Unknown' }

export function statusMeta(status: VehicleStatus | null) {
  return status ? STATUS_META[status] : UNKNOWN_STATUS_META
}

export const ZONE_META: Record<ZoneType, { color: string; label: string }> = {
  loading: { color: '#16A34A', label: 'Loading' },
  dumping: { color: '#F59E0B', label: 'Dumping' },
  parking: { color: '#94A3B8', label: 'Parking' },
  no_go: { color: '#DC2626', label: 'No-Go' },
}

export const VEHICLE_TYPE_LABEL: Record<VehicleType, string> = {
  tipper: 'Dumper',
  excavator: 'Excavator',
  loader: 'Loader',
  bowser: 'Bowser',
  drill: 'Drill',
  surface_miner: 'Surface Miner',
}
