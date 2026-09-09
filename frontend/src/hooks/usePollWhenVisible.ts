import { useEffect, useRef } from "react";

/** Call `tick` immediately, then on an interval while the tab is visible.
 *
 * `tick` is read from a ref so a new callback identity does not re-fetch.
 * Pass `restartKey` when a filter should start a new poll cycle right away.
 */
export function usePollWhenVisible(
  tick: () => void | Promise<void>,
  ms: number,
  enabled = true,
  restartKey?: unknown
) {
  const tickRef = useRef(tick);
  tickRef.current = tick;

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    let id: number | null = null;

    const run = () => {
      if (!cancelled) void tickRef.current();
    };

    const stop = () => {
      if (id != null) {
        window.clearInterval(id);
        id = null;
      }
    };

    const start = () => {
      if (id != null || document.hidden) return;
      id = window.setInterval(run, ms);
    };

    const onVis = () => {
      if (document.hidden) {
        stop();
        return;
      }
      run();
      start();
    };

    if (!document.hidden) {
      run();
      start();
    }
    document.addEventListener("visibilitychange", onVis);
    return () => {
      cancelled = true;
      stop();
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [ms, enabled, restartKey]);
}
