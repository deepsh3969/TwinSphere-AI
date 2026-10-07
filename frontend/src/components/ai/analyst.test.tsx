import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import AnalystBrief from './AnalystBrief';
import EvidencePanel from './EvidencePanel';
import type { AnalystRecommendationRow, AnalystReport } from '../../types';

const m = vi.hoisted(() => ({
  api: {
    analystEvidence: vi.fn(),
    decideAnalystRecommendation: vi.fn(),
  },
  getToken: vi.fn((): string | null => null),
  setToken: vi.fn(),
}));

vi.mock('../../services/api', () => ({
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

const REPORT: AnalystReport = {
  source: 'local_fallback',
  model: 'deterministic-analyst-v1',
  what_happened: 'legacy happened',
  why_it_matters: 'legacy why',
  likely_next: 'legacy next',
  recommended_action: 'legacy action',
  analysis_id: 'anl_test1',
  mode: 'INCIDENT',
  situation: {
    title: 'Fire in Engineering', summary: 'Smoke spread across 2 zones.',
    severity: 'HIGH', priority: 'HIGH', mode: 'INCIDENT',
  },
  what_is_happening: ['Fire active in eng_faculty', 'Risk climbing'],
  why: [{ factor: 'Occupancy 86%', impact: 'MEDIUM' }],
  affected_areas: ['Engineering'],
  predicted_effects: [{ effect: 'Smoke may worsen', likelihood: 'HIGH', time_horizon: '15 minutes' }],
  what_changed: [{ kind: 'risk_change', message: 'Risk moved 12 → 44', previous: '12', current: '44' }],
  confidence: {
    overall: 0.82, level: 'HIGH',
    components: [{ name: 'sensor_availability', value: 1, weight: 0.22, contribution: 0.22 }],
    notes: ['Confidence reduced because sensor data is 40s old.'],
  },
  route_assessment: {
    recommended_route: 'Emergency Gate (Gate B)', status: 'RECOMMENDED',
    risk: 4, estimated_time: 31, reason: 'Lowest-risk passable route.',
  },
  recommendations: [{
    id: 'anl_test1_r1', priority: 1, category: 'EVACUATION',
    action: 'Prioritize evacuation', reason: 'Fire spreading',
    evidence_ids: ['anl_test1:ev_1'], confidence: 0.8,
  }],
  evidence: [{
    id: 'anl_test1:ev_1', label: 'Campus risk 44/100 (HIGH)', source_type: 'risk',
    metric: 'risk_score', value: 44, severity: 'HIGH', confidence: 0.9,
    detail: 'trend rising', timestamp: '2026-10-07T10:00:00Z',
  }],
  question: 'where is safest?',
  query_answer: 'Emergency Gate (Gate B) is the safest exit.',
  latency_ms: 4,
};

const ROW: AnalystRecommendationRow = {
  recommendation_id: 'anl_test1_r1', analysis_id: 'anl_test1', priority: 1,
  category: 'EVACUATION', action: 'Prioritize evacuation', reason: 'Fire spreading',
  evidence: ['Campus risk 44/100 (HIGH)'], evidence_ids: ['anl_test1:ev_1'],
  confidence: 0.8, requires_human_approval: true, status: 'PENDING',
  decided_by: '', decided_at: null, created_at: '2026-10-07T10:00:00',
};

beforeEach(() => {
  m.api.analystEvidence.mockResolvedValue({ ...REPORT.evidence![0], detail: 'persisted copy' });
  m.api.decideAnalystRecommendation.mockResolvedValue({ recommendation_id: ROW.recommendation_id, status: 'ACCEPTED' });
});

describe('AnalystBrief (Phase 8)', () => {
  it('renders the structured brief: severity, confidence, sections', () => {
    render(<AnalystBrief report={REPORT} />);
    expect(screen.getByText('Fire in Engineering')).toBeTruthy();
    expect(screen.getAllByText('HIGH').length).toBeGreaterThan(0);
    expect(screen.getByText('82%')).toBeTruthy();
    expect(screen.getByText('What is happening')).toBeTruthy();
    expect(screen.getByText('Fire active in eng_faculty')).toBeTruthy();
    expect(screen.getByText('What changed')).toBeTruthy();
    expect(screen.getByText('Risk moved 12 → 44')).toBeTruthy();
    expect(screen.getByText('Emergency Gate (Gate B)')).toBeTruthy();
    expect(screen.getByText('where is safest?')).toBeTruthy();
    expect(screen.getByText('Prioritize evacuation')).toBeTruthy();
  });

  it('falls back to the Phase 5 narrative blocks without a situation', () => {
    render(<AnalystBrief report={{ ...REPORT, situation: undefined, evidence: undefined }} />);
    expect(screen.getByText('What happened')).toBeTruthy();
    expect(screen.getByText('legacy happened')).toBeTruthy();
    expect(screen.getByText('Recommended action')).toBeTruthy();
    expect(screen.queryByText('Fire in Engineering')).toBeNull();
  });

  it('posts an ACCEPT decision for a pending recommendation', async () => {
    const user = userEvent.setup();
    const onDecided = vi.fn();
    render(<AnalystBrief report={REPORT} decisions={[ROW]} canDecide onDecided={onDecided} />);
    await user.click(screen.getByRole('button', { name: /ACCEPT/ }));
    expect(m.api.decideAnalystRecommendation).toHaveBeenCalledWith('anl_test1_r1', 'ACCEPTED');
    await waitFor(() => expect(onDecided).toHaveBeenCalled());
  });

  it('hides decision buttons without the apply permission', () => {
    render(<AnalystBrief report={REPORT} decisions={[ROW]} canDecide={false} />);
    expect(screen.getByRole('button', { name: /ACCEPT/ })).toHaveProperty('disabled', true);
    expect(screen.getByRole('button', { name: /DISMISS/ })).toHaveProperty('disabled', true);
  });

  it('drops decision buttons once the row is decided', () => {
    render(<AnalystBrief report={REPORT} decisions={[{ ...ROW, status: 'ACCEPTED', decided_by: 'operator' }]} canDecide />);
    expect(screen.queryByRole('button', { name: /ACCEPT/ })).toBeNull();
    expect(screen.getByText('ACCEPTED')).toBeTruthy();
    expect(screen.getByText(/decided by operator/)).toBeTruthy();
  });
});

describe('EvidencePanel (Phase 8)', () => {
  it('lists evidence and round-trips the persisted detail on expand', async () => {
    const user = userEvent.setup();
    render(<EvidencePanel evidence={REPORT.evidence!} />);
    expect(screen.getByText('Evidence (1)')).toBeTruthy();
    expect(screen.getByText('Campus risk 44/100 (HIGH)')).toBeTruthy();
    await user.click(screen.getByText('Campus risk 44/100 (HIGH)'));
    expect(m.api.analystEvidence).toHaveBeenCalledWith('anl_test1:ev_1');
    await waitFor(() => expect(screen.getByText('persisted copy')).toBeTruthy());
  });

  it('shows an honest empty state', () => {
    render(<EvidencePanel evidence={[]} />);
    expect(screen.getByText(/No evidence collected/)).toBeTruthy();
  });
});
