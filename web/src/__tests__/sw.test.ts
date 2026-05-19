/**
 * Service Worker Integration Tests
 *
 * Full Playwright offline tests require a running backend + browser automation
 * and are out of scope for unit-level testing. Those tests would:
 * - Start the app with a real service worker registered
 * - Go offline via Playwright's network emulation
 * - Verify cached lesson reads work offline
 * - Verify pending events are enqueued to IndexedDB
 * - Go online and verify Background Sync drains the queue
 *
 * For now, we test the API client's Authorization header attachment
 * and the offline auth window check logic.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";

// Mock localStorage for auth store
const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => {
      store[key] = value;
    },
    removeItem: (key: string) => {
      delete store[key];
    },
    clear: () => {
      store = {};
    },
  };
})();

Object.defineProperty(globalThis, "localStorage", { value: localStorageMock });

describe("API Client - Authorization header", () => {
  beforeEach(() => {
    localStorageMock.clear();
    vi.restoreAllMocks();
  });

  it("attaches Authorization Bearer header when token is present", async () => {
    // Set up auth state with a token
    localStorageMock.setItem(
      "cse_auth_state",
      JSON.stringify({ token: "test-jwt-token", lastAuthenticatedAt: Date.now() })
    );

    // Re-import to pick up the new localStorage state
    vi.resetModules();
    const { apiClient } = await import("../api/client");

    // Mock fetch
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers({ "X-Request-ID": "req-123" }),
      json: () => Promise.resolve({ data: "test" }),
    });
    globalThis.fetch = mockFetch;

    await apiClient.get("/v1/modules");

    expect(mockFetch).toHaveBeenCalledWith("/v1/modules", {
      method: "GET",
      headers: {
        "Content-Type": "application/json",
        Authorization: "Bearer test-jwt-token",
      },
      body: undefined,
    });
  });

  it("does not attach Authorization header when no token", async () => {
    localStorageMock.clear();

    vi.resetModules();
    const { apiClient } = await import("../api/client");

    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers(),
      json: () => Promise.resolve({ data: "test" }),
    });
    globalThis.fetch = mockFetch;

    await apiClient.get("/v1/modules");

    expect(mockFetch).toHaveBeenCalledWith("/v1/modules", {
      method: "GET",
      headers: {
        "Content-Type": "application/json",
      },
      body: undefined,
    });
  });

  it("throws ApiError with parsed error body on non-OK response", async () => {
    localStorageMock.clear();
    vi.resetModules();
    const { apiClient, ApiError: _ApiError } = await import("../api/client");

    const mockFetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      headers: new Headers({ "X-Request-ID": "req-456" }),
      json: () =>
        Promise.resolve({
          error: { message: "Token expired", code: "TOKEN_EXPIRED" },
        }),
    });
    globalThis.fetch = mockFetch;

    await expect(apiClient.get("/v1/users/me")).rejects.toMatchObject({
      status: 401,
      code: "TOKEN_EXPIRED",
      message: "Token expired",
      requestId: "req-456",
    });
  });
});

describe("Offline auth window check", () => {
  beforeEach(() => {
    localStorageMock.clear();
    vi.restoreAllMocks();
  });

  it("returns false when not authenticated", async () => {
    localStorageMock.clear();
    vi.resetModules();
    const { isOfflineAuthValid } = await import("../utils/offline-auth");
    expect(isOfflineAuthValid()).toBe(false);
  });

  it("returns true when authenticated within 24h", async () => {
    localStorageMock.setItem(
      "cse_auth_state",
      JSON.stringify({ token: "tok", lastAuthenticatedAt: Date.now() - 1000 })
    );
    vi.resetModules();
    const { isOfflineAuthValid } = await import("../utils/offline-auth");
    expect(isOfflineAuthValid()).toBe(true);
  });

  it("returns false when auth is older than 24h", async () => {
    const over24h = 25 * 60 * 60 * 1000;
    localStorageMock.setItem(
      "cse_auth_state",
      JSON.stringify({ token: "tok", lastAuthenticatedAt: Date.now() - over24h })
    );
    vi.resetModules();
    const { isOfflineAuthValid } = await import("../utils/offline-auth");
    expect(isOfflineAuthValid()).toBe(false);
  });
});
