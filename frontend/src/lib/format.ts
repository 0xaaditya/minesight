// Display formatting shared across the drawer, map list, vehicles table, and detail
// page — previously duplicated per component (VehicleDrawer/MapPage), consolidated so
// "5 min ago" and IST rendering can't drift between screens.

export const STALE_THRESHOLD_MIN = 10 // matches CLAUDE.md no-comm threshold

export function minutesSince(iso: string): number {
  return Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000))
}

export function formatLastSeen(minutes: number): string {
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes} min ago`
  if (minutes < 60 * 24) return `${Math.floor(minutes / 60)}h ${minutes % 60}m ago`
  return `${Math.floor(minutes / (60 * 24))}d ago`
}

// All times stored UTC, displayed IST (CLAUDE.md convention).
export function formatIST(iso: string): string {
  return new Date(iso).toLocaleTimeString('en-IN', {
    timeZone: 'Asia/Kolkata',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

export function formatISTDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-IN', {
    timeZone: 'Asia/Kolkata',
    day: '2-digit',
    month: 'short',
  })
}

export function formatDistance(meters: number): string {
  return meters >= 1000 ? `${(meters / 1000).toFixed(1)} km` : `${Math.round(meters)} m`
}

export function formatCycleTime(seconds: number): string {
  const min = Math.round(seconds / 60)
  return min < 60 ? `${min} min` : `${Math.floor(min / 60)}h ${min % 60}m`
}
