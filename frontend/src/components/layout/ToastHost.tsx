import { AnimatePresence, motion } from 'framer-motion';
import { useTwinStore } from '../../store/useTwinStore';
import { IconAlert, IconCheck, IconX } from '../Icons';

const LEVEL_STYLE: Record<string, string> = {
  info: 'border-blue-700 bg-blue-950/95 text-blue-100',
  success: 'border-emerald-700 bg-emerald-950/95 text-emerald-100',
  warn: 'border-amber-700 bg-amber-950/95 text-amber-100',
  error: 'border-red-700 bg-red-950/95 text-red-100',
};

export default function ToastHost() {
  const toast = useTwinStore((s) => s.toast);
  const dismiss = useTwinStore((s) => s.dismissToast);

  return (
    <div className="fixed bottom-5 left-5 z-50 flex flex-col gap-2 max-w-[380px] pointer-events-none">
      <AnimatePresence>
        {toast && (
          <motion.div
            key={toast.id}
            initial={{ opacity: 0, y: 16, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 8 }}
            className={`pointer-events-auto rounded-lg border px-3.5 py-2.5 shadow-xl backdrop-blur ${LEVEL_STYLE[toast.level] ?? LEVEL_STYLE.info}`}
          >
            <div className="flex items-start gap-2.5">
              <span className="mt-0.5 shrink-0">
                {toast.level === 'error' || toast.level === 'warn'
                  ? <IconAlert width={15} height={15} />
                  : <IconCheck width={15} height={15} />}
              </span>
              <div className="min-w-0">
                <div className="text-[11px] font-bold tracking-wider uppercase">{toast.title}</div>
                <div className="text-[12.5px] leading-snug opacity-95">{toast.message}</div>
              </div>
              <button className="ml-auto opacity-70 hover:opacity-100" onClick={dismiss} aria-label="Dismiss">
                <IconX width={13} height={13} />
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
