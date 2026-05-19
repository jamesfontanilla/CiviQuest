import { useState, useEffect } from "react";

interface StreakDisplayProps {
  streak: number;
  freezes: number;
}

const MILESTONES = [7, 14, 30];

export function StreakDisplay({ streak, freezes }: StreakDisplayProps) {
  const [celebrating, setCelebrating] = useState(false);

  useEffect(() => {
    if (MILESTONES.includes(streak)) {
      setCelebrating(true);
      const timer = setTimeout(() => setCelebrating(false), 2000);
      return () => clearTimeout(timer);
    }
  }, [streak]);

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: "0.5rem",
        padding: "0.5rem 0.75rem",
        borderRadius: "var(--radius-sm)",
        background: streak > 0 ? "var(--glass-bg-strong)" : "var(--glass-bg-subtle)",
        backdropFilter: "var(--glass-blur-sm)",
        WebkitBackdropFilter: "var(--glass-blur-sm)",
        border: "1px solid var(--glass-border-medium)",
        boxShadow: streak > 0 ? "var(--shadow-glow)" : "none",
      }}
      aria-label={`Current streak: ${streak} days`}
    >
      <span
        style={{
          fontSize: "1.5rem",
          animation: streak > 0 ? "pulse 1.5s ease-in-out infinite" : undefined,
        }}
        role="img"
        aria-hidden="true"
      >
        🔥
      </span>
      <span style={{ fontWeight: 700, fontSize: "1.125rem", color: "var(--color-text)" }}>
        {streak}
      </span>
      <span style={{ fontSize: "0.8125rem", color: "var(--color-text-secondary)" }}>
        day{streak !== 1 ? "s" : ""}
      </span>
      {freezes > 0 && (
        <span title={`${freezes} freeze${freezes !== 1 ? "s" : ""} available`} style={{ marginLeft: "0.25rem" }}>
          ❄️
        </span>
      )}
      {celebrating && (
        <span style={{ animation: "bounce 0.5s ease" }} role="img" aria-label="Celebration">
          🎉
        </span>
      )}
      <style>{`
        @keyframes pulse {
          0%, 100% { transform: scale(1); }
          50% { transform: scale(1.15); }
        }
        @keyframes bounce {
          0%, 100% { transform: translateY(0); }
          50% { transform: translateY(-4px); }
        }
      `}</style>
    </div>
  );
}
