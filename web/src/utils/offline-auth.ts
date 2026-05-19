import { getLastAuthenticatedAt, isAuthenticated } from "../stores/auth";

const OFFLINE_AUTH_WINDOW_MS = 24 * 60 * 60 * 1000; // 24 hours

/**
 * Check whether the user's offline auth window is still valid.
 * Returns true if the user authenticated within the last 24 hours.
 * If expired or never authenticated, returns false — caller should
 * redirect to login.
 */
export function isOfflineAuthValid(): boolean {
  if (!isAuthenticated()) return false;

  const lastAuth = getLastAuthenticatedAt();
  if (lastAuth === null) return false;

  const elapsed = Date.now() - lastAuth;
  return elapsed < OFFLINE_AUTH_WINDOW_MS;
}

/**
 * Checks offline auth validity and redirects to login if expired.
 * Returns true if auth is valid, false if redirect was triggered.
 */
export function enforceOfflineAuth(): boolean {
  if (!isOfflineAuthValid()) {
    // In a service worker context, we can't use window.location directly.
    // This function is meant to be called from the main thread.
    if (typeof window !== "undefined") {
      window.location.href = "/login";
    }
    return false;
  }
  return true;
}
