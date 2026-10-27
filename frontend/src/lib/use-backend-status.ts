"use client";

import { useEffect, useState } from "react";

export type BackendStatus = "checking" | "connected" | "offline";

// Written out in full so Next can inline it at build time.
const BASE_URL = (
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
).replace(/\/+$/, "");

const HEALTH_URL = `${BASE_URL}/api/health`;
const POLL_INTERVAL_MS = 10_000;
const TIMEOUT_MS = 3_000;

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

export function useBackendStatus(): BackendStatus {
  const [status, setStatus] = useState<BackendStatus>("checking");

  useEffect(() => {
    let cancelled = false;
    let inFlight = false;
    let current: BackendStatus = "checking";
    let controller: AbortController | null = null;
    let intervalId: number | undefined;

    async function check(): Promise<void> {
      if (inFlight) return;
      inFlight = true;

      const requestController = new AbortController();
      controller = requestController;
      const timeoutId = window.setTimeout(
        () => requestController.abort(),
        TIMEOUT_MS,
      );

      const next = await probe(requestController.signal);

      window.clearTimeout(timeoutId);
      inFlight = false;
      controller = null;

      // Only report real changes, never go back to "checking", and never
      // touch state after unmount.
      if (cancelled || next === current) return;
      current = next;
      setStatus(next);
    }

    function stopPolling(): void {
      if (intervalId !== undefined) {
        window.clearInterval(intervalId);
        intervalId = undefined;
      }
    }

    function startPolling(): void {
      stopPolling();
      intervalId = window.setInterval(() => {
        void check();
      }, POLL_INTERVAL_MS);
    }

    function handleVisibilityChange(): void {
      if (document.visibilityState === "visible") {
        void check();
        startPolling();
      } else {
        stopPolling();
      }
    }

    void check();
    if (document.visibilityState === "visible") {
      startPolling();
    }
    document.addEventListener("visibilitychange", handleVisibilityChange);

    return () => {
      cancelled = true;
      stopPolling();
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      controller?.abort();
    };
  }, []);

  return status;
}