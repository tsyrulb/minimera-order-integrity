export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(message: string, status: number, code: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

function errorDetails(
  value: unknown,
): { code: string; message: string } | null {
  if (!value || typeof value !== "object" || !("error" in value)) return null;
  const error = value.error;
  if (
    !error ||
    typeof error !== "object" ||
    !("message" in error) ||
    typeof error.message !== "string"
  )
    return null;
  return {
    message: error.message,
    code:
      "code" in error && typeof error.code === "string"
        ? error.code
        : "REQUEST_FAILED",
  };
}

export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  if (!headers.has("Content-Type"))
    headers.set("Content-Type", "application/json");
  const response = await fetch("/api/integrity" + path, {
    ...options,
    headers,
    credentials: "same-origin",
  });
  let data: unknown;
  try {
    data = await response.json();
  } catch {
    throw new ApiError(
      "The local server could not return the current state. Refresh to reconnect.",
      response.status,
      "INVALID_RESPONSE",
    );
  }
  if (!response.ok) {
    const error = errorDetails(data);
    throw new ApiError(
      error?.message ||
        "The request could not complete. Please refresh the current state.",
      response.status,
      error?.code || "REQUEST_FAILED",
    );
  }
  return data as T;
}
