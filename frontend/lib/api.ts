export class ApiError extends Error {
  constructor(
    readonly code: string,
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(method: string, path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api/tp/${path}`, {
    ...init,
    method,
    headers: { accept: "application/json", ...init.headers },
    cache: "no-store",
  });
  const text = await response.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = null;
  }
  if (!response.ok) {
    const error = (body as { error?: { code?: unknown; message?: unknown } } | null)?.error;
    if (error && typeof error.code === "string") {
      throw new ApiError(error.code, String(error.message ?? error.code), response.status);
    }
    throw new ApiError("http_error", response.statusText || `HTTP ${response.status}`, response.status);
  }
  return body as T;
}

export function apiGet<T>(path: string, params?: Record<string, string>): Promise<T> {
  const query = params && Object.keys(params).length ? `?${new URLSearchParams(params)}` : "";
  return request<T>("GET", `${path}${query}`);
}

export function apiSend<T>(method: "POST" | "PATCH" | "PUT", path: string, body: unknown): Promise<T> {
  return request<T>(method, path, {
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}
