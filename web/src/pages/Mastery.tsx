import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiClient } from "../api/client";
import { GlassCard } from "../components/GlassCard";
import { GlassProgressBar } from "../components/GlassProgressBar";
import { GlassBadge } from "../components/GlassBadge";
import { GlassButton } from "../components/GlassButton";
import { GlassSkeleton } from "../components/GlassSkeleton";
import { PageTransition } from "../components/PageTransition";

interface SubtopicMastery {
  subtopic_id: number;
  subtopic_title: string;
  mastery_level: string;
  mastery_score: number;
  confidence_score: number;
  retention_score: number;
  total_attempts: number;
  correct_attempts: number;
  last_practiced_at: string | null;
}

interface ReviewDue {
  subtopic_id: number;
  subtopic_title: string;
  next_review_at: string;
  days_overdue: number;
  interval_days: number;
}

interface Recommendation {
  subtopic_id: number;
  subtopic_title: string;
  reason: string;
  priority: number;
  recommended_difficulty: string;
}

const LEVEL_COLORS: Record<string, string> = {
  BEGINNER: "var(--color-danger)",
  FAMILIAR: "var(--color-warning)",
  PROFICIENT: "var(--color-accent)",
  ADVANCED: "var(--color-success)",
  MASTERED: "var(--color-metallic)",
};

const LEVEL_BADGE_COLORS: Record<string, "danger" | "warning" | "accent" | "success" | "primary"> = {
  BEGINNER: "danger",
  FAMILIAR: "warning",
  PROFICIENT: "accent",
  ADVANCED: "success",
  MASTERED: "primary",
};

const REASON_LABELS: Record<string, string> = {
  weak_area: "Needs Practice",
  due_for_review: "Due for Review",
  next_in_sequence: "Next Up",
  challenge: "Challenge",
};

export function Mastery() {
  const [mastery, setMastery] = useState<SubtopicMastery[]>([]);
  const [dueReviews, setDueReviews] = useState<ReviewDue[]>([]);
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      apiClient.get<SubtopicMastery[]>("/v1/mastery/me"),
      apiClient.get<ReviewDue[]>("/v1/mastery/me/reviews/due"),
      apiClient.get<Recommendation[]>("/v1/mastery/me/recommendations"),
    ])
      .then(([m, r, rec]) => {
        setMastery(m);
        setDueReviews(r);
        setRecommendations(rec);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <PageTransition>
        <div className="page container" style={{ maxWidth: 800 }}>
          <h1 style={{ color: "var(--color-text)", fontFamily: "var(--font-family)", marginBottom: "1.5rem" }}>
            Mastery Dashboard
          </h1>
          <GlassCard style={{ marginBottom: "1.5rem" }}>
            <GlassSkeleton height="1.5rem" width="40%" />
            <div style={{ display: "flex", gap: "1rem", marginTop: "1rem", flexWrap: "wrap" }}>
              {[1, 2, 3, 4, 5].map((i) => (
                <GlassSkeleton key={i} height="2.5rem" width="6rem" borderRadius="var(--radius-md)" />
              ))}
            </div>
          </GlassCard>
          <GlassCard>
            <GlassSkeleton height="10rem" />
          </GlassCard>
        </div>
      </PageTransition>
    );
  }

  if (error) {
    return (
      <PageTransition>
        <div className="page container" style={{ maxWidth: 800 }}>
          <p style={{ color: "var(--color-danger)" }}>{error}</p>
        </div>
      </PageTransition>
    );
  }

  // Count subtopics at each level.
  const levelCounts: Record<string, number> = {};
  for (const m of mastery) {
    levelCounts[m.mastery_level] = (levelCounts[m.mastery_level] || 0) + 1;
  }

  return (
    <PageTransition>
      <div className="page container" style={{ maxWidth: 800 }}>
        <h1 style={{ color: "var(--color-text)", fontFamily: "var(--font-family)", marginBottom: "1.5rem" }}>
          Mastery Dashboard
        </h1>

        {/* Overall progress summary */}
        <GlassCard as="section" style={{ marginBottom: "1.5rem" }}>
          <h2 style={{ fontSize: "var(--font-size-lg)", fontWeight: 600, color: "var(--color-text)", marginBottom: "1rem" }}>
            Overall Progress
          </h2>
          <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
            {["BEGINNER", "FAMILIAR", "PROFICIENT", "ADVANCED", "MASTERED"].map((level) => (
              <div
                key={level}
                style={{
                  padding: "0.5rem 1rem",
                  borderRadius: "var(--radius-md)",
                  background: "var(--glass-bg-subtle)",
                  border: "1px solid var(--glass-border-light)",
                }}
              >
                <span style={{ fontWeight: 700, color: LEVEL_COLORS[level], fontSize: "var(--font-size-lg)" }}>
                  {levelCounts[level] || 0}
                </span>{" "}
                <span style={{ color: "var(--color-text-secondary)", fontSize: "var(--font-size-sm)" }}>
                  {level.toLowerCase()}
                </span>
              </div>
            ))}
          </div>
        </GlassCard>

        {/* Due for Review */}
        {dueReviews.length > 0 && (
          <GlassCard as="section" style={{ marginBottom: "1.5rem" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", marginBottom: "1rem" }}>
              <h2 style={{ fontSize: "var(--font-size-lg)", fontWeight: 600, color: "var(--color-text)" }}>
                Due for Review
              </h2>
              <GlassBadge label={String(dueReviews.length)} color="danger" />
            </div>
            <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
              {dueReviews.map((r) => (
                <li
                  key={r.subtopic_id}
                  style={{
                    padding: "0.75rem 0",
                    borderBottom: "1px solid var(--glass-border-light)",
                  }}
                >
                  <span style={{ fontWeight: 500, color: "var(--color-text)" }}>{r.subtopic_title}</span>
                  <span style={{ marginLeft: "0.5rem", fontSize: "var(--font-size-sm)", color: "var(--color-text-secondary)" }}>
                    — {r.days_overdue.toFixed(1)} days overdue
                  </span>
                </li>
              ))}
            </ul>
          </GlassCard>
        )}

        {/* Recommendations */}
        {recommendations.length > 0 && (
          <GlassCard as="section" style={{ marginBottom: "1.5rem" }}>
            <h2 style={{ fontSize: "var(--font-size-lg)", fontWeight: 600, color: "var(--color-text)", marginBottom: "1rem" }}>
              Recommended Next
            </h2>
            <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
              {recommendations.map((rec) => (
                <div
                  key={rec.subtopic_id}
                  style={{
                    padding: "0.75rem 1rem",
                    background: "var(--glass-bg-subtle)",
                    border: "1px solid var(--glass-border-light)",
                    borderRadius: "var(--radius-md)",
                    display: "flex",
                    alignItems: "center",
                    gap: "0.75rem",
                    flexWrap: "wrap",
                  }}
                >
                  <span style={{ fontWeight: 500, color: "var(--color-text)" }}>{rec.subtopic_title}</span>
                  <GlassBadge label={REASON_LABELS[rec.reason] || rec.reason} color="accent" />
                  <span style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-muted)" }}>
                    {rec.recommended_difficulty}
                  </span>
                </div>
              ))}
            </div>
          </GlassCard>
        )}

        {/* Mastery per subtopic */}
        <GlassCard as="section">
          <h2 style={{ fontSize: "var(--font-size-lg)", fontWeight: 600, color: "var(--color-text)", marginBottom: "1rem" }}>
            Subtopic Mastery
          </h2>
          {mastery.length === 0 && (
            <p style={{ color: "var(--color-text-secondary)", fontSize: "var(--font-size-sm)" }}>
              No mastery data yet. Start practicing!
            </p>
          )}
          <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
            {mastery.map((m) => (
              <div key={m.subtopic_id}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.25rem" }}>
                  <span style={{ color: "var(--color-text)", fontSize: "var(--font-size-sm)" }}>{m.subtopic_title}</span>
                  <GlassBadge label={m.mastery_level} color={LEVEL_BADGE_COLORS[m.mastery_level] || "primary"} />
                </div>
                <GlassProgressBar
                  value={m.mastery_score * 100}
                  label={`${m.subtopic_title} mastery: ${Math.round(m.mastery_score * 100)}%`}
                  color={LEVEL_COLORS[m.mastery_level]}
                  height={6}
                />
              </div>
            ))}
          </div>
        </GlassCard>

        <div style={{ marginTop: "1.5rem" }}>
          <Link to="/modules" style={{ textDecoration: "none" }} aria-label="Back to modules">
            <GlassButton variant="ghost">← Back to Modules</GlassButton>
          </Link>
        </div>
      </div>
    </PageTransition>
  );
}
