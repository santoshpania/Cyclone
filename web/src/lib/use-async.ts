"use client";

import { useCallback, useEffect, useEffectEvent, useState, type DependencyList } from "react";

export type AsyncState<T> = { data: T | undefined; error: Error | null; loading: boolean; reload: () => void };

type Settled<T> = { deps: readonly unknown[]; data: T | undefined; error: Error | null };

function sameDeps(a: readonly unknown[], b: readonly unknown[]): boolean {
  return a.length === b.length && a.every((v, i) => Object.is(v, b[i]));
}

/** Minimal data loader: runs `fn` when deps change and ignores stale responses.
 * `loading` is derived (settled deps ≠ current deps), so no state is set during the effect. */
export function useAsync<T>(fn: () => Promise<T>, deps: DependencyList): AsyncState<T> {
  const [tick, setTick] = useState(0);
  const key = [...deps, tick];
  const [settled, setSettled] = useState<Settled<T>>({ deps: [Symbol("initial")], data: undefined, error: null });
  const run = useEffectEvent(fn);

  useEffect(() => {
    let cancelled = false;
    run().then(
      (data) => !cancelled && setSettled({ deps: key, data, error: null }),
      (e: unknown) =>
        !cancelled &&
        setSettled((prev) => ({ deps: key, data: prev.data, error: e instanceof Error ? e : new Error(String(e)) })),
    );
    return () => {
      cancelled = true;
    };
    // `key` is rebuilt every render from deps + tick; depend on its parts.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, key);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data: settled.data, error: settled.error, loading: !sameDeps(settled.deps, key), reload };
}
