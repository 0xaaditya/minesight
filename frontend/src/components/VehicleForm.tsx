import { useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import { useCreateVehicle, useUpdateVehicle, type Vehicle, type VehicleType } from '../api/client'
import { useT } from '../i18n/strings'

const VEHICLE_TYPES: { value: VehicleType; label: string; prefix: string }[] = [
  { value: 'tipper', label: 'Tipper / Dumper', prefix: 'S-' },
  { value: 'excavator', label: 'Excavator', prefix: 'EX-' },
  { value: 'loader', label: 'Loader', prefix: 'L-' },
  { value: 'bowser', label: 'Bowser', prefix: 'BB-' },
  { value: 'drill', label: 'Drill', prefix: 'K-' },
  { value: 'surface_miner', label: 'Surface Miner', prefix: 'CSM-' },
]

// Rendered inside a modal, either registering a new vehicle or editing an existing one
// (pass `vehicle` to switch to edit mode — same fields, PATCH instead of POST). On
// success the device is also (re-)registered in Traccar (backend side, and again on
// edit only if the device ID actually changed); if that part fails/was skipped the
// vehicle is still saved, and we keep the modal open to show the warning instead of
// silently closing.
export function VehicleForm({ vehicle, onDone }: { vehicle?: Vehicle; onDone?: () => void }) {
  const T = useT()
  const isEdit = !!vehicle
  const [assetId, setAssetId] = useState(vehicle?.asset_id ?? '')
  const [vehicleType, setVehicleType] = useState<VehicleType>(vehicle?.vehicle_type ?? 'tipper')
  const [deviceId, setDeviceId] = useState(vehicle?.traccar_unique_id ?? '')
  const [regNumber, setRegNumber] = useState(vehicle?.registration_number ?? '')
  const [manufacturer, setManufacturer] = useState(vehicle?.manufacturer ?? '')
  const [capacity, setCapacity] = useState(vehicle?.capacity_tonnes?.toString() ?? '')
  const createVehicle = useCreateVehicle()
  const updateVehicle = useUpdateVehicle()
  const mutation = isEdit ? updateVehicle : createVehicle

  const result = mutation.data
  const traccarWarn = result && (result.traccar_status === 'failed' || result.traccar_status === 'skipped')

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const payload = {
      asset_id: assetId.trim(),
      vehicle_type: vehicleType,
      traccar_unique_id: deviceId.trim() || undefined,
      registration_number: regNumber.trim() || undefined,
      manufacturer: manufacturer.trim() || undefined,
      capacity_tonnes: capacity ? Number(capacity) : undefined,
    }
    const onSuccess = (v: { traccar_status: string | null }) => {
      if (v.traccar_status === 'created' || v.traccar_status === 'exists' || v.traccar_status === null) {
        onDone?.()
      }
    }
    if (isEdit) {
      updateVehicle.mutate({ vehicleId: vehicle.id, ...payload }, { onSuccess })
    } else {
      createVehicle.mutate(payload, { onSuccess })
    }
  }

  if (traccarWarn) {
    return (
      <div className="vehicle-form-warn">
        <p>
          <AlertTriangle size={15} />
          {T('traccarNotRegistered')} {result!.traccar_detail}
        </p>
        <button
          type="button"
          onClick={() => {
            mutation.reset()
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
            (our ESP32 nodes); Teltonika boxes will use their IMEI here. Changing this
            on an existing vehicle re-registers the new ID in Traccar — the "device
            broke, replaced it" flow for hardware whose ID can't be renamed. */}
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
      <button type="submit" disabled={mutation.isPending}>
        {mutation.isPending ? (isEdit ? 'Saving...' : 'Registering...') : isEdit ? T('saveChanges') : T('registerVehicle')}
      </button>
      {mutation.isError && <p className="error">{(mutation.error as Error).message}</p>}
    </form>
  )
}
