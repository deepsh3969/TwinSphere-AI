import type { SVGProps } from 'react';

type P = SVGProps<SVGSVGElement>;

const base = (props: P) => ({
  width: 16, height: 16, viewBox: '0 0 24 24', fill: 'none',
  stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const, ...props,
});

export const IconDashboard = (p: P) => (
  <svg {...base(p)}><rect x="3" y="3" width="7" height="9" rx="1" /><rect x="14" y="3" width="7" height="5" rx="1" /><rect x="14" y="12" width="7" height="9" rx="1" /><rect x="3" y="16" width="7" height="5" rx="1" /></svg>
);
export const IconCube = (p: P) => (
  <svg {...base(p)}><path d="M12 2 21 7v10l-9 5-9-5V7l9-5Z" /><path d="M3 7l9 5 9-5" /><path d="M12 12v10" /></svg>
);
export const IconPlay = (p: P) => (
  <svg {...base(p)}><polygon points="6 3 20 12 6 21 6 3" /></svg>
);
export const IconPause = (p: P) => (
  <svg {...base(p)}><rect x="6" y="4" width="4" height="16" rx="1" /><rect x="14" y="4" width="4" height="16" rx="1" /></svg>
);
export const IconBrain = (p: P) => (
  <svg {...base(p)}><path d="M12 5a3 3 0 0 0-3-3 3 3 0 0 0-3 3 3 3 0 0 0-2 3c0 1 .4 1.8 1 2.5A3 3 0 0 0 6 16a3 3 0 0 0 3 3 3 3 0 0 0 3-1.5V5Z" /><path d="M12 5a3 3 0 0 1 3-3 3 3 0 0 1 3 3 3 3 0 0 1 2 3c0 1-.4 1.8-1 2.5A3 3 0 0 1 18 16a3 3 0 0 1-3 3 3 3 0 0 1-3-1.5" /></svg>
);
export const IconChart = (p: P) => (
  <svg {...base(p)}><path d="M3 3v18h18" /><path d="M7 15l4-5 3 3 5-7" /></svg>
);
export const IconHistory = (p: P) => (
  <svg {...base(p)}><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></svg>
);
export const IconGear = (p: P) => (
  <svg {...base(p)}><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-1.8-.3 1.6 1.6 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1A1.6 1.6 0 0 0 9 19.4a1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0 .3-1.8 1.6 1.6 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1A1.6 1.6 0 0 0 4.6 9a1.6 1.6 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 1.8.3H9a1.6 1.6 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.6 1.6 0 0 0 1 1.5 1.6 1.6 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8V9a1.6 1.6 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1Z" /></svg>
);
export const IconLogout = (p: P) => (
  <svg {...base(p)}><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" /><polyline points="16 17 21 12 16 7" /><line x1="21" y1="12" x2="9" y2="12" /></svg>
);
export const IconAlert = (p: P) => (
  <svg {...base(p)}><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z" /><line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" /></svg>
);
export const IconCheck = (p: P) => (
  <svg {...base(p)}><polyline points="20 6 9 17 4 12" /></svg>
);
export const IconActivity = (p: P) => (
  <svg {...base(p)}><polyline points="22 12 18 12 15 21 9 3 6 12 2 12" /></svg>
);
export const IconFire = (p: P) => (
  <svg {...base(p)}><path d="M12 2s4 4 4 8a4 4 0 0 1-8 0c0-1.5.7-2.8 1.5-3.7C9 10 10 11 11 11c0-3 1-6 1-9Z" /><path d="M6.3 8.7A6 6 0 0 0 6 11a6 6 0 0 0 12 0c0-2-1-4-2.5-5.5" /></svg>
);
export const IconUsers = (p: P) => (
  <svg {...base(p)}><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /><path d="M23 21v-2a4 4 0 0 0-3-3.87" /><path d="M16 3.13a4 4 0 0 1 0 7.75" /></svg>
);
export const IconZap = (p: P) => (
  <svg {...base(p)}><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" /></svg>
);
export const IconRoad = (p: P) => (
  <svg {...base(p)}><path d="M4 22 8 2M16 2l4 20M12 4v3M12 11v3M12 18v3" /></svg>
);
export const IconThermo = (p: P) => (
  <svg {...base(p)}><path d="M14 14.76V3.5a2.5 2.5 0 0 0-5 0v11.26a4.5 4.5 0 1 0 5 0Z" /></svg>
);
export const IconTarget = (p: P) => (
  <svg {...base(p)}><circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="5" /><circle cx="12" cy="12" r="1.4" /></svg>
);
export const IconRefresh = (p: P) => (
  <svg {...base(p)}><polyline points="23 4 23 10 17 10" /><path d="M20.5 15a9 9 0 1 1-2.1-9.4L23 10" /></svg>
);
export const IconX = (p: P) => (
  <svg {...base(p)}><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
);
export const IconSpark = (p: P) => (
  <svg {...base(p)}><path d="M12 3v4M12 17v4M3 12h4M17 12h4M6.3 6.3l2.8 2.8M14.9 14.9l2.8 2.8M17.7 6.3l-2.8 2.8M9.1 14.9l-2.8 2.8" /></svg>
);
export const IconRocket = (p: P) => (
  <svg {...base(p)}><path d="M4.5 16.5c-1.5 1.3-2 5-2 5s3.7-.5 5-2c.7-.8.7-2 0-2.8a2 2 0 0 0-3 0Z" /><path d="M12 15l-3-3a22 22 0 0 1 2-3.9A12.9 12.9 0 0 1 22 2c0 2.7-.8 7.7-6 11a22 22 0 0 1-4 2Z" /><path d="M9 12H4s.5-2.8 2-4c1.7-1.3 5 0 5 0" /><path d="M12 15v5s2.8-.5 4-2c1.3-1.7 0-5 0-5" /></svg>
);
export const IconMenu = (p: P) => (
  <svg {...base(p)}><line x1="3" y1="6" x2="21" y2="6" /><line x1="3" y1="12" x2="21" y2="12" /><line x1="3" y1="18" x2="21" y2="18" /></svg>
);
export const IconSearch = (p: P) => (
  <svg {...base(p)}><circle cx="11" cy="11" r="7" /><line x1="21" y1="21" x2="16.65" y2="16.65" /></svg>
);
export const IconDownload = (p: P) => (
  <svg {...base(p)}><path d="M12 3v12" /><path d="M7 11l5 5 5-5" /><path d="M4 21h16" /></svg>
);
