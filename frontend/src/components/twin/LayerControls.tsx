import { useState } from 'react';
import { useTwinStore } from '../../store/useTwinStore';
import { SENSOR_TYPES, SENSOR_TYPE_COLORS, SENSOR_TYPE_LABELS, type LayerKey } from '../../types/twin';
import { IconCheck } from '../Icons';

const PRIMARY_LAYERS: { key: LayerKey; label: string }[] = [
  { key: 'buildings', label: 'Buildings' },
  { key: 'roads', label: 'Roads & Gates' },
  { key: 'sensors', label: 'Sensors' },
  { key: 'zones', label: 'Zones' },
  { key: 'labels', label: 'Labels' },
  { key: 'parking', label: 'Parking' },
  { key: 'trees', label: 'Trees & Lamps' },
];

const SECONDARY_LAYERS: { key: LayerKey; label: string }[] = [
  { key: 'risk', label: 'Risk' },
  { key: 'grid', label: 'Grid' },
  { key: 'occupancy', label: 'Crowd' },
  { key: 'routes', label: 'Evac Routes' },
  { key: 'heatmap', label: 'Heatmap' },
  { key: 'night', label: 'Night' },
];

function LayerCheck({ checked, label, onToggle }: {
  checked: boolean; label: string; onToggle: () => void;
}) {
  return (
    <button
      role="checkbox"
      aria-checked={checked}
      onClick={onToggle}
      className="flex items-center gap-2 w-full px-1.5 py-1 rounded hover:bg-ink-800 focus:outline-none focus-visible:ring-1 focus-visible:ring-brand-400 text-left"
    >
      <span
        className={`w-3.5 h-3.5 rounded-[3px] border flex items-center justify-center shrink-0 ${
          checked ? 'bg-brand-500 border-brand-400' : 'border-line-strong bg-ink-850'
        }`}
      >
        {checked && <IconCheck width={9} height={9} className="text-white" strokeWidth={3} />}
      </span>
      <span className={`text-[11.5px] ${checked ? 'text-mist-100' : 'text-mist-500'}`}>{label}</span>
    </button>
  );
}

/** Layer control panel (spec §21/§22): visibility toggles + sensor type filter. */
export default function LayerControls() {
  const toggles = useTwinStore((s) => s.toggles);
  const toggle = useTwinStore((s) => s.toggle);
  const sensorFilter = useTwinStore((s) => s.sensorFilter);
  const setSensorFilter = useTwinStore((s) => s.setSensorFilter);
  const [open, setOpen] = useState(true);

  return (
    <div className="panel rounded-lg shadow-lg shadow-black/40 w-[220px] overflow-hidden">
      <button
        className="w-full flex items-center justify-between px-3 py-2 hover:bg-ink-800/60 focus:outline-none focus-visible:ring-1 focus-visible:ring-brand-400"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-label={open ? 'Collapse layer controls' : 'Expand layer controls'}
      >
        <span className="label-cap">Layers</span>
        <span className={`text-[10px] text-mist-500 transition-transform ${open ? '' : '-rotate-90'}`}>▾</span>
      </button>

      {open && (
        <div className="px-2.5 pb-2.5 space-y-2.5 border-t border-line pt-2">
          <div className="space-y-0.5">
            {PRIMARY_LAYERS.map((l) => (
              <LayerCheck key={l.key} label={l.label} checked={toggles[l.key]} onToggle={() => toggle(l.key)} />
            ))}
          </div>

          <div className="pt-1.5 border-t border-line">
            <div className="label-cap mb-1">Scene extras</div>
            <div className="flex flex-wrap gap-1">
              {SECONDARY_LAYERS.map((l) => (
                <button
                  key={l.key}
                  onClick={() => toggle(l.key)}
                  aria-pressed={toggles[l.key]}
                  className={`chip !text-[9.5px] ${
                    toggles[l.key] ? 'border-brand-400 bg-brand-950/70 text-brand-200' : 'border-line-strong text-mist-500'
                  }`}
                >
                  {l.label}
                </button>
              ))}
            </div>
          </div>

          <div className="pt-1.5 border-t border-line">
            <div className="label-cap mb-1">Sensor filter</div>
            <div className="flex flex-wrap gap-1">
              <button
                onClick={() => setSensorFilter('all')}
                aria-pressed={sensorFilter === 'all'}
                className={`chip !text-[9.5px] ${
                  sensorFilter === 'all' ? 'border-brand-400 bg-brand-950/70 text-brand-200' : 'border-line-strong text-mist-500'
                }`}
              >
                All
              </button>
              {SENSOR_TYPES.map((t) => (
                <button
                  key={t}
                  onClick={() => setSensorFilter(t)}
                  aria-pressed={sensorFilter === t}
                  title={`Show only ${SENSOR_TYPE_LABELS[t]} sensors`}
                  className={`chip !text-[9.5px] ${
                    sensorFilter === t ? 'border-brand-400 bg-brand-950/70 text-brand-200' : 'border-line-strong text-mist-500'
                  }`}
                >
                  <span className="w-1.5 h-1.5 rounded-full" style={{ background: SENSOR_TYPE_COLORS[t] }} />
                  {SENSOR_TYPE_LABELS[t]}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
