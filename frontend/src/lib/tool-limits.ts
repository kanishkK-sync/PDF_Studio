// Limits and class strings shared by tool workspaces. Each backend limit stays
// the authority; the numbers here only save a doomed upload.

// process.env.NEXT_PUBLIC_* is written out in full so Next can inline it at
// build time. A missing, empty or invalid value falls back to the default.
const parsedMaxMb = Number(process.env.NEXT_PUBLIC_MAX_UPLOAD_MB);
export const MAX_UPLOAD_MB =
  Number.isFinite(parsedMaxMb) && parsedMaxMb > 0 ? parsedMaxMb : 100;
export const MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024;

export const pdfTextTools = {
  "redact-pdf": { maxBytes: MAX_UPLOAD_BYTES, maxTerms: 100, maxCharacters: 8000 },
  "pdf-to-markdown": { maxBytes: MAX_UPLOAD_BYTES },
} as const;

const parsedMaxImages = Number(process.env.NEXT_PUBLIC_MAX_IMAGES);
export const MAX_IMAGES =
  Number.isInteger(parsedMaxImages) && parsedMaxImages > 0
    ? parsedMaxImages
    : 50;

// Errors worth a retry button. The others (not an image, too large, too many
// files, ...) fail the same way every time, so the user changes the input.
export const RETRYABLE_CODES: ReadonlySet<string> = new Set([
  "network_error",
  "processing_failed",
  "internal_error",
  "unexpected_response",
]);

export const primaryButtonClass =
  "inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-full bg-accent-violet px-6 text-sm font-medium text-background shadow-glow sm:w-auto";

export const secondaryButtonClass =
  "inline-flex min-h-11 items-center justify-center gap-2 rounded-full border border-border bg-surface-raised px-6 text-sm font-medium text-foreground";
