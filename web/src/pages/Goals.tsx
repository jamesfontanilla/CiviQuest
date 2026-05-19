import { useState, useEffect } from "react";
import { apiClient } from "../api/client";
import { GlassCard } from "../components/GlassCard";
import { GlassButton } from "../components/GlassButton";
import { GlassBadge } from "../components/GlassBadge";
import { GlassSkeleton } from "../components/GlassSkeleton";
import { PageTransition } from "../components/PageTransition";

interface DailyGoal {
  id: number;
  target_xp: number;
  current_xp: number;
  goal_date: string;
  completed: boolean;
  completed_at: string | null;
}

interface DaySummary {
  goal_date: string;
  target_xp: number;
  current_xp: number;
  completed: boolean;
}

interface WeeklySummary {
  days: DaySummary[];
  completed_count: number;
  total_days: number;
}

interface FreezeCount {
  available: number;
}

const TARGETS = [25, 50, 100, 150];

export function Goals() {
  const [goal, setGoal] = useState<DailyGoal | null>(null);
  const [weekly, setWeekly] = useState<WeeklySummary | null>(null);
  const [freezes, setFreezes] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadData();
  }, []);

  async function loadData() {
    try {
      const [goalRes, weeklyRes, freezeRes] = await Promise.all([
        apiClient.get<DailyGoal>("/v1/goals/me/today"),
        apiClient.get<WeeklySummary>("/v1/goals/me/weekly"),
        apiClient.get<FreezeCount>("/v1/streak/me/freezes"),
      ]);
      setGoal(goalRes);
      setWeekly(weeklyRes);
      setFreezes(freezeRes.available);
    } catch {
      // handle error silently
    } finally {
      setLoading(false);
    }
  }

  async function setTarget(target: number) {
    await apiClient.put("/v1/goals/me/target", { target_xp: target });
    loadData();
  }

  if (loading) {
    return (
      <PageTransition>
        <main className="page container" style={{ maxWidth: 800 }}>
          <h1 style={{ color: "var(--color-text)", fontFamily: "var(--font-family)", marginBottom: "1.5rem" }}>
            Daily Goals
          </h1>
          <GlassCard style={{ marginBottom: "1.5rem", display: "flex", flexDirection: "column", alignItems: "center" }}>
            <GlassSkeleton width="120px" height="120px" borderRadius="50%" />
            <div style={{ marginTop: "1rem" }}>
              <GlassSkeleton width="8rem" height="1rem" />
            </div>
          </GlassCard>
          <GlassCard>
            <GlassSkeleton height="3rem" />
          </GlassCard>
        </main>
      </PageTransition>
    );
  }

  const progress = goal ? Math.min((goal.current_xp / goal.target_xp) * 100, 100) : 0;
  const circumference = 2 * Math.PI * 45;
  const strokeDashoffset = circumference - (progress / 100) * circumference;

  return (
    <PageTransition>
      <main className="page container" style={{ maxWidth: 800 }}>
        <h1 style={{ color: "var(--color-text)", fontFamily: "var(--font-family)", marginBottom: "1.5rem" }}>
          Daily Goals
        </h1>

        {/* Progress Ring */}
        <GlassCard style={{ display: "flex", flexDirection: "column", alignItems: "center", marginBottom: "1.5rem" }}>
          <svg width="120" height="120" viewBox="0 0 100 100" aria-label={`Daily goal progress: ${Math.round(progress)}%`}>
            <circle cx="50" cy="50" r="45" fill="none" stroke="var(--glass-border-medium)" strokeWidth="8" />
            <circle
              cx="50" cy="50" r="45" fill="none"
              stroke={goal?.completed ? "var(--color-success)" : "var(--color-accent)"}
              strokeWidth="8" strokeLinecap="round"
              strokeDasharray={circumference}
              strokeDashoffset={strokeDashoffset}
              transform="rotate(-90 50 50)"
              style={{ transition: "stroke-dashoffset 0.5s ease" }}
            />
            <text x="50" y="50" textAnchor="middle" dominantBaseline="middle" fontSize="14" fontWeight="700" fill="var(--color-text)">
              {goal ? `${goal.current_xp}/${goal.target_xp}` : "—"}
            </text>
          </svg>
          {goal?.completed && (
            <GlassBadge label="✅ Goal Complete!" color="success" size="md" />
          )}
        </GlassCard>

        {/* Target Selector */}
        <GlassCard as="section" style={{ marginBottom: "1.5rem" }}>
          <h2 style={{ fontSize: "var(--font-size-lg)", fontWeight: 600, color: "var(--color-text)", marginBottom: "0.75rem" }}>
            Daily XP Target
          </h2>
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            {TARGETS.map((t) => (
              <GlassButton
                key={t}
                variant={goal?.target_xp === t ? "primary" : "ghost"}
                size="sm"
                onClick={() => setTarget(t)}
              >
                {t} XP
              </GlassButton>
            ))}
          </div>
        </GlassCard>

        {/* Streak Freeze Indicator */}
        <GlassCard style={{ marginBottom: "1.5rem", display: "flex", alignItems: "center", gap: "0.75rem" }}>
          <span style={{ fontSize: "var(--font-size-xl)" }}>❄️</span>
          <span style={{ fontSize: "var(--font-size-sm)", color: "var(--color-text-secondary)" }}>
            Streak Freezes: <strong style={{ color: "var(--color-text)" }}>{freezes}</strong>
          </span>
        </GlassCard>

        {/* Weekly Calendar */}
        {weekly && (
          <GlassCard as="section">
            <h2 style={{ fontSize: "var(--font-size-lg)", fontWeight: 600, color: "var(--color-text)", marginBottom: "0.75rem" }}>
              This Week ({weekly.completed_count}/{weekly.total_days} days)
            </h2>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(7, 1fr)", gap: "0.5rem" }}>
              {weekly.days.map((day) => {
                const dayName = new Date(day.goal_date + "T00:00:00").toLocaleDateString(undefined, { weekday: "short" });
                return (
                  <div
                    key={day.goal_date}
                    style={{
                      textAlign: "center",
                      padding: "0.5rem 0.25rem",
                      borderRadius: "var(--radius-sm)",
                      background: day.completed ? "var(--color-success)" : "var(--glass-bg-subtle)",
                      color: day.completed ? "var(--color-background-warm)" : "var(--color-text-secondary)",
                      fontSize: "var(--font-size-xs)",
                      border: day.completed ? "none" : "1px solid var(--glass-border-light)",
                    }}
                  >
                    <div style={{ fontWeight: 600 }}>{dayName}</div>
                    <div>{day.completed ? "✓" : "—"}</div>
                  </div>
                );
              })}
            </div>
          </GlassCard>
        )}
      </main>
    </PageTransition>
  );
}
