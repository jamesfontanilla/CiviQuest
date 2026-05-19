/**
 * Pomodoro Focus Mode page.
 *
 * Features:
 * - Circular countdown timer (minutes:seconds)
 * - Mode selector: 25/5, 50/10, Custom
 * - Controls: Start, Pause, Reset, Skip Break
 * - Session counter ("Session 3 of 4")
 * - State machine: IDLE → WORKING → BREAK → WORKING → ... → DONE
 * - Distraction tracking via document.visibilitychange
 * - Timer state persisted in localStorage
 * - Auto-break with Web Audio API beep
 * - Focus analytics section
 */

import { useState, useEffect, useRef, useCallback } from "react";
import { apiClient } from "../api/client";
import { GlassCard } from "../components/GlassCard";
import { GlassButton } from "../components/GlassButton";
import { PageTransition } from "../components/PageTransition";

type TimerState = "IDLE" | "WORKING" | "BREAK" | "PAUSED" | "DONE";
type Mode = "25_5" | "50_10" | "custom";

interface FocusStats {
  total_sessions: number;
  total_focus_hours: number;
  avg_session_minutes: number;
  sessions_today: number;
  focus_minutes_today: number;
}

interface SessionData {
  id: number;
  mode: string;
  work_minutes: number;
  break_minutes: number;
}

const STORAGE_KEY = "civiquest_focus_state";
const TOTAL_SESSIONS = 4;

function playBeep() {
  try {
    const ctx = new AudioContext();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.frequency.value = 800;
    gain.gain.value = 0.3;
    osc.start();
    osc.stop(ctx.currentTime + 0.3);
  } catch {
    // Audio not available — silent fallback
  }
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
}

export function Focus() {
  const [mode, setMode] = useState<Mode>("25_5");
  const [customWork, setCustomWork] = useState(25);
  const [customBreak, setCustomBreak] = useState(5);
  const [timerState, setTimerState] = useState<TimerState>("IDLE");
  const [secondsLeft, setSecondsLeft] = useState(25 * 60);
  const [currentSession, setCurrentSession] = useState(1);
  const [distractions, setDistractions] = useState(0);
  const [totalFocusSeconds, setTotalFocusSeconds] = useState(0);
  const [stats, setStats] = useState<FocusStats | null>(null);
  const [sessionId, setSessionId] = useState<number | null>(null);

  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pausedStateRef = useRef<TimerState>("WORKING");

  const workMinutes = mode === "25_5" ? 25 : mode === "50_10" ? 50 : customWork;
  const breakMinutes = mode === "25_5" ? 5 : mode === "50_10" ? 10 : customBreak;

  // Load stats on mount
  useEffect(() => {
    apiClient.get<FocusStats>("/v1/focus/sessions/me/stats").then(setStats).catch(() => {});
  }, []);

  // Persist timer state to localStorage
  useEffect(() => {
    if (timerState !== "IDLE" && timerState !== "DONE") {
      const state = { timerState, secondsLeft, currentSession, distractions, totalFocusSeconds, sessionId, mode };
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } else {
      localStorage.removeItem(STORAGE_KEY);
    }
  }, [timerState, secondsLeft, currentSession, distractions, totalFocusSeconds, sessionId, mode]);

  // Restore state from localStorage on mount
  useEffect(() => {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved) {
      try {
        const s = JSON.parse(saved);
        setTimerState(s.timerState === "PAUSED" ? "PAUSED" : s.timerState);
        setSecondsLeft(s.secondsLeft);
        setCurrentSession(s.currentSession);
        setDistractions(s.distractions);
        setTotalFocusSeconds(s.totalFocusSeconds);
        setSessionId(s.sessionId);
        if (s.mode) setMode(s.mode);
        if (s.timerState !== "PAUSED") pausedStateRef.current = s.timerState;
      } catch {
        localStorage.removeItem(STORAGE_KEY);
      }
    }
  }, []);

  // Track distractions via visibility change
  useEffect(() => {
    const handler = () => {
      if (document.hidden && (timerState === "WORKING")) {
        setDistractions((d) => d + 1);
      }
    };
    document.addEventListener("visibilitychange", handler);
    return () => document.removeEventListener("visibilitychange", handler);
  }, [timerState]);

  // Timer tick
  useEffect(() => {
    if (timerState === "WORKING" || timerState === "BREAK") {
      intervalRef.current = setInterval(() => {
        setSecondsLeft((prev) => {
          if (prev <= 1) {
            return 0;
          }
          return prev - 1;
        });
        if (timerState === "WORKING") {
          setTotalFocusSeconds((t) => t + 1);
        }
      }, 1000);
    }
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [timerState]);

  // Handle timer reaching zero
  useEffect(() => {
    if (secondsLeft === 0 && timerState === "WORKING") {
      playBeep();
      if (currentSession >= TOTAL_SESSIONS) {
        setTimerState("DONE");
        completeSession();
      } else {
        setTimerState("BREAK");
        setSecondsLeft(breakMinutes * 60);
      }
    } else if (secondsLeft === 0 && timerState === "BREAK") {
      playBeep();
      setCurrentSession((s) => s + 1);
      setTimerState("WORKING");
      setSecondsLeft(workMinutes * 60);
    }
  }, [secondsLeft, timerState]);

  const startSession = async () => {
    try {
      const data = await apiClient.post<SessionData>("/v1/focus/sessions", {
        mode,
        work_minutes: workMinutes,
        break_minutes: breakMinutes,
      });
      setSessionId(data.id);
    } catch {
      // Continue even if backend fails — timer is client-side
    }
    setTimerState("WORKING");
    setSecondsLeft(workMinutes * 60);
    setCurrentSession(1);
    setDistractions(0);
    setTotalFocusSeconds(0);
  };

  const completeSession = useCallback(async () => {
    if (sessionId) {
      try {
        await apiClient.post(`/v1/focus/sessions/${sessionId}:complete`, {
          total_focus_minutes: Math.round(totalFocusSeconds / 60),
          distractions,
        });
        // Refresh stats
        const newStats = await apiClient.get<FocusStats>("/v1/focus/sessions/me/stats");
        setStats(newStats);
      } catch {
        // Non-critical
      }
    }
    setSessionId(null);
    localStorage.removeItem(STORAGE_KEY);
  }, [sessionId, totalFocusSeconds, distractions]);

  const pause = () => {
    pausedStateRef.current = timerState;
    setTimerState("PAUSED");
  };

  const resume = () => {
    setTimerState(pausedStateRef.current);
  };

  const reset = async () => {
    if (sessionId) {
      try {
        await apiClient.post(`/v1/focus/sessions/${sessionId}:abandon`);
      } catch {
        // Non-critical
      }
    }
    setTimerState("IDLE");
    setSecondsLeft(workMinutes * 60);
    setCurrentSession(1);
    setDistractions(0);
    setTotalFocusSeconds(0);
    setSessionId(null);
    localStorage.removeItem(STORAGE_KEY);
  };

  const skipBreak = () => {
    if (timerState === "BREAK") {
      setCurrentSession((s) => s + 1);
      setTimerState("WORKING");
      setSecondsLeft(workMinutes * 60);
    }
  };

  // Calculate progress for circular display
  const totalSeconds = timerState === "BREAK" ? breakMinutes * 60 : workMinutes * 60;
  const progress = totalSeconds > 0 ? ((totalSeconds - secondsLeft) / totalSeconds) * 100 : 0;

  const isActive = timerState === "WORKING" || timerState === "BREAK" || timerState === "PAUSED";

  return (
    <PageTransition>
      <main className="page container" style={{ maxWidth: 600, textAlign: "center" }}>
        {/* Hide non-essential UI during active focus */}
        {!isActive && (
          <>
            <h1 style={{ fontSize: "var(--font-size-2xl)", fontWeight: 700, color: "var(--color-text)", marginBottom: "0.5rem" }}>
              ⏱️ Focus Mode
            </h1>
            <p style={{ color: "var(--color-text-secondary)", marginBottom: "1.5rem", fontSize: "var(--font-size-sm)" }}>
              Stay focused with Pomodoro technique. Work in intervals, take breaks.
            </p>
          </>
        )}

        {/* Mode selector — only when idle */}
        {timerState === "IDLE" && (
          <GlassCard style={{ marginBottom: "1.5rem" }}>
            <div style={{ display: "flex", justifyContent: "center", gap: "0.5rem", marginBottom: "1rem" }}>
              {(["25_5", "50_10", "custom"] as Mode[]).map((m) => (
                <GlassButton
                  key={m}
                  variant={mode === m ? "primary" : "ghost"}
                  size="sm"
                  onClick={() => {
                    setMode(m);
                    const w = m === "25_5" ? 25 : m === "50_10" ? 50 : customWork;
                    setSecondsLeft(w * 60);
                  }}
                  aria-label={`Select ${m === "25_5" ? "25/5" : m === "50_10" ? "50/10" : "Custom"} mode`}
                >
                  {m === "25_5" ? "25/5" : m === "50_10" ? "50/10" : "Custom"}
                </GlassButton>
              ))}
            </div>
            {mode === "custom" && (
              <div style={{ display: "flex", justifyContent: "center", gap: "0.75rem" }}>
                <label style={{ fontSize: "var(--font-size-sm)", color: "var(--color-text-secondary)" }}>
                  Work:
                  <input
                    type="number"
                    min={5}
                    max={120}
                    value={customWork}
                    onChange={(e) => {
                      const v = Number(e.target.value);
                      setCustomWork(v);
                      setSecondsLeft(v * 60);
                    }}
                    style={{
                      width: 60,
                      marginLeft: "0.25rem",
                      padding: "0.25rem",
                      borderRadius: "var(--radius-sm)",
                      border: "1px solid var(--glass-border-medium)",
                      background: "var(--glass-bg-subtle)",
                      color: "var(--color-text)",
                    }}
                    aria-label="Work minutes"
                  />
                  min
                </label>
                <label style={{ fontSize: "var(--font-size-sm)", color: "var(--color-text-secondary)" }}>
                  Break:
                  <input
                    type="number"
                    min={1}
                    max={30}
                    value={customBreak}
                    onChange={(e) => setCustomBreak(Number(e.target.value))}
                    style={{
                      width: 60,
                      marginLeft: "0.25rem",
                      padding: "0.25rem",
                      borderRadius: "var(--radius-sm)",
                      border: "1px solid var(--glass-border-medium)",
                      background: "var(--glass-bg-subtle)",
                      color: "var(--color-text)",
                    }}
                    aria-label="Break minutes"
                  />
                  min
                </label>
              </div>
            )}
          </GlassCard>
        )}

        {/* Timer display */}
        <GlassCard style={{ marginBottom: "1.5rem", display: "flex", flexDirection: "column", alignItems: "center" }}>
          <div
            style={{
              position: "relative",
              width: 220,
              height: 220,
              borderRadius: "50%",
              background: `conic-gradient(var(--color-accent) ${progress}%, var(--glass-border-medium) ${progress}%)`,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
            role="timer"
            aria-label={`${formatTime(secondsLeft)} remaining`}
          >
            <div
              style={{
                width: 190,
                height: 190,
                borderRadius: "50%",
                background: "var(--color-background)",
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <span style={{ fontSize: "var(--font-size-4xl)", fontWeight: 700, fontVariantNumeric: "tabular-nums", color: "var(--color-text)" }}>
                {formatTime(secondsLeft)}
              </span>
              <span style={{ fontSize: "var(--font-size-sm)", color: "var(--color-text-secondary)", marginTop: "0.25rem" }}>
                {timerState === "BREAK" ? "Break" : timerState === "PAUSED" ? "Paused" : timerState === "DONE" ? "Done!" : timerState === "WORKING" ? "Focus" : "Ready"}
              </span>
            </div>
          </div>

          {/* Session counter */}
          {isActive && (
            <p style={{ fontSize: "var(--font-size-sm)", color: "var(--color-text-secondary)", marginTop: "1rem" }}>
              Session {currentSession} of {TOTAL_SESSIONS}
            </p>
          )}
        </GlassCard>

        {/* Controls */}
        <div style={{ display: "flex", justifyContent: "center", gap: "0.5rem", flexWrap: "wrap", marginBottom: "1.5rem" }}>
          {timerState === "IDLE" && (
            <GlassButton variant="primary" onClick={startSession}>
              ▶ Start
            </GlassButton>
          )}
          {timerState === "WORKING" && (
            <GlassButton variant="ghost" onClick={pause}>
              ⏸ Pause
            </GlassButton>
          )}
          {timerState === "PAUSED" && (
            <GlassButton variant="primary" onClick={resume}>
              ▶ Resume
            </GlassButton>
          )}
          {timerState === "BREAK" && (
            <GlassButton variant="ghost" onClick={skipBreak}>
              ⏭ Skip Break
            </GlassButton>
          )}
          {isActive && (
            <GlassButton variant="danger" onClick={reset}>
              ⏹ Reset
            </GlassButton>
          )}
          {timerState === "DONE" && (
            <GlassButton variant="primary" onClick={() => { setTimerState("IDLE"); setSecondsLeft(workMinutes * 60); }}>
              🔄 New Session
            </GlassButton>
          )}
        </div>

        {/* Distraction counter during active session */}
        {isActive && distractions > 0 && (
          <p style={{ fontSize: "var(--font-size-sm)", color: "var(--color-text-secondary)", marginBottom: "1rem" }}>
            Tab switches: {distractions}
          </p>
        )}

        {/* Focus analytics */}
        {stats && (
          <GlassCard style={{ textAlign: "left" }}>
            <h3 style={{ fontSize: "var(--font-size-base)", fontWeight: 600, color: "var(--color-text)", marginBottom: "0.75rem" }}>
              📊 Focus Stats
            </h3>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem", fontSize: "var(--font-size-sm)" }}>
              <div>
                <span style={{ color: "var(--color-text-secondary)" }}>Today</span>
                <p style={{ fontWeight: 600, margin: "0.125rem 0 0", color: "var(--color-text)" }}>{stats.focus_minutes_today} min</p>
              </div>
              <div>
                <span style={{ color: "var(--color-text-secondary)" }}>Sessions today</span>
                <p style={{ fontWeight: 600, margin: "0.125rem 0 0", color: "var(--color-text)" }}>{stats.sessions_today}</p>
              </div>
              <div>
                <span style={{ color: "var(--color-text-secondary)" }}>Total hours</span>
                <p style={{ fontWeight: 600, margin: "0.125rem 0 0", color: "var(--color-text)" }}>{stats.total_focus_hours}h</p>
              </div>
              <div>
                <span style={{ color: "var(--color-text-secondary)" }}>Avg session</span>
                <p style={{ fontWeight: 600, margin: "0.125rem 0 0", color: "var(--color-text)" }}>{stats.avg_session_minutes} min</p>
              </div>
            </div>
          </GlassCard>
        )}
      </main>
    </PageTransition>
  );
}
