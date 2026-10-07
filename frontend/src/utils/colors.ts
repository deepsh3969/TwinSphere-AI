import type { RiskLevel } from '../types';

export function riskColor(score: number): string {
  if (score > 80) return '#ef4444';
  if (score > 60) return '#f97316';
  if (score > 40) return '#eab308';
  if (score > 20) return '#84cc16';
  return '#22c55e';
}

/**
 * Risk level → color (spec §47). When risk data is absent/unknown the
 * neutral slate is returned — risk is never invented.
 */
export const NEUTRAL_COLOR = '#64748b';

export function getRiskColor(level?: RiskLevel | string | null): string {
  switch ((level ?? '').toUpperCase()) {
    case 'CRITICAL': return '#ef4444';
    case 'HIGH': return '#f97316';
    case 'ELEVATED': return '#f59e0b';
    case 'MODERATE': return '#eab308';
    case 'LOW': return '#22c55e';
    default: return NEUTRAL_COLOR;
  }
}

/** True when the backend actually provided a risk level for the entity. */
export function hasRiskData(level?: RiskLevel | string | null): boolean {
  return Boolean(level) && ['LOW', 'MODERATE', 'ELEVATED', 'HIGH', 'CRITICAL'].includes(String(level).toUpperCase());
}

export function riskTextClass(score: number): string {
  if (score > 80) return 'text-red-400';
  if (score > 60) return 'text-orange-400';
  if (score > 40) return 'text-amber-300';
  if (score > 20) return 'text-lime-300';
  return 'text-emerald-400';
}

export function levelChip(level: RiskLevel | string): string {
  switch (level) {
    case 'CRITICAL': return 'border-red-600 bg-red-950/70 text-red-300';
    case 'HIGH': return 'border-orange-600 bg-orange-950/70 text-orange-300';
    case 'ELEVATED': return 'border-amber-600 bg-amber-950/70 text-amber-300';
    case 'MODERATE': return 'border-lime-600 bg-lime-950/70 text-lime-300';
    default: return 'border-emerald-700 bg-emerald-950/70 text-emerald-300';
  }
}

/**
 * Published-risk trend direction. The backend publishes a numeric delta
 * (rounded EMA change, Phase 5 `RiskStability`) — tolerate direction strings too.
 */
export function trendDir(trend?: number | string | null): 'rising' | 'falling' | 'stable' {
  if (typeof trend === 'number') return trend > 0.05 ? 'rising' : trend < -0.05 ? 'falling' : 'stable';
  const t = String(trend ?? '').toLowerCase();
  if (t === 'rising' || t === 'falling' || t === 'stable') return t;
  return 'stable';
}

/** Human-readable trend: signed delta for numbers, direction word otherwise. */
export function trendLabel(trend?: number | string | null): string {
  if (typeof trend === 'number' && Math.abs(trend) >= 0.01) return `${trend > 0 ? '+' : ''}${trend.toFixed(2)}`;
  return trendDir(trend);
}

export function routeColor(status: string): string {
  if (status === 'BLOCKED') return '#ef4444';
  if (status === 'WARNING') return '#eab308';
  return '#22c55e';
}

/** Phase 7 §7 — mode-specific route colors (3D lines + panel swatches). */
export function routeModeColor(mode: string): string {
  switch (mode) {
    case 'shortest': return '#38bdf8';
    case 'fastest': return '#f97316';
    case 'safest': return '#22c55e';
    case 'emergency': return '#f43f5e';
    default: return '#a78bfa';   // balanced
  }
}

/** Phase 7 §10 — safety band colors for computed routes. */
export function routeSafetyColor(safety: string): string {
  switch (safety) {
    case 'HIGH_RISK': return '#ef4444';
    case 'WARNING': return '#eab308';
    default: return '#22c55e';
  }
}

/** Phase 7 §16 — per-vehicle colors for emergency response routes. */
export function vehicleColor(vehicle: string): string {
  switch (vehicle) {
    case 'fire_truck': return '#ef4444';
    case 'ambulance': return '#f472b6';
    default: return '#38bdf8';   // security
  }
}

/** Severity chips for bottlenecks (§13). */
export function severityChip(severity: string): string {
  switch (severity) {
    case 'HIGH': return 'border-red-600 bg-red-950/70 text-red-300';
    case 'MEDIUM': return 'border-amber-600 bg-amber-950/70 text-amber-300';
    default: return 'border-sky-700 bg-sky-950/70 text-sky-300';
  }
}

export function fmtClock(hour: number): string {
  const h = Math.floor(hour) % 24;
  const m = Math.floor((hour % 1) * 60);
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
}

export function fmtNum(value: number, digits = 0): string {
  return value.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}

export function scenarioLabel(scenario: string): string {
  return ({
    fire: 'Fire Emergency',
    crowd: 'Crowd Surge',
    power: 'Power Failure',
    road: 'Road Closure',
    temperature: 'Extreme Temperature',
  } as Record<string, string>)[scenario] ?? scenario;
}

export function scenarioIcon(scenario: string): string {
  return ({ fire: '🔥', crowd: '👥', power: '⚡', road: '🚗', temperature: '🌡' } as Record<string, string>)[scenario] ?? '•';
}
