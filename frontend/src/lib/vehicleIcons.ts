import type { ComponentType } from 'react'
import { Construction, Drill, Forklift, Fuel, Mountain, Truck } from 'lucide-react'
import type { VehicleType } from '../api/client'

export const TYPE_ICON: Record<VehicleType, ComponentType<{ size?: number }>> = {
  tipper: Truck,
  excavator: Construction,
  loader: Forklift,
  bowser: Fuel,
  drill: Drill,
  surface_miner: Mountain,
}
