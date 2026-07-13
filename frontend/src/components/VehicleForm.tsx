import { useState } from 'react'
import { useCreateVehicle, type VehicleType } from '../api/client'

const VEHICLE_TYPES: { value: VehicleType; label: string; prefix: string }[] = [
  { value: 'tipper', label: 'Tipper / Dumper', prefix: 'S-' },
  { value: 'excavator', label: 'Excavator', prefix: 'EX-' },
  { value: 'loader', label: 'Loader', prefix: 'L-' },
  { value: 'bowser', label: 'Bowser', prefix: 'BB-' },
  { value: 'drill', label: 'Drill', prefix: 'K-' },
  { value: 'surface_miner', label: 'Surface Miner', prefix: 'CSM-' },
]

export function VehicleForm() {
  const [assetId, setAssetId] = useState('')
  const [vehicleType, setVehicleType] = useState<VehicleType>('tipper')
  const createVehicle = useCreateVehicle()

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    createVehicle.mutate(
      { asset_id: assetId.trim(), vehicle_type: vehicleType },
      { onSuccess: () => setAssetId('') },
    )
  }

  return (
    <form onSubmit={handleSubmit} className="vehicle-form">
      <input
        type="text"
        placeholder="Asset ID (e.g. S-052)"
        value={assetId}
        onChange={(e) => setAssetId(e.target.value)}
        required
      />
      <select value={vehicleType} onChange={(e) => setVehicleType(e.target.value as VehicleType)}>
        {VEHICLE_TYPES.map((t) => (
          <option key={t.value} value={t.value}>
            {t.label} ({t.prefix})
          </option>
        ))}
      </select>
      <button type="submit" disabled={createVehicle.isPending}>
        {createVehicle.isPending ? 'Registering...' : 'Register Vehicle'}
      </button>
      {createVehicle.isError && <p className="error">{createVehicle.error.message}</p>}
    </form>
  )
}
