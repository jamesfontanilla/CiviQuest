const AUTH_STORAGE_KEY = "cse_auth_state";

interface AuthState {
  token: string | null;
  lastAuthenticatedAt: number | null;
}

function loadState(): AuthState {
  try {
    const raw = localStorage.getItem(AUTH_STORAGE_KEY);
    if (raw) {
      return JSON.parse(raw);
    }
  } catch {
    // corrupted state — reset
  }
  return { token: null, lastAuthenticatedAt: null };
}

function saveState(state: AuthState): void {
  localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(state));
}

let state: AuthState = loadState();

export function login(token: string): void {
  state = { token, lastAuthenticatedAt: Date.now() };
  saveState(state);
}

export function logout(): void {
  state = { token: null, lastAuthenticatedAt: null };
  saveState(state);
}

export function isAuthenticated(): boolean {
  return state.token !== null;
}

export function getToken(): string | null {
  return state.token;
}

export function getLastAuthenticatedAt(): number | null {
  return state.lastAuthenticatedAt;
}
