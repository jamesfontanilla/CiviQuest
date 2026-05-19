import { getToken, logout } from "../stores/auth";

export interface ErrorResponse {
  error: {
    message: string;
    code: string;
  };
}

export class ApiError extends Error {
  status: number;
  code: string;
  requestId: string | null;

  constructor(status: number, message: string, code: string, requestId: string | null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.requestId = requestId;
  }
}

const API_BASE = import.meta.env.VITE_API_URL || "";

async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };

  const token = getToken();
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE}${url}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });

  const requestId = response.headers.get("X-Request-ID");

  if (!response.ok) {
    let errorBody: ErrorResponse | null = null;
    try {
      errorBody = await response.json();
    } catch {
      // response may not be JSON
    }

    // Auto-logout on 401 — token is stale/invalid (e.g., after server restart)
    if (response.status === 401) {
      logout();
      // Use replace so the back button doesn't loop back to the broken page
      window.location.replace("/login");
    }

    throw new ApiError(
      response.status,
      errorBody?.error?.message ?? `Request failed with status ${response.status}`,
      errorBody?.error?.code ?? "UNKNOWN",
      requestId
    );
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json();
}

export const apiClient = {
  get<T>(url: string): Promise<T> {
    return request<T>("GET", url);
  },

  post<T>(url: string, body?: unknown): Promise<T> {
    return request<T>("POST", url, body);
  },

  put<T>(url: string, body?: unknown): Promise<T> {
    return request<T>("PUT", url, body);
  },

  patch<T>(url: string, body?: unknown): Promise<T> {
    return request<T>("PATCH", url, body);
  },

  delete<T>(url: string): Promise<T> {
    return request<T>("DELETE", url);
  },
};
