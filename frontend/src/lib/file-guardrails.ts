import type { FileError } from "react-dropzone";
import { formatBytes } from "@/lib/format";

/** Validate the browser file before a workspace can create an upload job. */
export function validateUploadFile(
  file: File,
  accept: Record<string, string[]>,
  maxBytes: number,
): FileError | null {
  const extensions = Object.values(accept).flat().map((value) => value.toLowerCase());
  if (file.size === 0) {
    return { code: "file-empty", message: `${file.name} is empty. Choose a file with content.` };
  }
  if (!extensions.some((extension) => file.name.toLowerCase().endsWith(extension))) {
    return {
      code: "file-invalid-extension",
      message: `${file.name} has the wrong extension. Choose ${extensions.join(" or ")} files.`,
    };
  }
  if (file.size > maxBytes) {
    return {
      code: "file-too-large",
      message: `${file.name} is larger than ${formatBytes(maxBytes)}. Choose a smaller file.`,
    };
  }
  return null;
}
