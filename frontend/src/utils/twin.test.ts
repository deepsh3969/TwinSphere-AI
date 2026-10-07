import { describe, expect, it } from 'vitest';
import { trendDir, trendLabel } from './colors';
import {
  CAMPUS_ORIGIN, geoDistanceMeters, geoToWorld, worldToGeo,
} from './geoToWorld';
import {
  floorLabel, sensorTypeColor, sensorTypeLabel, VIEW_MODE_LAYERS, zoneTypeColor,
} from '../types/twin';

describe('geoToWorld', () => {
  it('maps the campus origin to world zero', () => {
    const p = geoToWorld(CAMPUS_ORIGIN.latitude, CAMPUS_ORIGIN.longitude);
    expect(p.x).toBeCloseTo(0, 6);
    expect(p.z).toBeCloseTo(0, 6);
  });

  it('places north of the origin on negative z (map-style up)', () => {
    const p = geoToWorld(CAMPUS_ORIGIN.latitude + 0.001, CAMPUS_ORIGIN.longitude);
    expect(p.x).toBeCloseTo(0, 6);
    expect(p.z).toBeLessThan(0);
    expect(p.z).toBeCloseTo(-111.32, 0);
  });

  it('round-trips through worldToGeo', () => {
    const lat = CAMPUS_ORIGIN.latitude + 0.0023;
    const lon = CAMPUS_ORIGIN.longitude - 0.0031;
    const world = geoToWorld(lat, lon);
    const geo = worldToGeo(world);
    expect(geo.latitude).toBeCloseTo(lat, 9);
    expect(geo.longitude).toBeCloseTo(lon, 9);
  });
});

describe('geoDistanceMeters', () => {
  it('approximates a 0.01° latitude span as ~1.1 km', () => {
    const d = geoDistanceMeters(
      { latitude: CAMPUS_ORIGIN.latitude, longitude: CAMPUS_ORIGIN.longitude },
      { latitude: CAMPUS_ORIGIN.latitude + 0.01, longitude: CAMPUS_ORIGIN.longitude },
    );
    expect(d).toBeGreaterThan(1100);
    expect(d).toBeLessThan(1120);
  });

  it('is zero for identical points', () => {
    const p = { latitude: 6.52, longitude: 3.38 };
    expect(geoDistanceMeters(p, p)).toBe(0);
  });
});

describe('twin display helpers', () => {
  it('labels floor 1 as Ground and the rest as Level N', () => {
    expect(floorLabel(1)).toBe('Ground');
    expect(floorLabel(2)).toBe('Level 2');
    expect(floorLabel(5)).toBe('Level 5');
  });

  it('keeps the zones view mode scoped to zone layers', () => {
    expect(VIEW_MODE_LAYERS.zones.zones).toBe(true);
    expect(VIEW_MODE_LAYERS.zones.buildings).toBe(true);
    expect(VIEW_MODE_LAYERS.overview.zones).toBe(false);
  });

  it('falls back to neutral colors for unknown sensor/zone types', () => {
    expect(sensorTypeColor('temperature')).toBe('#f97316');
    expect(sensorTypeColor('quantum')).toBe('#94a3b8');
    expect(sensorTypeLabel('air_quality')).toBe('Air Quality');
    expect(zoneTypeColor('classroom')).toBe('#3b82f6');
    expect(zoneTypeColor('unknown_kind')).toBe('#64748b');
  });

  it('keeps the risk layer off outside RISK MODE and on inside it', () => {
    expect(VIEW_MODE_LAYERS.risk.risk).toBe(true);
    expect(VIEW_MODE_LAYERS.overview.risk).toBe(false);
    expect(VIEW_MODE_LAYERS.zones.risk).toBe(false);
  });
});

describe('Phase 5 published-risk trend', () => {
  it('derives direction from the numeric EMA delta', () => {
    expect(trendDir(0.83)).toBe('rising');
    expect(trendDir(-1.4)).toBe('falling');
    expect(trendDir(0)).toBe('stable');
    expect(trendDir(0.02)).toBe('stable');
  });

  it('tolerates direction strings and unknown values', () => {
    expect(trendDir('rising')).toBe('rising');
    expect(trendDir('FALLING')).toBe('falling');
    expect(trendDir(undefined)).toBe('stable');
    expect(trendDir('wobbly')).toBe('stable');
  });

  it('labels numbers with a signed delta and words otherwise', () => {
    expect(trendLabel(0.83)).toBe('+0.83');
    expect(trendLabel(-2.5)).toBe('-2.50');
    expect(trendLabel(0)).toBe('stable');
    expect(trendLabel('rising')).toBe('rising');
  });
});
