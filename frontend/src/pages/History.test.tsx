import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import incidentsJson from '../testData/history_incidents.json';
import incidentDetailJson from '../testData/history_incident_detail.json';
import incidentReportJson from '../testData/history_incident_report.json';
import simulationsJson from '../testData/history_simulations.json';
import simDetailJson from '../testData/history_simulation_detail.json';
import compareJson from '../testData/history_sim_compare.json';
import History from './History';

const m = vi.hoisted(() => ({
  api: {
    historyIncidents: vi.fn(),
    historySimulations: vi.fn(),
    historyIncident: vi.fn(),
    incidentReport: vi.fn(),
    incidentExport: vi.fn(),
    historySimulation: vi.fn(),
    historySimEvents: vi.fn(),
    compareSimulations: vi.fn(),
    historyExport: vi.fn(),
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

const sims = simulationsJson;
const incs = incidentsJson;
const firstInc = incs.items[0];
const firstSim = sims.items[0];
const incDetail = incidentDetailJson;
const incReport = incidentReportJson;
const simDetail = simDetailJson;
const compare = compareJson;
const simIncidentId = (simDetail as unknown as { incidents: Array<{ id: string }> })
  .incidents[0]?.id;

function LocationProbe() {
  const loc = useLocation();
  return <div data-testid="loc">{`${loc.pathname}${loc.search}`}</div>;
}

function renderPage(initial = '/history') {
  return render(
    <MemoryRouter initialEntries={[initial]}>
      <LocationProbe />
      <Routes>
        <Route path="/history" element={<History />} />
        <Route path="/dashboard" element={<div>dashboard-probe</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  // jsdom does not implement blob URLs used by downloadCsv()
  URL.createObjectURL = vi.fn(() => 'blob:twinsphere');
  URL.revokeObjectURL = vi.fn();
  m.api.historySimulations.mockResolvedValue(sims);
  m.api.historyIncidents.mockResolvedValue(incs);
  m.api.historyIncident.mockResolvedValue(incDetail);
  m.api.incidentReport.mockResolvedValue(incReport);
  m.api.incidentExport.mockResolvedValue('id,code\n1,INC-TEST\n');
  m.api.historySimulation.mockResolvedValue(simDetail);
  m.api.compareSimulations.mockResolvedValue(compare);
  m.api.historyExport.mockResolvedValue('code,status\nSIM-C43325,COMPLETED\n');
});

describe('History §62 — simulations tab', () => {
  it('lists persisted runs with server-side pagination', async () => {
    renderPage();
    expect(await screen.findByTestId(`sim-row-${firstSim.id}`)).toBeInTheDocument();
    expect(screen.getByText(firstSim.code)).toBeInTheDocument();
    expect(m.api.historySimulations).toHaveBeenCalledWith(
      expect.objectContaining({ page: 1, page_size: 10 }),
    );
    expect(screen.getByText(new RegExp(`page 1 / ${sims.pages}`))).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('paginate-next'));
    await waitFor(() =>
      expect(m.api.historySimulations).toHaveBeenCalledWith(
        expect.objectContaining({ page: 2 }),
      ));
    expect(screen.getByTestId('loc').textContent).toContain('page=2');
  });

  it('filters by scenario through URL state', async () => {
    renderPage();
    await screen.findByTestId(`sim-row-${firstSim.id}`);
    fireEvent.click(screen.getByTestId('scenario-crowd'));
    expect(screen.getByTestId('loc').textContent).toContain('scenario=crowd');
    await waitFor(() =>
      expect(m.api.historySimulations).toHaveBeenCalledWith(
        expect.objectContaining({ scenario: 'crowd' }),
      ));
  });

  it('shows an honest empty state when no runs match', async () => {
    m.api.historySimulations.mockResolvedValue({
      ...sims, items: [], total: 0, page: 1, pages: 1,
    });
    renderPage();
    expect(await screen.findByTestId('empty-simulations')).toBeInTheDocument();
  });

  it('opens the simulation drawer with metrics, events and incident links', async () => {
    renderPage();
    await screen.findByTestId(`sim-row-${firstSim.id}`);
    const target = sims.items.find((s) => s.code === simDetail.simulation.code)!;
    fireEvent.click(screen.getByTestId(`sim-row-${target.id}`));
    expect(await screen.findByTestId('simulation-drawer')).toBeInTheDocument();
    await waitFor(() =>
      expect(m.api.historySimulation).toHaveBeenCalledWith(target.id));
    const drawer = within(screen.getByTestId('simulation-drawer'));
    expect(drawer.getByText(new RegExp(simDetail.simulation.code))).toBeInTheDocument();
    expect(drawer.getByText(/Fire spread to Ground Floor Lobby/)).toBeInTheDocument();
    expect(drawer.getByText(/SIMULATION: 3/)).toBeInTheDocument();
    expect(m.api.historyIncident).not.toHaveBeenCalled();
  });

  it('hands off to the dashboard replay with ?replay=<simId>', async () => {
    renderPage();
    await screen.findByTestId(`sim-row-${firstSim.id}`);
    fireEvent.click(screen.getByTestId(`replay-${firstSim.id}`));
    expect(screen.getByTestId('loc').textContent).toBe(
      `/dashboard?replay=${encodeURIComponent(firstSim.id)}`,
    );
    expect(screen.getByText('dashboard-probe')).toBeInTheDocument();
  });

  it('selects exactly two runs and fetches the comparison', async () => {
    renderPage();
    const [a, b] = sims.items;
    await screen.findByTestId(`sim-row-${a.id}`);
    fireEvent.click(screen.getByTestId(`sim-cmp-${a.id}`));
    fireEvent.click(screen.getByTestId(`sim-cmp-${b.id}`));
    expect(await screen.findByTestId('compare-panel')).toBeInTheDocument();
    await waitFor(() =>
      expect(m.api.compareSimulations).toHaveBeenCalledWith(a.id, b.id));
    const panel = screen.getByTestId('compare-panel');
    expect(panel).toHaveTextContent(compare.a.code);
    expect(panel).toHaveTextContent(compare.b.code);
    expect(panel.querySelectorAll('tbody tr').length).toBe(compare.rows.length);
    expect(m.api.compareSimulations.mock.calls.length).toBeGreaterThan(0);
  });

  it('exports the simulation list as CSV', async () => {
    renderPage();
    await screen.findByTestId(`sim-row-${firstSim.id}`);
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(() => undefined);
    fireEvent.click(screen.getByTestId('history-export'));
    await waitFor(() =>
      expect(m.api.historyExport).toHaveBeenCalledWith('simulations', { page_size: 1000 }));
    expect(click).toHaveBeenCalled();
  });
});

describe('History §62 — incidents tab', () => {
  it('switches tabs via URL state and paginates incidents', async () => {
    renderPage();
    await screen.findByTestId(`sim-row-${firstSim.id}`);
    fireEvent.click(screen.getByTestId('tab-incidents'));
    expect(await screen.findByTestId(`inc-row-${firstInc.id}`)).toBeInTheDocument();
    expect(screen.getByTestId('loc').textContent).toContain('tab=incidents');
    await waitFor(() =>
      expect(m.api.historyIncidents).toHaveBeenCalledWith(
        expect.objectContaining({ page: 1, page_size: 10 }),
      ));
  });

  it('applies severity/status/kind filters from the URL', async () => {
    renderPage('/history?tab=incidents');
    await screen.findByTestId(`inc-row-${firstInc.id}`);
    fireEvent.change(screen.getByTestId('filter-inc-severity'), {
      target: { value: 'HIGH' },
    });
    expect(screen.getByTestId('loc').textContent).toContain('severity=HIGH');
    await waitFor(() =>
      expect(m.api.historyIncidents).toHaveBeenCalledWith(
        expect.objectContaining({ severity: 'HIGH' }),
      ));
  });

  it('opens the incident drawer and generates the report', async () => {
    renderPage('/history?tab=incidents');
    await screen.findByTestId(`inc-row-${firstInc.id}`);
    fireEvent.click(screen.getByTestId(`inc-row-${firstInc.id}`));
    expect(await screen.findByTestId('incident-drawer')).toBeInTheDocument();
    await waitFor(() =>
      expect(m.api.historyIncident).toHaveBeenCalledWith(firstInc.id));
    const drawer = within(await screen.findByTestId('incident-drawer'));
    expect(await drawer.findByText(new RegExp(firstInc.code))).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('report-toggle'));
    const block = await screen.findByTestId('report-block');
    expect(m.api.incidentReport).toHaveBeenCalledWith(firstInc.id);
    expect(block).toHaveTextContent(incReport.report_type);
    expect(block).toHaveTextContent(incReport.executive_summary.slice(0, 60));
    expect(block).toHaveTextContent('Timeline categories');
  });

  it('exports one incident as CSV from the row and the drawer', async () => {
    renderPage('/history?tab=incidents');
    await screen.findByTestId(`inc-row-${firstInc.id}`);
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(() => undefined);

    fireEvent.click(screen.getByTestId(`inc-export-${firstInc.id}`));
    await waitFor(() =>
      expect(m.api.incidentExport).toHaveBeenCalledWith(firstInc.id, 'csv'));

    fireEvent.click(screen.getByTestId(`inc-row-${firstInc.id}`));
    await screen.findByTestId('incident-drawer');
    fireEvent.click(screen.getByTestId('incident-export'));
    await waitFor(() =>
      expect(m.api.incidentExport.mock.calls.length).toBe(2));
    expect(click).toHaveBeenCalled();
  });

  it('shows an honest empty state when no incidents match', async () => {
    m.api.historyIncidents.mockResolvedValue({
      ...incs, items: [], total: 0, page: 1, pages: 1,
    });
    renderPage('/history?tab=incidents');
    expect(await screen.findByTestId('empty-incidents')).toBeInTheDocument();
  });

  it('links a simulation run to its incidents in one URL write', async () => {
    expect(simIncidentId).toBeTruthy();
    renderPage();
    await screen.findByTestId(`sim-row-${firstSim.id}`);
    const target = sims.items.find((s) => s.code === simDetail.simulation.code)!;
    fireEvent.click(screen.getByTestId(`sim-row-${target.id}`));
    await waitFor(() => expect(m.api.historySimulation).toHaveBeenCalledWith(target.id));
    const chip = await screen.findByTestId(`sim-inc-${simIncidentId}`);
    fireEvent.click(chip);
    expect(screen.getByTestId('loc').textContent).toContain('tab=incidents');
    expect(screen.getByTestId('loc').textContent).toContain(`inc=${simIncidentId}`);
  });
});
