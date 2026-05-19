/**
 * Background Sync logic for the service worker.
 *
 * Registers a "progress-sync" tag. On sync event, drains all pending_events
 * from IndexedDB and POSTs them to /v1/progress:sync. On success, removes
 * accepted events and notifies the client via postMessage.
 *
 * NOTE: This file is intended to be imported by the service worker entry point.
 * In a Workbox-based setup (vite-plugin-pwa), custom sync logic can be injected
 * via the `injectManifest` strategy. For MVP, this serves as the reference
 * implementation that documents the sync contract.
 */

export const SYNC_TAG = "progress-sync";

export interface SyncEvent {
  client_event_id: string;
  kind: string;
  client_timestamp: string;
  payload: unknown;
}

export interface SyncResponse {
  accepted: Array<{ client_event_id: string }>;
  rejected: Array<{ client_event_id: string; reason: string }>;
}

/**
 * Register the background sync tag. Call this from the main thread
 * after enqueuing a pending event.
 */
export async function registerSync(): Promise<void> {
  if ("serviceWorker" in navigator && "SyncManager" in window) {
    const registration = await navigator.serviceWorker.ready;
    await (registration as unknown as { sync: { register: (tag: string) => Promise<void> } }).sync.register(SYNC_TAG);
  }
}

/**
 * Handle the sync event inside the service worker.
 * This function should be called from the SW's `sync` event listener.
 */
export async function handleSync(
  getToken: () => string | null,
  drainEvents: () => Promise<Array<{ id?: number } & SyncEvent>>,
  clearEvents: (ids: number[]) => Promise<void>,
  postMessageToClients: (msg: unknown) => void
): Promise<void> {
  const token = getToken();
  if (!token) return;

  const events = await drainEvents();
  if (events.length === 0) return;

  const body = {
    events: events.map((e) => ({
      client_event_id: e.client_event_id,
      kind: e.kind,
      client_timestamp: e.client_timestamp,
      payload: e.payload,
    })),
  };

  const response = await fetch("/v1/progress:sync", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(body),
  });

  if (response.ok) {
    const result: SyncResponse = await response.json();
    const acceptedIds = new Set(result.accepted.map((a) => a.client_event_id));
    const idsToRemove = events
      .filter((e) => acceptedIds.has(e.client_event_id))
      .map((e) => e.id!)
      .filter((id) => id !== undefined);

    await clearEvents(idsToRemove);
    postMessageToClients({ type: "sync_complete", accepted: result.accepted.length });
  }
}
