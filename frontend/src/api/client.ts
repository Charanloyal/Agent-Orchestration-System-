// Same-origin JSON client. Cookies carry the session; unsafe methods send the CSRF token.

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | null;
  readonly details: unknown;

  constructor(status: number, code: string, message: string, requestId: string | null, details?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.requestId = requestId;
    this.details = details;
  }
}

let csrfToken: string | null = null;

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

type RequestOptions = {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  form?: FormData;
  headers?: Record<string, string>;
  signal?: AbortSignal;
};

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = options.method ?? "GET";
  const headers: Record<string, string> = { Accept: "application/json", ...options.headers };
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  if (method !== "GET" && csrfToken) {
    headers["X-CSRF-Token"] = csrfToken;
  }

  let response: Response;
  try {
    response = await fetch(path, {
      method,
      headers,
      credentials: "same-origin",
      // FormData sets its own multipart Content-Type with the boundary.
      body: options.form ?? (options.body === undefined ? undefined : JSON.stringify(options.body)),
      signal: options.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }
    throw new ApiError(0, "network_error", "Could not reach the server.", null);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  const text = await response.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      throw new ApiError(response.status, "invalid_response", "The server returned an invalid response.", null);
    }
  }
  if (!response.ok) {
    const error = (data as { error?: { code?: string; message?: string; request_id?: string; details?: unknown } })
      ?.error;
    throw new ApiError(
      response.status,
      error?.code ?? "http_error",
      error?.message ?? `Request failed (HTTP ${response.status}).`,
      error?.request_id ?? response.headers.get("x-request-id"),
      error?.details,
    );
  }
  return data as T;
}

export function newIdempotencyKey(): string {
  return crypto.randomUUID();
}

export type Download = { blob: Blob; filename: string; kind: string | null; sha256: string | null };

/** POST that returns a file (CSRF-protected because the server records the export). */
export async function download(path: string): Promise<Download> {
  const headers: Record<string, string> = { Accept: "text/markdown, application/json" };
  if (csrfToken) headers["X-CSRF-Token"] = csrfToken;
  let response: Response;
  try {
    response = await fetch(path, { method: "POST", headers, credentials: "same-origin" });
  } catch {
    throw new ApiError(0, "network_error", "Could not reach the server.", null);
  }
  if (!response.ok) {
    let error: { code?: string; message?: string; request_id?: string } | undefined;
    try {
      error = ((await response.json()) as { error?: typeof error }).error;
    } catch {
      error = undefined;
    }
    throw new ApiError(
      response.status,
      error?.code ?? "http_error",
      error?.message ?? `Download failed (HTTP ${response.status}).`,
      error?.request_id ?? response.headers.get("x-request-id"),
    );
  }
  const disposition = response.headers.get("content-disposition") ?? "";
  const filename = /filename="([^"]+)"/.exec(disposition)?.[1] ?? "report.md";
  return {
    blob: await response.blob(),
    filename,
    kind: response.headers.get("x-export-kind"),
    sha256: response.headers.get("x-content-sha256"),
  };
}

/** Hand a blob to the browser as a file download. */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
