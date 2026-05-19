import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { apiClient } from "../api/client";
import { logout } from "../stores/auth";
import { GlassCard } from "../components/GlassCard";
import { GlassButton } from "../components/GlassButton";
import { GlassSkeleton } from "../components/GlassSkeleton";
import { PageTransition } from "../components/PageTransition";
import { GlassProgressBar } from "../components/GlassProgressBar";
import { GlassBadge } from "../components/GlassBadge";
import { useToast } from "../context/ToastContext";

interface XPData {
  cumulative_xp: number;
  level: number;
  streak: number;
}

interface Achievement {
  achievement_id: string;
  title: string;
  description: string;
  granted_at: string;
}

function xpForLevel(level: number): number {
  return level * 100;
}

const gradientTextStyle: React.CSSProperties = {
  background: "linear-gradient(135deg, var(--color-accent), var(--color-metallic))",
  WebkitBackgroundClip: "text",
  WebkitTextFillColor: "transparent",
  backgroundClip: "text",
};

export function Profile() {
  const navigate = useNavigate();
  const toast = useToast();
  const [xp, setXp] = useState<XPData | null>(null);
  const [achievements, setAchievements] = useState<Achievement[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      apiClient.get<XPData>("/v1/xp/me"),
      apiClient.get<Achievement[]>("/v1/achievements/me"),
    ])
      .then(([xpRes, achRes]) => {
        setXp(xpRes);
        setAchievements(achRes);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  function handleLogout() {
    apiClient.delete("/v1/auth/sessions/me").catch(() => {});
    logout();
    toast.info("Logged out successfully");
    navigate("/login");
  }

  if (loading) {
    return (
      <PageTransition>
        <div className="page container" style={{ maxWidth: 600 }}>
          <h1 style={{ fontFamily: "var(--font-family)", ...gradientTextStyle }}>Profile</h1>
          <GlassCard>
            <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
              <GlassSkeleton height="2rem" width="60%" />
              <GlassSkeleton height="1.5rem" />
              <GlassSkeleton height="1.5rem" />
              <GlassSkeleton height="1.5rem" width="80%" />
            </div>
          </GlassCard>
        </div>
      </PageTransition>
    );
  }

  if (error) {
    return (
      <PageTransition>
        <div className="page container" style={{ maxWidth: 600 }}>
          <p style={{ color: "var(--color-danger)" }}>{error}</p>
        </div>
      </PageTransition>
    );
  }

  const xpToNext = xp ? xpForLevel(xp.level + 1) : 100;
  const xpInLevel = xp ? xp.cumulative_xp % xpForLevel(xp.level || 1) : 0;

  return (
    <PageTransition>
      <div className="page container" style={{ maxWidth: 600 }}>
        <h1 style={{ fontFamily: "var(--font-family)", marginBottom: "1.5rem", ...gradientTextStyle }}>
          Profile
        </h1>

        {xp && (
          <GlassCard>
            <h2 style={{ fontSize: "var(--font-size-sm)", fontWeight: 600, color: "var(--color-text-secondary)", textTransform: "uppercase", letterSpacing: "0.05em", marginTop: 0, marginBottom: "1.25rem", ...gradientTextStyle }}>
              Progress
            </h2>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "1rem", textAlign: "center", marginBottom: "1.25rem" }}>
              <div>
                <p style={{ fontSize: "1.75rem", fontWeight: 700, margin: 0, color: "var(--color-accent)" }}>{xp.level}</p>
                <p style={{ color: "var(--color-text-secondary)", fontSize: "var(--font-size-sm)", margin: 0 }}>Level</p>
              </div>
              <div>
                <p style={{ fontSize: "1.75rem", fontWeight: 700, margin: 0, color: "var(--color-text)" }}>{xp.cumulative_xp.toLocaleString()}</p>
                <p style={{ color: "var(--color-text-secondary)", fontSize: "var(--font-size-sm)", margin: 0 }}>Total XP</p>
              </div>
              <div>
                <p style={{ fontSize: "1.75rem", fontWeight: 700, margin: 0, color: "var(--color-warning)" }}>🔥 {xp.streak}</p>
                <p style={{ color: "var(--color-text-secondary)", fontSize: "var(--font-size-sm)", margin: 0 }}>Day Streak</p>
              </div>
            </div>
            <GlassProgressBar
              value={xpInLevel}
              max={xpToNext}
              label={`XP to Level ${xp.level + 1}`}
              color="var(--color-primary)"
              animated
            />
          </GlassCard>
        )}

        <section aria-label="Achievements" style={{ marginTop: "1.5rem" }}>
          <h2 style={{ fontFamily: "var(--font-family)", marginBottom: "1rem", ...gradientTextStyle }}>
            Achievements
          </h2>
          {achievements.length === 0 ? (
            <GlassCard>
              <p style={{ color: "var(--color-text-secondary)", margin: 0 }}>No achievements yet. Keep learning!</p>
            </GlassCard>
          ) : (
            <div style={{ display: "grid", gap: "0.75rem" }}>
              {achievements.map((a) => (
                <GlassCard key={a.achievement_id}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                      <span style={{ fontSize: "1.25rem" }}>🏅</span>
                      <strong style={{ color: "var(--color-text)" }}>{a.title}</strong>
                    </div>
                    <GlassBadge
                      label={new Date(a.granted_at).toLocaleDateString()}
                      color="success"
                    />
                  </div>
                </GlassCard>
              ))}
            </div>
          )}
        </section>

        <div style={{ marginTop: "2rem", display: "flex", gap: "1rem" }}>
          <Link to="/modules" style={{ textDecoration: "none" }} aria-label="Back to modules">
            <GlassButton variant="secondary">← Modules</GlassButton>
          </Link>
          <GlassButton variant="danger" onClick={handleLogout} aria-label="Log out">
            Log Out
          </GlassButton>
        </div>
      </div>
    </PageTransition>
  );
}
