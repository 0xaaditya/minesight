import { useEffect, useRef, useState } from 'react'
import { Pause, Play, SkipBack, SkipForward, X } from 'lucide-react'
import type { Position, Vehicle } from '../api/client'
import { useT } from '../i18n/strings'

// Fixed-cadence playback, not scaled to real elapsed time between fixes — a truck
// sending a fix every 30s and one sending every 5s (event trigger) would otherwise
// play back at wildly different speeds. Simpler and predictable for v0.
const STEP_INTERVAL_MS = 400

function formatIST(iso: string): string {
  return new Date(iso).toLocaleString('en-GB', {
    timeZone: 'Asia/Kolkata',
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
}

export function ReplayPanel({
  vehicle,
  positions,
  isLoading,
  index,
  onIndexChange,
  onClose,
}: {
  vehicle: Vehicle
  positions: Position[]
  isLoading: boolean
  index: number
  onIndexChange: (index: number) => void
  onClose: () => void
}) {
  const T = useT()
  const [playing, setPlaying] = useState(false)
  const indexRef = useRef(index)
  indexRef.current = index

  useEffect(() => {
    if (!playing || positions.length === 0) return
    const id = setInterval(() => {
      const next = indexRef.current + 1
      if (next >= positions.length) {
        setPlaying(false)
        return
      }
      onIndexChange(next)
    }, STEP_INTERVAL_MS)
    return () => clearInterval(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing, positions.length])

  const current = positions[index]

  return (
    <div className="ls-replay-panel">
      <div className="ls-replay-head">
        <span>{T('replayToday')}</span>
        {/* Close lives top-RIGHT — matches where every other dismiss control in the app
            sits (drawer, zone panel), so it's found without hunting (user feedback). */}
        <button className="ls-icon-btn ls-replay-back" onClick={onClose} aria-label="Close replay">
          <X size={17} />
        </button>
      </div>
      <div className="ls-replay-body">
        <div className="ls-replay-vehicle">{vehicle.asset_id}</div>

        {isLoading ? (
          <div className="ls-replay-empty">…</div>
        ) : positions.length === 0 ? (
          <div className="ls-replay-empty">{T('noTripsToday')}</div>
        ) : (
          <>
            <input
              type="range"
              min={0}
              max={positions.length - 1}
              value={index}
              onChange={(e) => {
                setPlaying(false)
                onIndexChange(Number(e.target.value))
              }}
              className="ls-replay-slider"
            />
            <div className="ls-replay-controls">
              <span className="ls-replay-count">
                {index + 1}/{positions.length}
              </span>
              <button
                className="ls-icon-btn"
                onClick={() => onIndexChange(Math.max(0, index - 1))}
                disabled={index === 0}
                aria-label="Step back"
              >
                <SkipBack size={15} />
              </button>
              <button
                className="ls-icon-btn ls-replay-play"
                onClick={() => setPlaying((p) => !p)}
                aria-label={playing ? 'Pause' : 'Play'}
              >
                {playing ? <Pause size={16} /> : <Play size={16} />}
              </button>
              <button
                className="ls-icon-btn"
                onClick={() => onIndexChange(Math.min(positions.length - 1, index + 1))}
                disabled={index === positions.length - 1}
                aria-label="Step forward"
              >
                <SkipForward size={15} />
              </button>
              <span className="ls-replay-time">{current ? formatIST(current.event_time) : ''}</span>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
