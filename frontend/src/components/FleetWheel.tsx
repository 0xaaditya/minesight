import { Fragment } from 'react'
import type { Vehicle, VehicleType } from '../api/client'
import { statusMeta, VEHICLE_TYPE_LABEL } from '../lib/status'

const CX = 310
const CY = 310
const HOLE_R = 58
const INNER_0 = 64
const INNER_1 = 142
const OUTER_0 = 148
const OUTER_1 = 244
const LABEL_R = 250

const CATEGORY_COLORS = ['#0E7490', '#155E75', '#0F766E', '#115E59', '#164E63']

const CATEGORY_ORDER: VehicleType[] = ['tipper', 'excavator', 'loader', 'bowser', 'drill', 'surface_miner']

function polar(r: number, angleDeg: number): [number, number] {
  const rad = ((angleDeg - 90) * Math.PI) / 180
  return [CX + r * Math.cos(rad), CY + r * Math.sin(rad)]
}

function wedgePath(r0: number, r1: number, a0: number, a1: number): string {
  const large = a1 - a0 > 180 ? 1 : 0
  const [xo0, yo0] = polar(r1, a0)
  const [xo1, yo1] = polar(r1, a1)
  const [xi1, yi1] = polar(r0, a1)
  const [xi0, yi0] = polar(r0, a0)
  return `M${xo0} ${yo0} A${r1} ${r1} 0 ${large} 1 ${xo1} ${yo1} L${xi1} ${yi1} A${r0} ${r0} 0 ${large} 0 ${xi0} ${yi0} Z`
}

export function FleetWheel({
  vehicles,
  onSelect,
  accent = '#D97706',
}: {
  vehicles: Vehicle[]
  onSelect: (vehicleId: string) => void
  accent?: string
}) {
  const total = vehicles.length
  if (total === 0) {
    return (
      <svg viewBox="0 0 620 620" className="ls-wheel-svg">
        <circle cx={CX} cy={CY} r={HOLE_R} fill={accent} />
        <text x={CX} y={CY - 6} fill="#fff" fontSize={30} fontWeight={800} textAnchor="middle" dominantBaseline="central">
          0
        </text>
        <text x={CX} y={CY + 18} fill="rgba(255,255,255,.85)" fontSize={11} fontWeight={600} textAnchor="middle" dominantBaseline="central">
          ASSETS
        </text>
      </svg>
    )
  }

  const grouped = CATEGORY_ORDER.map((type) => ({
    type,
    vehicles: vehicles.filter((v) => v.vehicle_type === type),
  })).filter((g) => g.vehicles.length > 0)

  let angle = 0

  return (
    <svg viewBox="0 0 620 620" className="ls-wheel-svg">
      {grouped.map((group, ci) => {
        const span = (group.vehicles.length / total) * 360
        const a0 = angle
        const a1 = angle + span
        angle = a1
        const mid = (a0 + a1) / 2
        const [lx, ly] = polar((INNER_0 + INNER_1) / 2, mid)
        let rot = mid
        if (mid > 90 && mid < 270) rot = mid + 180
        const sub = span / group.vehicles.length

        return (
          <Fragment key={group.type}>
            <path
              d={wedgePath(INNER_0, INNER_1, a0, a1)}
              fill={CATEGORY_COLORS[ci % CATEGORY_COLORS.length]}
              stroke="#fff"
              strokeWidth={1}
            />
            {span > 14 && (
              <text
                x={lx}
                y={ly}
                fill="#fff"
                fontSize={11}
                fontWeight={700}
                textAnchor="middle"
                dominantBaseline="central"
                transform={`rotate(${rot - 90} ${lx} ${ly})`}
                style={{ letterSpacing: '.03em' }}
              >
                {VEHICLE_TYPE_LABEL[group.type].toUpperCase()}
              </text>
            )}
            {group.vehicles.map((v, vi) => {
              const va0 = a0 + vi * sub
              const va1 = va0 + sub
              const meta = statusMeta(v.status)
              const vm = (va0 + va1) / 2
              const [tx, ty] = polar(LABEL_R, vm)
              let vrot = vm - 90
              let anchor: 'start' | 'end' = 'start'
              if (vm > 180) {
                vrot = vm + 90
                anchor = 'end'
              }
              return (
                <Fragment key={v.id}>
                  <path
                    d={wedgePath(OUTER_0, OUTER_1, va0, va1)}
                    fill={meta.color}
                    stroke="#fff"
                    strokeWidth={1}
                    style={{ cursor: 'pointer' }}
                    onClick={() => onSelect(v.id)}
                  >
                    <title>{`${v.asset_id} · ${v.status ?? 'unknown'}`}</title>
                  </path>
                  <text
                    x={tx}
                    y={ty}
                    fill="#64748B"
                    fontSize={7.2}
                    fontWeight={600}
                    textAnchor={anchor}
                    dominantBaseline="central"
                    transform={`rotate(${vrot} ${tx} ${ty})`}
                    style={{ pointerEvents: 'none' }}
                  >
                    {v.asset_id}
                  </text>
                </Fragment>
              )
            })}
          </Fragment>
        )
      })}
      <circle cx={CX} cy={CY} r={HOLE_R} fill={accent} />
      <text x={CX} y={CY - 6} fill="#fff" fontSize={30} fontWeight={800} textAnchor="middle" dominantBaseline="central">
        {total}
      </text>
      <text x={CX} y={CY + 18} fill="rgba(255,255,255,.85)" fontSize={11} fontWeight={600} textAnchor="middle" dominantBaseline="central">
        ASSETS
      </text>
    </svg>
  )
}
