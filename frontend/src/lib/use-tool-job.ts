"use client";

import { useCallback, useEffect, useReducer, useRef } from "react";
import { toApiError, type ApiError } from "@/lib/api";

export type JobStatus =
  | "idle"
  | "ready"
  | "uploading"
  | "processing"
  | "done"
  | "error";

export type JobCallbacks = {
  onProgress: (percent: number) => void;
  onUploadComplete: () => void;
};

export type JobRun<R> = {
  promise: Promise<R>;
  abort: () => void;
};

// Starts one job for one file. The hook knows nothing about what it does.
export type JobRunner<R> = (file: File, callbacks: JobCallbacks) => JobRun<R>;

type State<R> = {
  status: JobStatus;
  file: File | null;
  progress: number;
  result: R | null;
  error: ApiError | null;
};

type Action<R> =
  | { type: "select"; file: File }
  | { type: "clear" }
  | { type: "reset" }
  | { type: "start" }
  | { type: "progress"; percent: number }
  | { type: "uploaded" }
  | { type: "succeed"; result: R }
  | { type: "fail"; error: ApiError }
  | { type: "cancel" };

const INITIAL_STATE: State<never> = {
  status: "idle",
  file: null,
  progress: 0,
  result: null,
  error: null,
};

function isBusy(status: JobStatus): boolean {
  return status === "uploading" || status === "processing";
}

function reducer<R>(state: State<R>, action: Action<R>): State<R> {
  switch (action.type) {
    case "select":
      if (isBusy(state.status)) return state;
      return {
        status: "ready",
        file: action.file,
        progress: 0,
        result: null,
        error: null,
      };
    case "clear":
    case "reset":
      if (isBusy(state.status)) return state;
      return INITIAL_STATE;
    case "start":
      if (
        state.file === null ||
        (state.status !== "ready" && state.status !== "error")
      ) {
        return state;
      }
      return {
        ...state,
        status: "uploading",
        progress: 0,
        result: null,
        error: null,
      };
    case "progress":
      if (state.status !== "uploading") return state;
      return {
        ...state,
        progress: Math.min(100, Math.max(0, action.percent)),
      };
    case "uploaded":
      if (state.status !== "uploading") return state;
      return { ...state, status: "processing", progress: 100 };
    case "succeed":
      if (!isBusy(state.status)) return state;
      return {
        ...state,
        status: "done",
        progress: 100,
        result: action.result,
        error: null,
      };
    case "fail":
      if (!isBusy(state.status)) return state;
      return {
        ...state,
        status: "error",
        progress: 0,
        result: null,
        error: action.error,
      };
    case "cancel":
      if (state.status !== "uploading") return state;
      return { ...state, status: "ready", progress: 0 };
  }
}

// One in-flight run. Mutated only from event handlers and callbacks.
type ActiveRun = {
  abort: () => void;
  uploading: boolean;
};

export type ToolJob<R> = {
  file: File | null;
  status: JobStatus;
  progress: number;
  result: R | null;
  error: ApiError | null;
  select: (file: File) => void;
  clear: () => void;
  start: (runner: JobRunner<R>) => void;
  cancel: () => void;
  reset: () => void;
};

export function useToolJob<R>(): ToolJob<R> {
  const [state, dispatch] = useReducer<State<R>, [Action<R>]>(
    reducer,
    INITIAL_STATE,
  );
  const activeRef = useRef<ActiveRun | null>(null);

  // Abort on unmount so nothing updates state afterwards.
  useEffect(() => {
    return () => {
      const run = activeRef.current;
      activeRef.current = null;
      run?.abort();
    };
  }, []);

  const select = useCallback((file: File) => {
    if (activeRef.current) return;
    dispatch({ type: "select", file });
  }, []);

  const clear = useCallback(() => {
    if (activeRef.current) return;
    dispatch({ type: "clear" });
  }, []);

  const reset = useCallback(() => {
    if (activeRef.current) return;
    dispatch({ type: "reset" });
  }, []);

  const start = useCallback(
    (runner: JobRunner<R>) => {
      const file = state.file;
      if (!file || activeRef.current) return;
      if (state.status !== "ready" && state.status !== "error") return;

      const run: ActiveRun = { abort: () => {}, uploading: true };
      activeRef.current = run;
      dispatch({ type: "start" });

      let handle: JobRun<R>;
      try {
        handle = runner(file, {
          onProgress: (percent) => {
            if (activeRef.current === run) {
              dispatch({ type: "progress", percent });
            }
          },
          onUploadComplete: () => {
            if (activeRef.current === run) {
              run.uploading = false;
              dispatch({ type: "uploaded" });
            }
          },
        });
      } catch (error: unknown) {
        activeRef.current = null;
        dispatch({ type: "fail", error: toApiError(error) });
        return;
      }

      run.abort = handle.abort;
      handle.promise.then(
        (result) => {
          if (activeRef.current !== run) return;
          activeRef.current = null;
          dispatch({ type: "succeed", result });
        },
        (error: unknown) => {
          if (activeRef.current !== run) return;
          activeRef.current = null;
          dispatch({ type: "fail", error: toApiError(error) });
        },
      );
    },
    [state.file, state.status],
  );

  // Only while the file is still being sent. Once the server is working,
  // aborting would just orphan the job, so this does nothing.
  const cancel = useCallback(() => {
    const run = activeRef.current;
    if (!run || !run.uploading) return;
    activeRef.current = null;
    run.abort();
    dispatch({ type: "cancel" });
  }, []);

  return {
    file: state.file,
    status: state.status,
    progress: state.progress,
    result: state.result,
    error: state.error,
    select,
    clear,
    start,
    cancel,
    reset,
  };
}