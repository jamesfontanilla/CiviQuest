import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiClient } from "../api/client";
import { GlassCard } from "../components/GlassCard";
import { GlassSkeleton } from "../components/GlassSkeleton";
import { PageTransition } from "../components/PageTransition";

interface LeaderboardEntry {
  display_name: string;
  level: number;
  xp_window: number;
  category: string;
}

export function Leaderboard() {
  const [entries, setEntries] = useState<LeaderboardEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiClient
      .get<LeaderboardEntry[]>("/v1/leaderboards/global")
      .then((res) => setEntries(res))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <PageTransition>
        <div className="page container" style={{ maxWidth: 720 }}>
          <h1 style={{ color: "var(--color-text)", fontFamily: "var(--font-family)", marginBottom: "1.5rem" }}>
            Leaderboard
          </h1>
          <GlassCard>
            <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
              {[1, 2, 3, 4, 5].map((i) => (
                <GlassSkeleton key={i} height="2.5rem" />
              ))}
            </div>
          </GlassCard>
        </div>
      </PageTransition>
    );
  }

  if (error) {
    return (
      <PageTransition>
        <div className="page container" style={{ maxWidth: 720 }}>
          <p style={{ color: "var(--color-danger)" }}>{error}</p>
        </div>
      </PageTransition>
    );
  }

  return (
    <PageTransition>
      <div className="page container" style={{ maxWidth: 720 }}>
        <h1 style={{ color: "var(--color-text)", fontFamily: "var(--font-family)", marginBottom: "1.5rem" }}>
          Leaderboard
        </h1>
        <GlassCard>
          <table style={{ width: "100%", borderCollapse: "collapse" }} aria-label="Global leaderboard">
            <thead>
              <tr style={{ borderBottom: "1px solid var(--glass-border-medium)" }}>
                <th style={{ textAlign: "left", padding: "0.75rem 0.5rem", color: "var(--color-text-secondary)", fontSize: "var(--font-size-sm)", fontWeight: 600 }}>#</th>
                <th style={{ textAlign: "left", padding: "0.75rem 0.5rem", color: "var(--color-text-secondary)", fontSize: "var(--font-size-sm)", fontWeight: 600 }}>Name</th>
                <th style={{ textAlign: "right", padding: "0.75rem 0.5rem", color: "var(--color-text-secondary)", fontSize: "var(--font-size-sm)", fontWeight: 600 }}>Level</th>
                <th style={{ textAlign: "right", padding: "0.75rem 0.5rem", color: "var(--color-text-secondary)", fontSize: "var(--font-size-sm)", fontWeight: 600 }}>XP</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((entry, i) => (
                <tr
                  key={i}
                  className="leaderboard-row"
                  style={{
                    background: "var(--glass-bg-subtle)",
                    borderBottom: "1px solid var(--glass-border-light)",
                    transition: "background var(--transition-fast)",
                  }}
                >
                  <td style={{ padding: "0.75rem 0.5rem", color: "var(--color-text-muted)", fontSize: "var(--font-size-sm)", fontWeight: 600 }}>{i + 1}</td>
                  <td style={{ padding: "0.75rem 0.5rem", color: "var(--color-text)", fontSize: "var(--font-size-base)" }}>{entry.display_name}</td>
                  <td style={{ textAlign: "right", padding: "0.75rem 0.5rem", color: "var(--color-accent)", fontSize: "var(--font-size-sm)", fontWeight: 600 }}>{entry.level}</td>
                  <td style={{ textAlign: "right", padding: "0.75rem 0.5rem", color: "var(--color-text-secondary)", fontSize: "var(--font-size-sm)" }}>{entry.xp_window.toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {entries.length === 0 && (
            <p style={{ color: "var(--color-text-secondary)", textAlign: "center", padding: "2rem 0" }}>
              No entries yet.
            </p>
          )}
        </GlassCard>
        <Link
          to="/modules"
          style={{
            display: "inline-block",
            marginTop: "1.5rem",
            color: "var(--color-accent)",
            textDecoration: "none",
            fontSize: "var(--font-size-sm)",
            transition: "color var(--transition-fast)",
          }}
          aria-label="Back to modules"
        >
          ← Back
        </Link>
      </div>
    </PageTransition>
  );
}
