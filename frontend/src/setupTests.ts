import '@testing-library/jest-dom/vitest';

// jsdom does not implement ResizeObserver; recharts' ResponsiveContainer
// requires it, otherwise the sensor history chart crashes tests.
if (!('ResizeObserver' in globalThis)) {
  class ResizeObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  (globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver = ResizeObserverStub;
}
