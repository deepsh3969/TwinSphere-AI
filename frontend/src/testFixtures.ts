import type {
  Building, BuildingDetail, CampusSummary, Sensor, SensorHistory, Snapshot, Zone,
} from './types';

export function makeSensor(over: Partial<Sensor> = {}): Sensor {
  return {
    id: 'sensor-1',
    sensor_code: 'T-001',
    name: 'Temperature Sensor 1',
    type: 'temperature',
    building_id: 'b-cs',
    zone_id: 'z-cs-1',
    unit: '°C',
    status: 'ONLINE',
    x: 10,
    y: 4.5,
    z: -12,
    min_value: 0,
    max_value: 60,
    normal_min: 15,
    normal_max: 32,
    value: 24.5,
    last_reading: 24.5,
    baseline: 23.5,
    healthy: true,
    updated_at: 1_760_000_000,
    ...over,
  };
}

export function makeZone(over: Partial<Zone> = {}): Zone {
  return {
    id: 'z-cs-1',
    building_id: 'b-cs',
    name: 'Server Room',
    floor: 1,
    floor_id: 'b-cs-F1',
    capacity: 10,
    occupancy: 4,
    kind: 'server_room',
    zone_type: 'IT',
    risk_level: 'LOW',
    width: 12,
    depth: 8,
    height: 4,
    adjacent: [],
    fire: 0,
    smoke: 0,
    temperature: 24,
    status: 'NORMAL',
    local_x: 4,
    local_z: -3,
    ...over,
  };
}

export function makeBuilding(over: Partial<Building> = {}): Building {
  return {
    id: 'b-cs',
    code: 'CS',
    name: 'Computer Science Block',
    type: 'ACADEMIC',
    description: 'Teaching and research block.',
    capacity: 400,
    occupancy: 210,
    occupancy_pct: 52.5,
    floors: 3,
    status: 'OPERATIONAL',
    position: { x: -40, y: 0, z: 30 },
    latitude: 6.5245,
    longitude: 3.3791,
    size: { x: 60, z: 40 },
    height: 12,
    color: '#3b82f6',
    has_backup_power: true,
    temperature: 24.1,
    humidity: 55,
    energy: 120,
    smoke: 0,
    air_quality: 42,
    water: 0,
    risk: 22,
    risk_level: 'LOW',
    sensor_health: 100,
    power: true,
    backup_power: false,
    evacuation_order: false,
    ...over,
  };
}

export function makeSummary(over: Partial<CampusSummary> = {}): CampusSummary {
  return {
    buildings: 6,
    floors: 18,
    zones: 42,
    sensors: 35,
    roads: 14,
    gates: 4,
    exits: 6,
    occupancy: 812,
    occupancy_pct: 41,
    risk_score: 24,
    risk_level: 'LOW',
    active_incidents: 1,
    active_simulations: 0,
    ...over,
  };
}

export function makeSnapshot(over: Partial<Snapshot> = {}): Snapshot {
  return {
    clock: 0,
    clock_hour: 12,
    speed: 1,
    status: 'NORMAL',
    recovery_progress: 0,
    buildings: [makeBuilding()],
    zones: [makeZone()],
    sensors: [makeSensor()],
    roads: [],
    nodes: [],
    incidents: [],
    risk: {} as unknown as Snapshot['risk'],
    building_risk: {},
    predictions: [],
    anomalies: [],
    recommendations: [],
    routes: [],
    alerts: [],
    active_sim: null,
    metrics: {} as unknown as Snapshot['metrics'],
    system_health: {},
    connected_clients: 1,
    data_source: 'SIMULATED',
    summary: makeSummary(),
    ...over,
  };
}

export function makeBuildingDetail(over: Partial<BuildingDetail> = {}): BuildingDetail {
  return {
    ...makeBuilding(),
    zones: [makeZone()],
    sensors: [makeSensor()],
    risk_detail: { level: 'LOW', score: 22, factors: {} } as unknown as BuildingDetail['risk_detail'],
    exits: [],
    routes: [],
    incidents: [],
    predictions: [],
    zone_count: 1,
    sensor_count: 1,
    floor_count: 3,
    ...over,
  } as BuildingDetail;
}

export function makeHistory(over: Partial<SensorHistory> = {}): SensorHistory {
  const persisted = Array.from({ length: 12 }, (_, i) => {
    const hour = String(10 + i).padStart(2, '0');
    return {
      value: 22 + i * 0.3,
      at: `2026-10-04T${hour}:00:00Z`,
      timestamp: `2026-10-04T${hour}:00:00Z`,
      quality: 'GOOD',
      source: 'simulator',
    };
  });
  return {
    sensor: makeSensor(),
    data_source: 'SIMULATED',
    source: 'simulator',
    live: [],
    persisted,
    ...over,
  };
}
