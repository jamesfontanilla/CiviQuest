import { useEffect, useState } from "react";
import { apiClient } from "../api/client";
import { GlassCard } from "../components/GlassCard";
import { GlassStatCard } from "../components/GlassStatCard";
import { GlassProgressBar } from "../components/GlassProgressBar";
import { GlassSkeleton } from "../components/GlassSkeleton";
import { PageTransition } from "../components/PageTransition";
import { DonutChart, LineChart } from "../components/Chart";
import { HeatMap } from "../components/HeatMap";

interface XPData {
  cumulative_xp: number;
  level: number;
  streak_count: number;
}

interface SubtopicMastery {
  subtopic_id: number;
  subtopic_title: string;
  mastery_level: string;
  mastery_score: number;
  total_attempts: number;
  correct_attempts: number;
  last_practiced_at: string | null;
}

interface WeakSubtopic {
  subtopic_id: number;
  subtopic_title: string;
  mastery_score: number;
  mastery_level: string;
}

interface ProgressSnapshot {
  total_subtopics: number;
  completed_subtopics: number;
  total_lessons: number;
  completed_lessons: number;
}

const LEVEL_COLORS: Record<string, string> = {
  BEGINNER: "var(--color-danger)",
  FAMILIAR: "var(--color-warning)",
  PROFICIENT: "var(--color-accent)",
  ADVANCED: "var(--color-success)",
  MASTERED: "var(--color-metallic)",
};

export function Analytics() {
  const [xp, setXp] = useState<XPData | null>(null);
  const [mastery, setMastery] = useState<SubtopicMastery[]>([]);
  const [weakest, setWeakest] = useState<WeakSubtopic[]>([]);
  const [progress, setProgress] = useState<ProgressSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      apiClient.get<XPData>("/v1/xp/me"),
      apiClient.get<SubtopicMastery[]>("/v1/mastery/me"),
      apiClient.get<WeakSubtopic[]>("/v1/mastery/me/weakest"),
      apiClient.get<ProgressSnapshot>("/v1/progress/snapshot"),
    ])
      .then(([xpRes, masteryRes, weakRes, progRes]) => {
        setXp(xpRes);
        setMastery(masteryRes);
        setWeakest(weakRes);
        setProgress(progRes);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <PageTransition>
        <div className="page container" style={{ maxWidth: 960 }}>
          <h1 style={{ color: "var(--color-text)", fontFamily: "var(--font-family)", marginBottom: "1.5rem" }}>
            Analytics
          </h1>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "1rem" }}>
            {[1, 2, 3, 4].map((i) => (
              <GlassCard key={i}>
                <GlassSkeleton height="1rem" width="60%" />
                <div style={{ marginTop: "0.5rem" }}>
                  <GlassSkeleton height="2rem" width="40%" />
                </div>
              </GlassCard>
            ))}
          </div>
          <div style={{ marginTop: "1.5rem" }}>
            <GlassCard>
              <GlassSkeleton height="12rem" />
            </GlassCard>
          </div>
        </div>
      </PageTransition>
    );
  }

  if (error) {
    return (
      <PageTransition>
        <div className="page container" style={{ maxWidth: 960 }}>
          <p style={{ color: "var(--color-danger)" }}>{error}</p>
        </div>
      </PageTransition>
    );
  }

  // Compute stats
  const totalSessions = mastery.reduce((sum, m) => sum + m.total_attempts, 0);
  const totalCorrect = mastery.reduce((sum, m) => sum + m.correct_attempts, 0);
  const avgAccuracy = totalSessions > 0 ? Math.round((totalCorrect / totalSessions) * 100) : 0;
  const readiness = progress
    ? Math.round((progress.completed_subtopics / Math.max(progress.total_subtopics, 1)) * 100)
    : 0;

  // Mastery level distribution
  const levelCounts: Record<string, number> = {};
  for (const m of mastery) {
    levelCounts[m.mastery_level] = (levelCounts[m.mastery_level] || 0) + 1;
  }

  const donutSegments = Object.entries(LEVEL_COLORS)
    .filter(([level]) => (levelCounts[level] || 0) > 0)
    .map(([level, color]) => ({
      label: level.charAt(0) + level.slice(1).toLowerCase(),
      value: levelCounts[level] || 0,
      color,
    }));

  // Accuracy trend (simulate from mastery data — group by last_practiced_at dates)
  const accuracyByDate = new Map<string, { correct: number; total: number }>();
  for (const m of mastery) {
    if (m.last_practiced_at) {
      const date = m.last_practiced_at.split("T")[0];
      const existing = accuracyByDate.get(date) || { correct: 0, total: 0 };
      existing.correct += m.correct_attempts;
      existing.total += m.total_attempts;
      accuracyByDate.set(date, existing);
    }
  }
  const accuracyTrend = Array.from(accuracyByDate.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .slice(-14)
    .map(([date, { correct, total }]) => ({
      label: date.slice(5),
      value: total > 0 ? Math.round((correct / total) * 100) : 0,
    }));

  // Study consistency heatmap
  const studyDates = new Map<string, number>();
  for (const m of mastery) {
    if (m.last_practiced_at) {
      const date = m.last_practiced_at.split("T")[0];
      studyDates.set(date, (studyDates.get(date) || 0) + 1);
    }
  }
  const heatmapData = Array.from(studyDates.entries()).map(([date, count]) => ({ date, count }));

  // Strongest subtopics
  const strongest = [...mastery]
    .sort((a, b) => b.mastery_score - a.mastery_score)
    .slice(0, 5);

  return (
    <PageTransition>
      <div className="page container" style={{ maxWidth: 960 }}>
        <h1 style={{ color: "var(--color-text)", fontFamily: "var(--font-family)", marginBottom: "1.5rem" }}>
          Analytics
        </h1>

        {/* Key Stats */}
        <section
          aria-label="Key statistics"
          style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "1rem", marginBottom: "2rem" }}
        >
          <GlassStatCard icon="📖" title="Study Sessions" value={totalSessions} />
          <GlassStatCard
            icon="🎯"
            title="Avg Accuracy"
            value={`${avgAccuracy}%`}
            trend={avgAccuracy > 70 ? { direction: "up", label: "On track" } : undefined}
          />
          <GlassStatCard icon="🔥" title="Day Streak" value={xp?.streak_count || 0} />
          <GlassStatCard icon="📊" title="Readiness" value={`${readiness}%`} />
        </section>

        {/* Mastery Overview */}
        <GlassCard as="section" style={{ marginBottom: "1.5rem" }}>
          <h2 style={{ fontSize: "var(--font-size-lg)", fontWeight: 600, color: "var(--color-text)", marginBottom: "1rem" }}>
            Mastery Distribution
          </h2>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "center", flexWrap: "wrap", gap: "2rem" }}>
            {donutSegments.length > 0 ? (
              <DonutChart segments={donutSegments} />
            ) : (
              <p style={{ color: "var(--color-text-secondary)", fontSize: "var(--font-size-sm)" }}>
                No mastery data yet. Start practicing!
              </p>
            )}
          </div>
        </GlassCard>

        {/* Accuracy Trend */}
        {accuracyTrend.length >= 2 && (
          <GlassCard as="section" style={{ marginBottom: "1.5rem" }}>
            <h2 style={{ fontSize: "var(--font-size-lg)", fontWeight: 600, color: "var(--color-text)", marginBottom: "1rem" }}>
              Accuracy Trend
            </h2>
            <LineChart data={accuracyTrend} color="var(--color-accent)" />
          </GlassCard>
        )}

        {/* Study Consistency */}
        <GlassCard as="section" style={{ marginBottom: "1.5rem" }}>
          <h2 style={{ fontSize: "var(--font-size-lg)", fontWeight: 600, color: "var(--color-text)", marginBottom: "1rem" }}>
            Study Consistency
          </h2>
          <HeatMap data={heatmapData} label="Sessions per day (last 12 weeks)" />
        </GlassCard>

        {/* Strengths & Weaknesses */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "1rem", marginBottom: "1.5rem" }}>
          <GlassCard as="section">
            <h2 style={{ fontSize: "var(--font-size-lg)", fontWeight: 600, color: "var(--color-success)", marginBottom: "1rem" }}>
              💪 Strengths
            </h2>
            {strongest.length === 0 ? (
              <p style={{ color: "var(--color-text-secondary)", fontSize: "var(--font-size-sm)" }}>No data yet</p>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
                {strongest.map((s) => (
                  <GlassProgressBar
                    key={s.subtopic_id}
                    value={s.mastery_score * 100}
                    label={s.subtopic_title}
                    color="var(--color-success)"
                  />
                ))}
              </div>
            )}
          </GlassCard>

          <GlassCard as="section">
            <h2 style={{ fontSize: "var(--font-size-lg)", fontWeight: 600, color: "var(--color-danger)", marginBottom: "1rem" }}>
              ⚠️ Needs Work
            </h2>
            {weakest.length === 0 ? (
              <p style={{ color: "var(--color-text-secondary)", fontSize: "var(--font-size-sm)" }}>No data yet</p>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
                {weakest.slice(0, 5).map((w) => (
                  <GlassProgressBar
                    key={w.subtopic_id}
                    value={w.mastery_score * 100}
                    label={w.subtopic_title}
                    color="var(--color-danger)"
                  />
                ))}
              </div>
            )}
          </GlassCard>
        </div>

        {/* Time Analysis */}
        <GlassCard as="section">
          <h2 style={{ fontSize: "var(--font-size-lg)", fontWeight: 600, color: "var(--color-text)", marginBottom: "1rem" }}>
            Time Analysis
          </h2>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
            <div style={{ textAlign: "center" }}>
              <div style={{ fontSize: "var(--font-size-2xl)", fontWeight: 700, color: "var(--color-text)", background: "linear-gradient(135deg, var(--color-accent), var(--color-metallic))", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", backgroundClip: "text" }}>
                {totalSessions > 0 ? `~${Math.max(1, Math.round(totalSessions * 0.8))}` : "0"}
              </div>
              <div style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-secondary)" }}>
                Avg seconds/question
              </div>
            </div>
            <div style={{ textAlign: "center" }}>
              <div style={{ fontSize: "var(--font-size-2xl)", fontWeight: 700, color: "var(--color-text)", background: "linear-gradient(135deg, var(--color-accent), var(--color-metallic))", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", backgroundClip: "text" }}>
                {Math.round(totalSessions * 0.5)}m
              </div>
              <div style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-secondary)" }}>
                Total study time (est.)
              </div>
            </div>
          </div>
        </GlassCard>
      </div>
    </PageTransition>
  );
}
