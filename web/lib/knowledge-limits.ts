/**
 * What the knowledge base will accept, in a form the browser can check.
 *
 * Pure, so the upload component can import it. That component runs in the
 * browser -- it has to, because reporting progress needs the request it is
 * watching -- and a module that also fetched would drag `next/headers`
 * into the bundle.
 *
 * These mirror `app/services/knowledge_service.py`. Checking them here
 * saves somebody a long upload that was always going to be refused; the
 * API checks again, while the body is still arriving, because that is the
 * check that actually bounds what a request can cost.
 */

/** `MAX_FILE_BYTES` in the service. Ten megabytes, not a round guess. */
export const MAX_FILE_BYTES = 10 * 1024 * 1024;

export const MAX_FILE_LABEL = "10MB";

/**
 * What the extractor can open.
 *
 * `application/octet-stream` is on the API's list because browsers send it
 * for a file they cannot identify, and a `.txt` from an unusual source is
 * a real case. It is not offered here: `accept` is a hint for the file
 * picker, and hinting "anything" would defeat the point of hinting.
 */
export const ACCEPTED_TYPES = [
  "application/pdf",
  "text/plain",
  "text/markdown",
  "text/csv",
] as const;

export const ACCEPT_ATTRIBUTE = ".pdf,.txt,.md,.csv,application/pdf,text/plain";

export function isTooLarge(file: File): boolean {
  return file.size > MAX_FILE_BYTES;
}

/** A size somebody can read, rather than a byte count. */
export function readableSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;

  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
