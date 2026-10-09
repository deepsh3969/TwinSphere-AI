import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import aiJson from '../testData/analytics_ai.json';
import buildingsJson from '../testData/analytics_buildings.json';
import energyJson from '../testData/analytics_energy.json';
import environmentJson from '../testData/analytics_environment.json';
import healthJson from '../testData/analytics_health.json';
import occupancyJson from '../testData/analytics_occupancy.json';
import overviewJson from '../testData/analytics_overview.json';
import riskJson from '../testData/analytics_risk.json';
import routesJson from '../testData/analytics_routes.json';
import sensorsJson from '../testData/analytics_sensors.json';
import incidentsJson from '../testData/history_incidents.json';
import simulationsJson from '../testData/history_simulations.json';
import { makeSnapshot } from '../testFixtures';
import { useTwinStore } from '../store/useTwinStore';
import Analytics from './Analytics';

const m = vi.hoisted(() => ({
  api: {
    analyticsOverview: vi.fn(),
    riskAnalytics: vi.fn(),
    occupancyAnalytics: vi.fn(),
    energyAnalytics: vi.fn(),
    environmentAnalytics: vi.fn(),
    sensorHealth: vi.fn(),
    sensorHealthDetail: vi.fn(),
    buildingsAnalytics: vi.fn(),
    compareBuildings: vi.fn(),
    routesAnalytics: vi.fn(),
    aiAnalytics: vi.fn(),
    campusHealth: vi.fn(),
    whatChanged: vi.fn(),
    exportAnalytics: vi.fn(),
    historyIncidents: vi.fn(),
    historySimulations: vi.fn(),
    register: vi.fn(),
    login: vi.fn(),
    health: vi.fn(),
    campus: vi.fn(),
    simulations: vi.fn(),
    realtimeStatus: vi.fn(),
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

function LocationProbe() {
  const loc = useLocation();
  return <div data-testid="loc">{`${loc.pathname}${loc.search}`}</div>;
}

function renderPage(initial = '/analytics') {
  return render(
    <MemoryRouter initialEntries={[initial]}>
      <LocationProbe />
      <Routes>
        <Route path="/analytics" element={<Analytics />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  URL.createObjectURL = vi.fn(() => 'blob:twinsphere');
  URL.revokeObjectURL = vi.fn();
  useTwinStore.setState({ snapshot: makeSnapshot() });
  m.api.analyticsOverview.mockResolvedValue(overviewJson);
  m.api.riskAnalytics.mockResolvedValue(riskJson);
  m.api.occupancyAnalytics.mockResolvedValue(occupancyJson);
  m.api.energyAnalytics.mockResolvedValue(energyJson);
  m.api.environmentAnalytics.mockResolvedValue(environmentJson);
  m.api.sensorHealth.mockResolvedValue(sensorsJson);
  m.api.buildingsAnalytics.mockResolvedValue(buildingsJson);
  m.api.routesAnalytics.mockResolvedValue(routesJson);
  m.api.aiAnalytics.mockResolvedValue(aiJson);
  m.api.campusHealth.mockResolvedValue(healthJson);
  m.api.historyIncidents.mockResolvedValue(incidentsJson);
  m.api.historySimulations.mockResolvedValue(simulationsJson);
  m.api.exportAnalytics.mockResolvedValue('range,value\n24H,1\n');
});

describe('Analytics §62 — window bundle', () => {
  it('renders KPIs, risk and health sections from the server bundle', async () => {
    renderPage();
    expect(await screen.findByTestId('section-window-overview')).toBeInTheDocument();
    expect(m.api.analyticsOverview).toHaveBeenCalledWith({ range: '24H' });
    expect(m.api.riskAnalytics).toHaveBeenCalledWith({ range: '24H' });
    expect(m.api.campusHealth).toHaveBeenCalledWith({ range: '24H' });

    const kpi = overviewJson.kpis[0];
    expect(
      within(screen.getByTestId('section-window-overview')).getByText(kpi.label),
    ).toBeInTheDocument();
    expect(screen.getByTestId('section-risk')).toBeInTheDocument();
    expect(screen.getByTestId('section-sensor-health')).toBeInTheDocument();
    expect(screen.getByText(/insufficient matched predictions|%\s*\(vs persisted actuals\)/))
      .toBeInTheDocument();
    expect(m.api.historyIncidents).toHaveBeenCalledWith(
      expect.objectContaining({ page_size: 50 }));
    expect(m.api.historySimulations).toHaveBeenCalledWith(
      expect.objectContaining({ page_size: 50 }));
  });

  it('shows the loading placeholder until the bundle resolves', async () => {
    let release: (value: typeof overviewJson) => void = () => undefined;
    const gate = new Promise<typeof overviewJson>((resolve) => { release = resolve; });
    m.api.analyticsOverview.mockReturnValue(gate);
    renderPage();
    expect(screen.getByTestId('analytics-loading')).toBeInTheDocument();
    release(overviewJson);
    await waitFor(() =>
      expect(screen.getByTestId('section-window-overview')).toBeInTheDocument());
  });

  it('surfaces an honest error with retry when the bundle fails', async () => {
    m.api.analyticsOverview.mockRejectedValue(new Error('window unavailable'));
    renderPage();
    expect(await screen.findByText('Failed to load analytics')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
  });
});

describe('Analytics §62 — URL-persisted filters', () => {
  it('switches the window range and refetches', async () => {
    renderPage();
    await screen.findByTestId('section-window-overview');
    fireEvent.click(screen.getByTestId('range-1H'));
    expect(screen.getByTestId('loc').textContent).toContain('range=1H');
    await waitFor(() =>
      expect(m.api.analyticsOverview).toHaveBeenCalledWith({ range: '1H' }));
  });

  it('scopes risk/occupancy to a building through the URL', async () => {
    renderPage();
    await screen.findByTestId('section-window-overview');
    const buildingId = makeSnapshot().buildings[0].id;
    fireEvent.change(screen.getByTestId('filter-building'), {
      target: { value: buildingId },
    });
    expect(screen.getByTestId('loc').textContent).toContain(`building=${buildingId}`);
    await waitFor(() =>
      expect(m.api.riskAnalytics).toHaveBeenCalledWith(
        { range: '24H', building_id: buildingId }));
  });

  it('applies incident filters to the history queries', async () => {
    renderPage();
    await screen.findByTestId('section-window-overview');
    fireEvent.change(screen.getByTestId('filter-status'), {
      target: { value: 'RESOLVED' },
    });
    expect(screen.getByTestId('loc').textContent).toContain('status=RESOLVED');
    await waitFor(() =>
      expect(m.api.historyIncidents).toHaveBeenCalledWith(
        expect.objectContaining({ status: 'RESOLVED', page_size: 50 })));
  });

  it('filters simulations by scenario', async () => {
    renderPage();
    await screen.findByTestId('section-window-overview');
    fireEvent.change(screen.getByTestId('filter-scenario'), {
      target: { value: 'fire' },
    });
    expect(screen.getByTestId('loc').textContent).toContain('scenario=fire');
    await waitFor(() =>
      expect(m.api.historySimulations).toHaveBeenCalledWith(
        expect.objectContaining({ scenario: 'fire' })));
  });

  it('offers a custom range with start/end inputs', async () => {
    renderPage();
    await screen.findByTestId('section-window-overview');
    fireEvent.click(screen.getByTestId('range-CUSTOM'));
    expect(screen.getByTestId('loc').textContent).toContain('range=CUSTOM');
    expect(screen.getByLabelText('Window start')).toBeInTheDocument();
    expect(screen.getByLabelText('Window end')).toBeInTheDocument();
    await waitFor(() =>
      expect(m.api.analyticsOverview).toHaveBeenCalledWith(
        { range: 'CUSTOM', start: '', end: '' }));
  });

  it('resets the filter set while keeping the chosen window', async () => {
    renderPage('/analytics?range=7D&building=b-cs&kind=FIRE');
    await screen.findByTestId('section-window-overview');
    expect(screen.getByTestId('filter-building')).toHaveValue('b-cs');
    fireEvent.click(screen.getByRole('button', { name: /reset filters/i }));
    expect(screen.getByTestId('loc').textContent).toBe('/analytics?range=7D');
    await waitFor(() =>
      expect(m.api.riskAnalytics).toHaveBeenCalledWith({ range: '7D' }));
  });
});

describe('Analytics §62 — CSV export', () => {
  it('exports the selected dataset for the active window', async () => {
    renderPage();
    await screen.findByTestId('section-window-overview');
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(() => undefined);

    fireEvent.change(screen.getByLabelText('Export dataset'), {
      target: { value: 'risk' },
    });
    fireEvent.click(screen.getByTestId('export-csv'));

    await waitFor(() =>
      expect(m.api.exportAnalytics).toHaveBeenCalledWith('risk', { range: '24H' }));
    expect(click).toHaveBeenCalled();
    expect(URL.createObjectURL).toHaveBeenCalled();
  });

  it('keeps the export on the chosen window', async () => {
    renderPage();
    await screen.findByTestId('section-window-overview');
    fireEvent.click(screen.getByTestId('range-6H'));
    await waitFor(() =>
      expect(m.api.analyticsOverview).toHaveBeenCalledWith({ range: '6H' }));
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
    fireEvent.click(screen.getByTestId('export-csv'));
    await waitFor(() =>
      expect(m.api.exportAnalytics).toHaveBeenCalledWith('summary', { range: '6H' }));
  });
});
