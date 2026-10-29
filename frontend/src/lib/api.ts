// Written out in full so Next can inline it at build time.
export const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
).replace(/\/+$/, "");

export const ABORTED_CODE = "aborted";
export const NETWORK_ERROR_CODE = "network_error";

const UNEXPECTED_CODE = "unexpected_response";
const UNEXPECTED_MESSAGE =
  "Something went wrong on the server. Please try again.";
const NETWORK_MESSAGE =
  "Can't reach the pdf-studio server. Check that the backend is running on this machine, then try again.";

export type Level = "light" | "balanced" | "strong";

export type CompressResult = {
  job_id: string;
  original_name: string;
  original_size: number;
  compressed_size: number;
  saved_bytes: number;
  saved_percent: number;
  already_optimized: boolean;
  level: Level;
  download_url: string;
};

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(code: string, message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
  }
}

export type UploadCallbacks = {
  // Real upload progress, 0-100.
  onProgress?: (percent: number) => void;
  // Fired once when every byte has been sent and the server is working.
  onUploadComplete?: () => void;
};

export type UploadHandle<T> = {
  promise: Promise<T>;
  abort: () => void;
};

export function isAbortError(error: unknown): boolean {
  return error instanceof ApiError && error.code === ABORTED_CODE;
}

// Turns anything thrown into an ApiError with a message safe to show.
export function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error;
  return new ApiError(UNEXPECTED_CODE, UNEXPECTED_MESSAGE, 0);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isLevel(value: unknown): value is Level {
  return value === "light" || value === "balanced" || value === "strong";
}

function parseJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return undefined;
  }
}

// Contract errors look like {"error": {"code", "message"}}. Anything else
// (for example FastAPI's own {"detail": ...} on a 405) becomes a generic error.
function errorFromBody(data: unknown, status: number): ApiError {
  if (isRecord(data)) {
    const inner = data.error;
    if (isRecord(inner)) {
      const { code, message } = inner;
      if (typeof code === "string" && typeof message === "string") {
        return new ApiError(code, message, status);
      }
    }
  }
  return new ApiError(UNEXPECTED_CODE, UNEXPECTED_MESSAGE, status);
}

function parseCompressResult(data: unknown): CompressResult | null {
  if (!isRecord(data)) return null;
  const {
    job_id,
    original_name,
    original_size,
    compressed_size,
    saved_bytes,
    saved_percent,
    already_optimized,
    level,
    download_url,
  } = data;

  if (
    typeof job_id !== "string" ||
    typeof original_name !== "string" ||
    typeof original_size !== "number" ||
    typeof compressed_size !== "number" ||
    typeof saved_bytes !== "number" ||
    typeof saved_percent !== "number" ||
    typeof already_optimized !== "boolean" ||
    !isLevel(level) ||
    typeof download_url !== "string"
  ) {
    return null;
  }

  return {
    job_id,
    original_name,
    original_size,
    compressed_size,
    saved_bytes,
    saved_percent,
    already_optimized,
    level,
    download_url,
  };
}

// Generic multipart POST. fetch cannot report upload progress, so this uses
// XMLHttpRequest. `parse` validates the success body and returns null when it
// does not match, which becomes a generic error instead of a crash.
export function postMultipart<T>(
  path: string,
  body: FormData,
  parse: (data: unknown) => T | null,
  callbacks: UploadCallbacks = {},
): UploadHandle<T> {
  const xhr = new XMLHttpRequest();

  const promise = new Promise<T>((resolve, reject) => {
    xhr.open("POST", `${API_BASE_URL}${path}`);

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && event.total > 0) {
        const percent = Math.round((event.loaded / event.total) * 100);
        callbacks.onProgress?.(Math.min(100, percent));
      }
    };

    xhr.upload.onload = () => {
      callbacks.onProgress?.(100);
      callbacks.onUploadComplete?.();
    };

    xhr.onload = () => {
      const data = parseJson(xhr.responseText);
      if (xhr.status >= 200 && xhr.status < 300) {
        const parsed = parse(data);
        if (parsed === null) {
          reject(new ApiError(UNEXPECTED_CODE, UNEXPECTED_MESSAGE, xhr.status));
        } else {
          resolve(parsed);
        }
        return;
      }
      reject(errorFromBody(data, xhr.status));
    };

    xhr.onerror = () => {
      reject(new ApiError(NETWORK_ERROR_CODE, NETWORK_MESSAGE, 0));
    };

    xhr.onabort = () => {
      reject(new ApiError(ABORTED_CODE, "The upload was cancelled.", 0));
    };

    xhr.send(body);
  });

  return {
    promise,
    abort: () => {
      xhr.abort();
    },
  };
}

export function compressPdf(
  file: File,
  level: Level,
  callbacks: UploadCallbacks = {},
): UploadHandle<CompressResult> {
  const form = new FormData();
  form.append("file", file);
  form.append("level", level);
  return postMultipart("/api/compress", form, parseCompressResult, callbacks);
}

// Best effort: never throws, because the server sweeper cleans up anyway.
export async function deleteJob(jobId: string): Promise<void> {
  try {
    await fetch(`${API_BASE_URL}/api/jobs/${encodeURIComponent(jobId)}`, {
      method: "DELETE",
      keepalive: true,
    });
  } catch {
    // Offline or blocked: nothing useful to do.
  }
}

// The contract's download_url is relative to the API host.
export function buildDownloadUrl(downloadUrl: string): string {
  if (/^https?:\/\//i.test(downloadUrl)) return downloadUrl;
  const path = downloadUrl.startsWith("/") ? downloadUrl : `/${downloadUrl}`;
  return `${API_BASE_URL}${path}`;
}

// ── Phase 2: PDF to JPG ──────────────────────────────────────────────────────

export type Quality = "low" | "medium" | "high";

// "jpg" is one bare image (a one-page PDF); "zip" holds one image per page.
export type ResultKind = "jpg" | "zip";

export type PdfToJpgResult = {
  job_id: string;
  original_name: string;
  page_count: number;
  file_count: number;
  result_size: number;
  kind: ResultKind;
  quality: Quality;
  download_url: string;
};

function isQuality(value: unknown): value is Quality {
  return value === "low" || value === "medium" || value === "high";
}

function isResultKind(value: unknown): value is ResultKind {
  return value === "jpg" || value === "zip";
}

function parsePdfToJpgResult(data: unknown): PdfToJpgResult | null {
  if (!isRecord(data)) return null;
  const {
    job_id,
    original_name,
    page_count,
    file_count,
    result_size,
    kind,
    quality,
    download_url,
  } = data;

  if (
    typeof job_id !== "string" ||
    typeof original_name !== "string" ||
    typeof page_count !== "number" ||
    typeof file_count !== "number" ||
    typeof result_size !== "number" ||
    !isResultKind(kind) ||
    !isQuality(quality) ||
    typeof download_url !== "string"
  ) {
    return null;
  }

  return {
    job_id,
    original_name,
    page_count,
    file_count,
    result_size,
    kind,
    quality,
    download_url,
  };
}

export function convertPdfToJpg(
  file: File,
  quality: Quality,
  callbacks: UploadCallbacks = {},
): UploadHandle<PdfToJpgResult> {
  const form = new FormData();
  form.append("file", file);
  form.append("quality", quality);
  return postMultipart(
    "/api/pdf-to-jpg",
    form,
    parsePdfToJpgResult,
    callbacks,
  );
}
// -- Phase 2: JPG to PDF ------------------------------------------------------

export type PageSize = "fit" | "a4";

export type JpgToPdfResult = {
  job_id: string;
  page_count: number;
  total_input_size: number;
  result_size: number;
  page_size: PageSize;
  // The file name the download will carry, decided by the server.
  download_name: string;
  download_url: string;
};

function isPageSize(value: unknown): value is PageSize {
  return value === "fit" || value === "a4";
}

function parseJpgToPdfResult(data: unknown): JpgToPdfResult | null {
  if (!isRecord(data)) return null;
  const {
    job_id,
    page_count,
    total_input_size,
    result_size,
    page_size,
    download_name,
    download_url,
  } = data;

  if (
    typeof job_id !== "string" ||
    typeof page_count !== "number" ||
    typeof total_input_size !== "number" ||
    typeof result_size !== "number" ||
    !isPageSize(page_size) ||
    typeof download_name !== "string" ||
    typeof download_url !== "string"
  ) {
    return null;
  }

  return {
    job_id,
    page_count,
    total_input_size,
    result_size,
    page_size,
    download_name,
    download_url,
  };
}

// The order of `files` is the page order.
export function jpgToPdf(
  files: readonly File[],
  pageSize: PageSize,
  callbacks: UploadCallbacks = {},
): UploadHandle<JpgToPdfResult> {
  const form = new FormData();
  for (const file of files) {
    form.append("files", file);
  }
  form.append("page_size", pageSize);
  return postMultipart(
    "/api/jpg-to-pdf",
    form,
    parseJpgToPdfResult,
    callbacks,
  );
}
