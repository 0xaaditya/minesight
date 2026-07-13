import { useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import { useCreateVehicle, type VehicleType } from '../api/client'
import { useT } from '../i18n/strings'

const VEHICLE_TYPES: { value: VehicleType; label: string; prefix: string }[] = [
  { value: 'tipper', label: 'Tipper / Dumper', prefix: 'S-' },
  { value: 'excavator', label: 'Excavator', prefix: 'EX-' },
  { value: 'loader', label: 'Loader', prefix: 'L-' },
  { value: 'bowser', label: 'Bowser', prefix: 'BB-' },
  { value: 'drill', label: 'Drill', prefix: 'K-' },
  { value: 'surface_miner', label: 'Surface Miner', prefix: 'CSM-' },
]

// Rendered inside the register modal. On success the device is also auto-created in
// Traccar (backend side); if that part fails/was skipped the vehicle is still saved,
// and we keep the modal open to show the warning instead of silently closing.
export function VehicleForm({ onDone }: { onDone?: () => void }) {
  const T = useT()
  const [assetId, setAssetId] = useState('')
  const [vehicleType, setVehicleType] = useState<VehicleType>('tipper')
  const [deviceId, setDeviceId] = useState('')
  const [regNumber, setRegNumber] = useState('')
  const [manufacturer, setManufacturer] = useState('')
  const [capacity, setCapacity] = useState('')
  const createVehicle = useCreateVehicle()

  const created = createVehicle.data
  const traccarWarn =
    created && (created.traccar_status === 'failed' || created.traccar_status === 'skipped')

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    createVehicle.mutate(
      {
        asset_id: assetId.trim(),
        vehicle_type: vehicleType,
        traccar_unique_id: deviceId.trim() || undefined,
        registration_number: regNumber.trim() || undefined,
        manufacturer: manufacturer.trim() || undefined,
        capacity_tonnes: capacity ? Number(capacity) : undefined,
      },
      {
        onSuccess: (vehicle) => {
          if (vehicle.traccar_status === 'created' || vehicle.traccar_status === 'exists') {
            onDone?.()
          }
        },
      },
    )
  }

  if (traccarWarn) {
    return (
      <div className="vehicle-form-warn">
        <p>
          <AlertTriangle size={15} />
          {T('traccarNotRegistered')} {created!.traccar_detail}
        </p>
        <button
          type="button"
          onClick={() => {
            createVehicle.reset()
            onDone?.()
          }}
        >
          {T('done')}
        </button>
      </div>
    )
  }

  return (
    <form onSubmit={handleSubmit} className="vehicle-form">
      <label className="vehicle-form-field">
        <span>{T('assetId')}</span>
        <input
          type="text"
          placeholder="e.g. S-052"
          value={assetId}
          onChange={(e) => setAssetId(e.target.value)}
          required
          autoFocus
        />
      </label>
      <label className="vehicle-form-field">
        <span>Type</span>
        <select value={vehicleType} onChange={(e) => setVehicleType(e.target.value as VehicleType)}>
          {VEHICLE_TYPES.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label} ({t.prefix})
            </option>
          ))}
        </select>
      </label>
      <label className="vehicle-form-field">
        <span>{T('deviceUniqueId')}</span>
        {/* What the tracker sends as its OsmAnd `id=`. Blank = same as the asset ID
            (our ESP32 nodes); Teltonika boxes will use their IMEI here. */}
        <input
          type="text"
          placeholder={assetId.trim() || 'defaults to asset ID'}
          value={deviceId}
          onChange={(e) => setDeviceId(e.target.value)}
        />
      </label>
      <label className="vehicle-form-field">
        <span>{T('registrationNumber')}</span>
        <input
          type="text"
          placeholder="e.g. MH12 AB 1234"
          value={regNumber}
          onChange={(e) => setRegNumber(e.target.value)}
        />
      </label>
      <label className="vehicle-form-field">
        <span>{T('manufacturer')}</span>
        <input
          type="text"
          placeholder="e.g. Tata, Volvo, BEML"
          value={manufacturer}
          onChange={(e) => setManufacturer(e.target.value)}
        />
      </label>
      <label className="vehicle-form-field">
        <span>{T('capacityTonnes')}</span>
        <input
          type="number"
          min="0"
          step="0.5"
          placeholder="e.g. 25"
          value={capacity}
          onChange={(e) => setCapacity(e.target.value)}
        />
      </label>
      <button type="submit" disabled={createVehicle.isPending}>
        {createVehicle.isPending ? 'Registering...' : 'Register Vehicle'}
      </button>
      {createVehicle.isError && <p className="error">{createVehicle.error.message}</p>}
    </form>
  )
}
