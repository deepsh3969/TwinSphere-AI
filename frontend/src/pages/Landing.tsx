import { Link, Navigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { useTwinStore } from '../store/useTwinStore';
import { IconBrain, IconChart, IconCube, IconPlay, IconRocket, IconSpark } from '../components/Icons';

const FEATURES = [
  { icon: IconCube, title: 'Live 3D Digital Twin', text: 'Interactive campus replica driven by backend state — buildings, zones, roads, sensors and routes.' },
  { icon: IconSpark, title: 'Predictive AI', text: 'Anomaly detection, occupancy & energy forecasting with honest, measured confidence.' },
  { icon: IconPlay, title: 'What-If Simulation', text: 'Fire, crowd surge, power failure, road closure and heat events — start, pause, recover.' },
  { icon: IconBrain, title: 'Decision Support', text: 'Deterministic risk scoring + A* evacuation routing, explained by an AI analyst layer.' },
  { icon: IconChart, title: 'Analytics & History', text: 'Time-series analytics across 1H–30D windows with full simulation history.' },
  { icon: IconRocket, title: 'Guided Demo Mode', text: 'A scripted end-to-end presentation flow with one-click reset.' },
];

const FLOW = ['Sensors', 'Twin State', 'AI Engine', 'Simulation', 'Optimization', '3D View', 'Operator', 'Recovery'];

export default function Landing() {
  const token = useTwinStore((s) => s.token);
  if (token) return <Navigate to="/dashboard" replace />;

  return (
    <div className="h-screen overflow-y-auto bg-ink-950">
      <header className="border-b border-line/70 backdrop-blur sticky top-0 z-20 bg-ink-950/85">
        <div className="max-w-6xl mx-auto px-5 h-14 flex items-center gap-3">
          <div className="w-7 h-7 rounded-md bg-gradient-to-br from-brand-500 to-aqua-400 flex items-center justify-center text-[13px] font-black text-ink-950">TS</div>
          <span className="font-bold tracking-wide text-[14px]">TWINSPHERE AI</span>
          <span className="chip border-line-strong bg-ink-800 text-mist-300 hidden sm:inline">SIMULATION ENVIRONMENT</span>
          <div className="flex-1" />
          <Link to="/login" className="btn btn-primary">Sign in</Link>
        </div>
      </header>

      <section className="relative overflow-hidden">
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top,rgba(37,99,235,0.16),transparent_60%)]" />
        <div className="max-w-6xl mx-auto px-5 py-16 lg:py-24 relative">
          <motion.div initial={{ opacity: 0, y: 18 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }}>
            <div className="chip border-brand-500/60 bg-brand-950/50 text-brand-300 mb-5">
              AI-POWERED SMART CAMPUS DIGITAL TWIN
            </div>
            <h1 className="text-4xl lg:text-6xl font-black leading-[1.05] tracking-tight max-w-3xl">
              Simulate the Campus.<br />
              <span className="text-brand-400">Predict the Risk.</span><br />
              Optimize the Response.
            </h1>
            <p className="mt-6 text-mist-300 text-[15.5px] leading-relaxed max-w-2xl">
              TwinSphere AI is a live digital twin of a university campus — not a static dashboard.
              Telemetry flows through a sensor engine into a central twin state, through risk,
              prediction and optimization engines, into a 3D scene you can act on. Every control
              changes the twin. Every result is derived from real computation on simulated data.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link to="/login" className="btn btn-primary !text-[13.5px] !px-5 !py-3">
                <IconRocket width={15} height={15} /> Launch Platform
              </Link>
              <Link to="/login" className="btn !text-[13.5px] !px-5 !py-3">
                <IconPlay width={14} height={14} /> View Demo Flow
              </Link>
            </div>
          </motion.div>

          <div className="mt-14 panel rounded-xl p-4 overflow-x-auto">
            <div className="label-cap mb-3">Architecture — data to decision</div>
            <div className="flex items-center gap-2 min-w-max">
              {FLOW.map((f, i) => (
                <div key={f} className="flex items-center gap-2">
                  <div className="px-3 py-2 rounded-md border border-line-strong bg-ink-800 text-[12px] font-semibold whitespace-nowrap">
                    {f}
                  </div>
                  {i < FLOW.length - 1 && <span className="text-brand-400 text-lg">→</span>}
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section className="max-w-6xl mx-auto px-5 pb-16">
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {FEATURES.map((f, i) => (
            <motion.div
              key={f.title}
              initial={{ opacity: 0, y: 14 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ delay: i * 0.05 }}
              className="panel rounded-xl p-5"
            >
              <f.icon width={20} height={20} className="text-brand-400 mb-3" />
              <h3 className="font-bold text-[14.5px] mb-1.5">{f.title}</h3>
              <p className="text-[13px] text-mist-300 leading-relaxed">{f.text}</p>
            </motion.div>
          ))}
        </div>

        <div className="mt-8 rounded-xl border border-amber-800/70 bg-amber-950/30 p-4 text-[12.5px] text-amber-200 leading-relaxed">
          <b>Honesty note:</b> all sensor values in this platform are produced by a deterministic
          simulation engine labelled <b>SIMULATED DATA</b>. The architecture is designed so real IoT
          streams can replace the simulator without changing the AI, optimization or visualization layers.
        </div>

        <footer className="mt-10 pt-6 border-t border-line text-[12px] text-mist-500 flex flex-wrap gap-4 justify-between">
          <span>TwinSphere AI — Smart Campus Digital Twin &amp; Simulation Platform</span>
          <span>React · FastAPI · PostgreSQL/SQLite · Three.js · Scikit-learn</span>
        </footer>
      </section>
    </div>
  );
}
