import type { RiskLevel } from './index';

/** Layer keys toggleable from the twin layer panel. */
export type LayerKey =
  | 'buildings' | 'roads' | 'sensors' | 'zones' | 'labels'
  | 'parking' | 'trees' | 'grid' | 'heatmap' | 'occupancy' | 'routes' | 'night'
  | 'risk';

/** High-level emphasis modes for the viewport (does not remove data). */
export type ViewMode = 'overview' | 'buildings' | 'sensors' | 'zones' | 'risk';

export type SensorType =
  | 'temperature' | 'occupancy' | 'energy' | 'smoke'
  | 'air_quality' | 'humidity' | 'water' | 'traffic' | 'parking';

export type SensorFilter = 'all' | SensorType;

export type InspectorMode = 'campus' | 'building' | 'sensor';

export type CameraPresetName = 'iso' | 'top' | 'front' | 'north';

/** Sensor type catalog — single source of truth for markers, legend and filters. */
export const SENSOR_TYPES: SensorType[] = [
  'temperature', 'occupancy', 'energy', 'smoke',
  'air_quality', 'humidity', 'water', 'traffic', 'parking',
];

export const SENSOR_TYPE_LABELS: Record<SensorType, string> = {
  temperature: 'Temperature',
  occupancy: 'Occupancy',
  energy: 'Energy',
  smoke: 'Smoke',
  air_quality: 'Air Quality',
  humidity: 'Humidity',
  water: 'Water',
  traffic: 'Traffic',
  parking: 'Parking',
};

/** Distinct, CVD-friendly hues (shape/icon pairings handled in UI). */
export const SENSOR_TYPE_COLORS: Record<SensorType, string> = {
  temperature: '#f97316',
  occupancy: '#38bdf8',
  energy: '#facc15',
  smoke: '#ef4444',
  air_quality: '#a78bfa',
  humidity: '#22d3ee',
  water: '#60a5fa',
  traffic: '#f472b6',
  parking: '#34d399',
};

export function isSensorType(value: string): value is SensorType {
  return (SENSOR_TYPES as string[]).includes(value);
}

export function sensorTypeColor(type: string): string {
  return isSensorType(type) ? SENSOR_TYPE_COLORS[type] : '#94a3b8';
}

export function sensorTypeLabel(type: string): string {
  return isSensorType(type) ? SENSOR_TYPE_LABELS[type] : type;
}

/** Neutral zone tints by functional type (NOT risk — risk uses getRiskColor). */
export const ZONE_TYPE_COLORS: Record<string, string> = {
  classroom: '#3b82f6',
  lab: '#8b5cf6',
  corridor: '#64748b',
  stair: '#78716c',
  stairwell: '#78716c',
  office: '#0ea5e9',
  hall: '#14b8a6',
  entrance: '#22c55e',
  exit: '#22c55e',
  emergency_exit: '#22c55e',
  server_room: '#f43f5e',
  storage: '#a16207',
  kitchen: '#f59e0b',
  dining: '#f59e0b',
  ward: '#ec4899',
  reception: '#10b981',
};

export function zoneTypeColor(kind: string): string {
  return ZONE_TYPE_COLORS[kind] ?? '#64748b';
}

/** Floor display label: floor 1 is the ground floor of the campus model. */
export function floorLabel(floorNumber: number): string {
  return floorNumber === 1 ? 'Ground' : `Level ${floorNumber}`;
}

export interface CameraPreset {
  pos: [number, number, number];
  target: [number, number, number];
}

export const CAMERA_PRESETS: Record<CameraPresetName, CameraPreset> = {
  iso: { pos: [118, 96, 132], target: [0, 0, 0] },
  top: { pos: [0, 268, 0.01], target: [0, 0, 0] },
  front: { pos: [0, 34, 186], target: [0, 8, 0] },
  north: { pos: [-40, 64, -176], target: [-20, 4, 20] },
};

/** Distance used when focusing a building. */
export const FOCUS_DISTANCE = 95;

/** Layer defaults applied when switching view modes (user can still toggle after). */
export const VIEW_MODE_LAYERS: Record<ViewMode, Partial<Record<LayerKey, boolean>>> = {
  overview: { buildings: true, roads: true, sensors: true, zones: false, labels: true, parking: true, trees: true, risk: false },
  buildings: { buildings: true, roads: true, sensors: false, zones: false, labels: true, parking: true, trees: true, risk: false },
  sensors: { buildings: true, roads: true, sensors: true, zones: false, labels: false, parking: true, trees: true, risk: false },
  zones: { buildings: true, roads: true, sensors: false, zones: true, labels: true, parking: false, trees: true, risk: false },
  // Phase 5 — RISK MODE: tint by published risk, keep context visible
  risk: { buildings: true, roads: true, sensors: true, zones: false, labels: true,
          parking: false, trees: false, risk: true, heatmap: false, night: false },
};

/** RISK MODE palette (spec §57): subtle, never alarming — LOW green .. CRITICAL deep red. */
export const RISK_MODE_COLORS: Record<RiskLevel, string> = {
  LOW: '#22c55e',
  MODERATE: '#eab308',
  ELEVATED: '#f97316',
  HIGH: '#ef4444',
  CRITICAL: '#b91c1c',
};

export interface TwinSnapshotSlice {
  summary?: {
    buildings?: number; floors?: number; zones?: number; sensors?: number;
    roads?: number; gates?: number; exits?: number;
    occupancy?: number; occupancy_pct?: number;
    risk_score?: number; risk_level?: RiskLevel;
    active_incidents?: number; active_simulations?: number;
  } | null;
}
