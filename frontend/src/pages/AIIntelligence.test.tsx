import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useTwinStore } from '../store/useTwinStore';
import { makeSnapshot } from '../testFixtures';
import AIIntelligence from './AIIntelligence';

const m = vi.hoisted(() => ({
  api: {
    risk: vi.fn(),
    recommendations: vi.fn(),
    analyze: vi.fn(),
    applyRecommendation: vi.fn(),
    anomalies: vi.fn(),
    aiPredictions: vi.fn(),
    aiEvents: vi.fn(),
    aiStatus: vi.fn(),
    analyst: vi.fn(),
    analystStatus: vi.fn(),
    analystRecommendations: vi.fn(),
    analystEvidence: vi.fn(),
    decideAnalystRecommendation: vi.fn(),
    register: vi.fn(),
    login: vi.fn(),
    health: vi.fn(),
    campus: vi.fn(),
    simulations: vi.fn(),
    building: vi.fn(),
    buildingFloors: vi.fn(),
    sensorHistory: vi.fn(),
    sensors: vi.fn(),
    zones: vi.fn(),
    realtimeStatus: vi.fn(),
    realtimeAction: vi.fn(),
    realtimeSpeed: vi.fn(),
  },
  getToken: vi.fn((): string | null => null),
  setToken: vi.fn(),
}));

vi.mock('../services/api', () => ({
  api: m.api,
  getToken: m.getToken,
  setToken: m.setToken,
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
}));

vi.mock('../services/ws', () => ({
  TwinSocket: class {
    connect = vi.fn();
    disconnect = vi.fn();
  },
}));

function renderPage() {
  return render(
    <MemoryRouter>
      <AIIntelligence />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  m.api.risk.mockResolvedValue({
    campus: { score: 30, level: 'LOW', factors: [], explanation: 'quiet' },
    buildings: { 'b-cs': { score: 33, level: 'LOW', factors: [], explanation: '' } },
    metrics: {},
    published: {
      campus: { score: 31, level: 'LOW', factors: [], explanation: 'quiet', raw_score: 30, trend: 'stable' },
      buildings: { 'b-cs': { score: 32, level: 'LOW', factors: [], explanation: '' } },
    },
    hierarchy: null,
    risk_history: { campus: [{ score: 30, level: 'LOW' }] },
    data_source: 'SIMULATED',
  });
  m.api.recommendations.mockResolvedValue([]);
  m.api.anomalies.mockResolvedValue({
    engine: 'layered-v1',
    anomalies: [{
      id: 'an-1', entity_id: 'sensor-1', entity_type: 'SENSOR', kind: 'value',
      sensor_id: 'sensor-1', building_id: 'b-lib', metric: 'smoke',
      detector: 'threshold', anomaly_type: 'SUDDEN_SPIKE',
      location: 'Library', score: 91, band: 'CRITICAL', status: 'ACTIVE',
      value: 14.2, expected: 2.1, z_score: 5.4, deviation_pct: 576,
      explanation: 'smoke well above the rolling baseline',
      confidence: null, available_samples: 4, minimum_required: 6,
      reason: 'value above threshold', first_seen: '2026-10-05T11:00:00Z',
      last_seen: '2026-10-05T11:00:00Z', observations: 2,
    }],
    sensor_status: { 'sensor-1': {
      status: 'CRITICAL', score: 91, type: 'smoke', detector: 'threshold',
      anomaly_id: 'an-1', available_samples: 4, minimum_required: 6,
    } },
    bands: {}, data_quality: 'OK', score_threshold: 75, min_samples: 6,
    count: 1, total: 1,
  });
  m.api.aiPredictions.mockResolvedValue({
    predictions: [{
      entity_id: 'occupancy:campus', metric: 'occupancy', model: 'baseline',
      model_name: 'Deterministic baseline', horizon_min: 30,
      current_value: 795, predicted_value: 812, confidence: 0.6, confidence_label: 'MEDIUM',
      lower_bound: 760, upper_bound: 864, samples: 40, status: 'OK',
      summary: 'Occupancy is expected to rise slightly over the next 30 minutes.',
      at: '2026-10-05T11:00:00Z',
    }],
    count: 1, horizons: [30],
  });
  m.api.aiEvents.mockResolvedValue({
    events: [{ id: 'e1', kind: 'ANOMALY', title: 'Smoke anomaly detected',
               detail: 'Library · smoke', level: 'warn', entity_id: 'sensor-1',
               at: '2026-10-05T11:00:00Z', source: 'ai_engine' }],
    count: 1, ai_health: {},
  });
  m.api.aiStatus.mockResolvedValue({
    phase: 'phase5', enabled: true, degraded: false,
    anomaly_engine: 'LAYERED ANOMALY ENGINE',
  });
  m.api.analyst.mockResolvedValue({ source: 'local_fallback' });
  m.api.analystStatus.mockResolvedValue({
    analyst: {
      status: 'FALLBACK', llm_configured: false, model: 'deterministic-analyst-v1',
      cooldown_seconds: 15, cooldown_remaining_s: 0, in_flight: false,
      cache_size: 0, cache_hits: 0, runs: 1, fallbacks: 1, llm_errors: 0,
      llm_fail_streak: 0, fail_streak: 0, last_run: '2026-10-07T10:00:00Z',
      last_latency_ms: 3, last_source: 'local_fallback', last_error: null,
      current_analysis: '', severity: 'LOW', persisted_limit: 100,
    },
  });
  m.api.analystRecommendations.mockResolvedValue({ recommendations: [], count: 0 });

  useTwinStore.setState({
    token: 'test-token',
    user: { id: 'u1', username: 'operator', role: 'OPERATOR' } as never,
    snapshot: makeSnapshot(),
    connection: 'CONNECTED',
    analyst: null,
    aiFallback: true,
    anomalies: [],
    sensorAiStatus: {},
    anomalyDataQuality: 'OK',
    aiPredictions: [],
    aiEvents: [],
    aiStatus: null,
    aiDegraded: false,
    aiLastUpdated: 0,
    aiRefreshing: false,
    riskPublished: null,
    riskPublishedBuildings: {},
    liveLog: [],
    toast: null,
  });
});

describe('AIIntelligence page (Phase 5)', () => {
  it('renders the mandatory AI limitations disclaimer and core sections', async () => {
    renderPage();
    expect(screen.getByRole('heading', { name: 'AI Intelligence' })).toBeTruthy();
    expect(await screen.findByText(/AI limitations — predictions are statistical estimates/)).toBeTruthy();
    expect(await screen.findByText(/Campus Risk — published \(stabilised\)/)).toBeTruthy();
    expect(screen.getByText('Active anomalies')).toBeTruthy();
    expect(screen.getByText('Recent AI events')).toBeTruthy();
  });

  it('renders anomalies with band chip, metrics and withheld-confidence honesty', async () => {
    renderPage();
    expect((await screen.findAllByText(/Library · smoke/)).length).toBeGreaterThan(0);
    expect(screen.getAllByText('CRITICAL').length).toBeGreaterThan(0);
    expect(screen.getByText(/value 14.2 · expected 2.1 · z 5.4/)).toBeTruthy();
    expect(screen.getByText(/confidence withheld \(n=4<6\)/)).toBeTruthy();
  });

  it('shows the honest in-bounds empty state when the slice is quiet', async () => {
    m.api.anomalies.mockResolvedValue({
      engine: 'layered-v1', anomalies: [], sensor_status: {},
      bands: {}, data_quality: 'OK', score_threshold: 75, min_samples: 6,
      count: 0, total: 0,
    });
    renderPage();
    expect(await screen.findByText(/All telemetry within expected statistical bounds/)).toBeTruthy();
  });

  it('surfaces AI DEGRADED when the AI status endpoint reports degradation', async () => {
    m.api.aiStatus.mockResolvedValue({ phase: 'phase5', enabled: true, degraded: true });
    renderPage();
    expect(await screen.findByText('AI DEGRADED')).toBeTruthy();
  });

  it('renders published campus risk with the raw → published delta', async () => {
    renderPage();
    expect(await screen.findByText(/Campus Risk — published \(stabilised\)/)).toBeTruthy();
    expect(await screen.findByText(/raw 30/)).toBeTruthy();
  });

  it('renders prediction cards with confidence label and honest metrics', async () => {
    renderPage();
    expect(await screen.findByText(/occupancy:campus/)).toBeTruthy();
    expect(screen.getByText('MEDIUM')).toBeTruthy();
    expect(screen.getByText(/\+30m/)).toBeTruthy();
  });
});
