import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";

/** Fetch a JSON endpoint and re-poll it on an interval. Polling pauses while the tab is hidden. */
export function usePoll<T>(path: string | null, intervalMs = 3000) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const pathRef = useRef(path);
  pathRef.current = path;

  const refresh = useCallback(async () => {
    const p = pathRef.current;
    if (!p) return;
    try {
      const d = await api<T>(p);
      if (pathRef.current === p) { setData(d); setError(null); }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    refresh();
    if (!intervalMs) return;
    const id = setInterval(() => { if (!document.hidden) refresh(); }, intervalMs);
    return () => clearInterval(id);
  }, [path, intervalMs, refresh]);

  return { data, error, loading, refresh };
}
