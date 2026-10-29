"use client";

import { useCallback, useEffect, useReducer, useRef } from "react";
import { toApiError, type ApiError } from "@/lib/api";
import type { JobCallbacks, JobRun, JobStatus } from "@/lib/use-tool-job";

export type FileEntry = {
  id: string;
  file: File;
  // Object URL for the thumbnail. Created in add(), revoked when the entry
  // leaves the list and when the hook unmounts.
  previewUrl: string;
};

export type AddResult = {
  added: number;
  skipped: number;
};

// Starts one job for an ordered list of files. The hook knows nothing about
// what it does.
export type MultiJobRunner<R> = (
  files: File[],
  callbacks: JobCallbacks,
) => JobRun<R>;

type State<R> = {
  status: JobStatus;
  entries: FileEntry[];
  progress: number;
  result: R | null;
  error: ApiError | null;
};

type Action<R> =
  | { type: "add"; entries: FileEntry[]; max: number }
  | { type: "remove"; id: string }
  | { type: "move"; id: string; delta: -1 | 1 }
  | { type: "clear" }
  | { type: "start" }
  | { type: "progress"; percent: number }
  | { type: "uploaded" }
  | { type: "succeed"; result: R }
  | { type: "fail"; error: ApiError }
  | { type: "cancel" };

const INITIAL_STATE: State<never> = {
  status: "idle",
  entries: [],
  progress: 0,
  result: null,
  error: null,
};

function isBusy(status: JobStatus): boolean {
  return status === "uploading" || status === "processing";
}

// The list can only change while nothing is running and no result is showing.
function isEditable(status: JobStatus): boolean {
  return !isBusy(status) && status !== "done";
}

function reducer<R>(state: State<R>, action: Action<R>): State<R> {
  switch (action.type) {
    case "add": {
      if (!isEditable(state.status)) return state;
      const room = Math.max(0, action.max - state.entries.length);
      const added = action.entries.slice(0, room);
      if (added.length === 0) return state;
      return {
        status: "ready",
        entries: [...state.entries, ...added],
        progress: 0,
        result: null,
        error: null,
      };
    }
    case "remove": {
      if (!isEditable(state.status)) return state;
      const entries = state.entries.filter((entry) => entry.id !== action.id);
      if (entries.length === state.entries.length) return state;
      if (entries.length === 0) return INITIAL_STATE;
      return { status: "ready", entries, progress: 0, result: null, error: null };
    }
    case "move": {
      if (!isEditable(state.status)) return state;
      const from = state.entries.findIndex((entry) => entry.id === action.id);
      const to = from + action.delta;
      if (from < 0 || to < 0 || to >= state.entries.length) return state;
      const entries = [...state.entries];
      const [moved] = entries.splice(from, 1);
      if (!moved) return state;
      entries.splice(to, 0, moved);
      return { ...state, entries };
    }
    case "clear":
      if (isBusy(state.status)) return state;
      return INITIAL_STATE;
    case "start":
      if (
        state.entries.length === 0 ||
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

export type MultiFileJob<R> = {
  entries: readonly FileEntry[];
  status: JobStatus;
  progress: number;
  result: R | null;
  error: ApiError | null;
  add: (files: readonly File[]) => AddResult;
  remove: (id: string) => void;
  move: (id: string, delta: -1 | 1) => void;
  // Empties the list and returns to idle. Ignored while a job is running.
  clear: () => void;
  start: (runner: MultiJobRunner<R>) => void;
  cancel: () => void;
};

export function useMultiFileJob<R>(maxFiles: number): MultiFileJob<R> {
  const [state, dispatch] = useReducer<State<R>, [Action<R>]>(
    reducer,
    INITIAL_STATE,
  );
  const activeRef = useRef<ActiveRun | null>(null);
  const nextIdRef = useRef(0);
  const entriesRef = useRef<FileEntry[]>([]);

  // Lets the unmount cleanup see the last committed list.
  useEffect(() => {
    entriesRef.current = state.entries;
  }, [state.entries]);

  // Abort on unmount so nothing updates state afterwards, and free the
  // thumbnail URLs.
  useEffect(() => {
    return () => {
      const run = activeRef.current;
      activeRef.current = null;
      run?.abort();
      for (const entry of entriesRef.current) {
        URL.revokeObjectURL(entry.previewUrl);
      }
    };
  }, []);

  const add = useCallback(
    (files: readonly File[]): AddResult => {
      const editable = isEditable(state.status) && !activeRef.current;
      const room = editable ? Math.max(0, maxFiles - state.entries.length) : 0;
      const taken = files.slice(0, room);
      if (taken.length === 0) return { added: 0, skipped: files.length };

      const entries = taken.map((file): FileEntry => {
        nextIdRef.current += 1;
        return {
          id: `file-${nextIdRef.current}`,
          file,
          previewUrl: URL.createObjectURL(file),
        };
      });
      dispatch({ type: "add", entries, max: maxFiles });
      return { added: taken.length, skipped: files.length - taken.length };
    },
    [maxFiles, state.entries.length, state.status],
  );

  const remove = useCallback(
    (id: string) => {
      if (activeRef.current) return;
      const entry = state.entries.find((item) => item.id === id);
      if (!entry) return;
      URL.revokeObjectURL(entry.previewUrl);
      dispatch({ type: "remove", id });
    },
    [state.entries],
  );

  const move = useCallback((id: string, delta: -1 | 1) => {
    if (activeRef.current) return;
    dispatch({ type: "move", id, delta });
  }, []);

  const clear = useCallback(() => {
    if (activeRef.current) return;
    for (const entry of state.entries) {
      URL.revokeObjectURL(entry.previewUrl);
    }
    dispatch({ type: "clear" });
  }, [state.entries]);

  const start = useCallback(
    (runner: MultiJobRunner<R>) => {
      if (state.entries.length === 0 || activeRef.current) return;
      if (state.status !== "ready" && state.status !== "error") return;
      const files = state.entries.map((entry) => entry.file);

      const run: ActiveRun = { abort: () => {}, uploading: true };
      activeRef.current = run;
      dispatch({ type: "start" });

      let handle: JobRun<R>;
      try {
        handle = runner(files, {
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
    [state.entries, state.status],
  );

  // Only while the files are still being sent. Once the server is working,
  // aborting would just orphan the job, so this does nothing.
  const cancel = useCallback(() => {
    const run = activeRef.current;
    if (!run || !run.uploading) return;
    activeRef.current = null;
    run.abort();
    dispatch({ type: "cancel" });
  }, []);

  return {
    entries: state.entries,
    status: state.status,
    progress: state.progress,
    result: state.result,
    error: state.error,
    add,
    remove,
    move,
    clear,
    start,
    cancel,
  };
}