import { openDB, type DBSchema, type IDBPDatabase } from "idb";

export interface PendingEvent {
  id?: number;
  client_event_id: string;
  kind: string;
  client_timestamp: string;
  payload: unknown;
  created_at: number;
}

export interface CachedLesson {
  subtopic_id: number;
  data: unknown;
  cached_at: number;
}

export interface CachedSubtopicPool {
  subtopic_id: number;
  questions: unknown[];
  cached_at: number;
}

export interface AuthStateRecord {
  key: "current";
  token: string | null;
  lastAuthenticatedAt: number | null;
}

interface CSEReviewerDB extends DBSchema {
  cached_lessons: {
    key: number;
    value: CachedLesson;
  };
  cached_subtopic_pools: {
    key: number;
    value: CachedSubtopicPool;
  };
  pending_events: {
    key: number;
    value: PendingEvent;
    indexes: { "by-client-event-id": string };
  };
  auth_state: {
    key: string;
    value: AuthStateRecord;
  };
}

let dbPromise: Promise<IDBPDatabase<CSEReviewerDB>> | null = null;

function getDB(): Promise<IDBPDatabase<CSEReviewerDB>> {
  if (!dbPromise) {
    dbPromise = openDB<CSEReviewerDB>("cse-reviewer", 1, {
      upgrade(db) {
        db.createObjectStore("cached_lessons", { keyPath: "subtopic_id" });
        db.createObjectStore("cached_subtopic_pools", { keyPath: "subtopic_id" });
        const pendingStore = db.createObjectStore("pending_events", {
          keyPath: "id",
          autoIncrement: true,
        });
        pendingStore.createIndex("by-client-event-id", "client_event_id", { unique: true });
        db.createObjectStore("auth_state", { keyPath: "key" });
      },
    });
  }
  return dbPromise;
}

export async function getCachedLesson(subtopicId: number): Promise<CachedLesson | undefined> {
  const db = await getDB();
  return db.get("cached_lessons", subtopicId);
}

export async function setCachedLesson(subtopicId: number, data: unknown): Promise<void> {
  const db = await getDB();
  await db.put("cached_lessons", { subtopic_id: subtopicId, data, cached_at: Date.now() });
}

export async function addPendingEvent(event: Omit<PendingEvent, "id" | "created_at">): Promise<void> {
  const db = await getDB();
  await db.add("pending_events", { ...event, created_at: Date.now() } as PendingEvent);
}

export async function drainPendingEvents(): Promise<PendingEvent[]> {
  const db = await getDB();
  return db.getAll("pending_events");
}

export async function clearPendingEvents(ids: number[]): Promise<void> {
  const db = await getDB();
  const tx = db.transaction("pending_events", "readwrite");
  for (const id of ids) {
    await tx.store.delete(id);
  }
  await tx.done;
}
