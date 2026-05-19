import { useState, useEffect } from "react";
import { apiClient } from "../api/client";
import { GlassCard } from "../components/GlassCard";
import { GlassButton } from "../components/GlassButton";
import { GlassBadge } from "../components/GlassBadge";
import { GlassSkeleton } from "../components/GlassSkeleton";
import { PageTransition } from "../components/PageTransition";

interface Tournament {
  id: number;
  title: string;
  description: string | null;
  category: string | null;
  starts_at: string;
  ends_at: string;
  status: string;
  max_participants: number | null;
  prize_description: string | null;
}

interface LeaderboardEntry {
  user_id: number;
  xp_earned: number;
  rank: number;
}

export function Tournaments() {
  const [tournaments, setTournaments] = useState<Tournament[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [leaderboard, setLeaderboard] = useState<LeaderboardEntry[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadTournaments();
  }, []);

  async function loadTournaments() {
    try {
      const data = await apiClient.get<Tournament[]>("/v1/tournaments");
      setTournaments(data);
    } catch {
      // handle error
    } finally {
      setLoading(false);
    }
  }

  async function joinTournament(id: number) {
    try {
      await apiClient.post(`/v1/tournaments/${id}:join`);
      loadTournaments();
    } catch {
      // already joined or full
    }
  }

  async function loadLeaderboard(id: number) {
    setSelectedId(id);
    try {
      const data = await apiClient.get<LeaderboardEntry[]>(`/v1/tournaments/${id}/leaderboard`);
      setLeaderboard(data);
    } catch {
      setLeaderboard([]);
    }
  }

  function getCountdown(endsAt: string): string {
    const diff = new Date(endsAt).getTime() - Date.now();
    if (diff <= 0) return "Ended";
    const hours = Math.floor(diff / (1000 * 60 * 60));
    const days = Math.floor(hours / 24);
    if (days > 0) return `${days}d ${hours % 24}h left`;
    return `${hours}h left`;
  }

  if (loading) {
    return (
      <PageTransition>
        <main className="page container" style={{ maxWidth: 900 }}>
          <h1 style={{ color: "var(--color-text)", fontFamily: "var(--font-family)", marginBottom: "1.5rem" }}>
            Tournaments
          </h1>
          <div style={{ display: "grid", gap: "1rem" }}>
            {[1, 2, 3].map((i) => (
              <GlassCard key={i}>
                <GlassSkeleton height="1.25rem" width="50%" />
                <div style={{ marginTop: "0.75rem" }}>
                  <GlassSkeleton height="0.875rem" width="80%" />
                </div>
                <div style={{ marginTop: "1rem", display: "flex", gap: "0.5rem" }}>
                  <GlassSkeleton height="2.25rem" width="5rem" borderRadius="var(--radius-md)" />
                  <GlassSkeleton height="2.25rem" width="7rem" borderRadius="var(--radius-md)" />
                </div>
              </GlassCard>
            ))}
          </div>
        </main>
      </PageTransition>
    );
  }

  return (
    <PageTransition>
      <main className="page container" style={{ maxWidth: 900 }}>
        <h1 style={{ color: "var(--color-text)", fontFamily: "var(--font-family)", marginBottom: "1.5rem" }}>
          Tournaments
        </h1>

        {tournaments.length === 0 && (
          <GlassCard>
            <p style={{ color: "var(--color-text-secondary)", fontSize: "var(--font-size-sm)" }}>
              No active or upcoming tournaments.
            </p>
          </GlassCard>
        )}

        <div style={{ display: "grid", gap: "1rem" }}>
          {tournaments.map((t) => (
            <GlassCard key={t.id}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                <div>
                  <h2 style={{ fontSize: "var(--font-size-lg)", fontWeight: 600, color: "var(--color-text)", marginBottom: "0.25rem" }}>
                    {t.title}
                  </h2>
                  {t.description && (
                    <p style={{ fontSize: "var(--font-size-sm)", color: "var(--color-text-secondary)", marginBottom: "0.5rem" }}>
                      {t.description}
                    </p>
                  )}
                  {t.prize_description && (
                    <p style={{ fontSize: "var(--font-size-sm)", color: "var(--color-accent)" }}>
                      🏆 Prize: {t.prize_description}
                    </p>
                  )}
                </div>
                <GlassBadge
                  label={t.status === "ACTIVE" ? getCountdown(t.ends_at) : "Upcoming"}
                  color={t.status === "ACTIVE" ? "success" : "warning"}
                  size="md"
                />
              </div>

              <div style={{ display: "flex", gap: "0.5rem", marginTop: "1rem" }}>
                <GlassButton variant="primary" size="sm" onClick={() => joinTournament(t.id)}>
                  Join
                </GlassButton>
                <GlassButton variant="ghost" size="sm" onClick={() => loadLeaderboard(t.id)}>
                  Leaderboard
                </GlassButton>
              </div>

              {/* Inline leaderboard */}
              {selectedId === t.id && leaderboard.length > 0 && (
                <div style={{ marginTop: "1rem", borderTop: "1px solid var(--glass-border-light)", paddingTop: "0.75rem" }}>
                  <table style={{ width: "100%", fontSize: "var(--font-size-sm)", borderCollapse: "collapse" }}>
                    <thead>
                      <tr style={{ textAlign: "left", color: "var(--color-text-secondary)" }}>
                        <th style={{ padding: "0.25rem 0" }}>Rank</th>
                        <th>User</th>
                        <th style={{ textAlign: "right" }}>XP</th>
                      </tr>
                    </thead>
                    <tbody>
                      {leaderboard.map((entry) => (
                        <tr key={entry.user_id} style={{ color: "var(--color-text)" }}>
                          <td style={{ padding: "0.25rem 0" }}>#{entry.rank}</td>
                          <td>User {entry.user_id}</td>
                          <td style={{ textAlign: "right", fontWeight: 600 }}>{entry.xp_earned}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </GlassCard>
          ))}
        </div>
      </main>
    </PageTransition>
  );
}
