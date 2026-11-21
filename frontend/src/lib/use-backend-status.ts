"use client";

import { useEffect, useState } from "react";

export type BackendStatus = "checking" | "waking" | "connected" | "offline";

// Written out in full so Next can inline it at build time.
const BASE_URL = (
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
).replace(/\/+$/, "");

const HEALTH_URL = `${BASE_URL}/api/health`;
const POLL_INTERVAL_MS = 10_000;
const OFFLINE_POLL_INTERVAL_MS = 3_000;
const TIMEOUT_MS = 3_000;
const WAKE_THRESHOLD_MS = 2_500;
const COLD_START_TIMEOUT_MS = 120_000;

// Never throws: every failure (network error, timeout, bad status, bad JSON,
// wrong payload) resolves to "offline".
async function probe(signal: AbortSignal): Promise<BackendStatus> {
  try {
    const response = await fetch(HEALTH_URL, { cache: "no-store", signal });
    if (!response.ok) return "offline";

    const data: unknown = await response.json();
    const isHealthy =
      typeof data === "object" &&
      data !== null &&
      "status" in data &&
      data.status === "ok";

    return isHealthy ? "connected" : "offline";
  } catch {
    return "offline";
  }
}

export function useBackendStatus() {
  const [status, setStatus] = useState<BackendStatus>("checking");

  const [latency, setLatency] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    let inFlight = false;
    let current: BackendStatus = "checking";
    let controller: AbortController | null = null;
    let timerId: number | undefined;
    let wakeTimerId: number | undefined;
    let initialProbe = true;

    function stopPolling(): void {
      if (timerId !== undefined) {
        window.clearTimeout(timerId);
        timerId = undefined;
      }
    }

    function scheduleNext(): void {
      stopPolling();
      if (cancelled || document.visibilityState !== "visible") return;
      timerId = window.setTimeout(() => {
        void check();
      }, current === "offline" ? OFFLINE_POLL_INTERVAL_MS : POLL_INTERVAL_MS);
    }

    async function check(): Promise<void> {
      if (inFlight) return;
      inFlight = true;

      const requestController = new AbortController();
      controller = requestController;
      if (initialProbe) {
        wakeTimerId = window.setTimeout(() => {
          if (!cancelled && !requestController.signal.aborted) {
            current = "waking";
            setStatus("waking");
          }
        }, WAKE_THRESHOLD_MS);
      }
      const timeoutId = window.setTimeout(
        () => requestController.abort(),
        initialProbe ? COLD_START_TIMEOUT_MS : TIMEOUT_MS,
      );

      const started = performance.now();
      const next = await probe(requestController.signal);

      window.clearTimeout(timeoutId);
      window.clearTimeout(wakeTimerId);
      wakeTimerId = undefined;
      inFlight = false;
      controller = null;

      // Only report real changes, never go back to "checking", and never
      // touch state after unmount.
      if (cancelled) return;
      // Hiding the tab cancels work, but should not mark a cold start offline.
      if (requestController.signal.aborted && document.visibilityState !== "visible") return;
      initialProbe = false;
      setLatency(next === "connected" ? Math.round(performance.now() - started) : null);
      if (next !== current) {
        current = next;
        setStatus(next);
      }
      scheduleNext();
    }

    function handleVisibilityChange(): void {
      if (document.visibilityState === "visible") {
        void check();
      } else {
        stopPolling();
        controller?.abort();
      }
    }

    void check();
    document.addEventListener("visibilitychange", handleVisibilityChange);
    window.addEventListener("online", check);
    window.addEventListener("focus", check);

    return () => {
      cancelled = true;
      stopPolling();
      window.clearTimeout(wakeTimerId);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      window.removeEventListener("online", check);
      window.removeEventListener("focus", check);
      controller?.abort();
    };
  }, []);

  return { status, latency };
}
