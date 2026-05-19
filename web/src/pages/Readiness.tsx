import { useState, useEffect } from "react";
import { apiClient } from "../api/client";
import { GlassCard } from "../components/GlassCard";
import { GlassBadge } from "../components/GlassBadge";
import { GlassSkeleton } from "../components/GlassSkeleton";
import { PageTransition } from "../components/PageTransition";

interface ReadinessData {
  passing_probability: number;
  predicted_score: number;
  readiness_percentage: number;
  recommended_hours_remaining: number;
  strengths: string[];
  weaknesses: string[];
  confidence_level: string;
}

const CONFIDENCE_COLORS: Record<string, string> = {
  low: "var(--color-danger)",
  moderate: "var(--color-warning)",
  high: "var(--color-success)",
  very_high: "var(--color-info)",
};

const CONFIDENCE_BADGE_COLORS: Record<string, "danger" | "warning" | "success" | "accent"> = {
  low: "danger",
  moderate: "warning",
  high: "success",
  very_high: "accent",
};

export function Readiness() {
  const [data, setData] = useState<ReadinessData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiClient.get<ReadinessData>("/v1/planner/readiness/me")
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <PageTransition>
        <main className="page container" style={{ maxWidth: 720 }}>
          <h1 style={{ color: "var(--color-text)", fontFamily: "var(--font-family)", marginBottom: "1.5rem" }}>
            📊 Exam Readiness
          </h1>
          <GlassCard style={{ display: "flex", justifyContent: "center", marginBottom: "1.5rem" }}>
            <GlassSkeleton width="160px" height="160px" borderRadius="50%" />
          </GlassCard>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "1rem" }}>
            {[1, 2, 3, 4].map((i) => (
              <GlassCard key={i}>
                <GlassSkeleton height="2rem" width="60%" />
                <div style={{ marginTop: "0.5rem" }}>
                  <GlassSkeleton height="0.75rem" width="80%" />
                </div>
              </GlassCard>
            ))}
          </div>
        </main>
      </PageTransition>
    );
  }

  if (!data) {
    return (
      <PageTransition>
        <main className="page container" style={{ maxWidth: 720 }}>
          <GlassCard>
            <p style={{ color: "var(--color-text-secondary)", textAlign: "center" }}>
              Unable to load readiness data.
            </p>
          </GlassCard>
        </main>
      </PageTransition>
    );
  }

  const confidenceColor = CONFIDENCE_COLORS[data.confidence_level] || "var(--color-text-muted)";

  return (
    <PageTransition>
      <main className="page container" style={{ maxWidth: 720 }}>
        <h1 style={{ color: "var(--color-text)", fontFamily: "var(--font-family)", marginBottom: "1.5rem" }}>
          📊 Exam Readiness
        </h1>

        {/* Big readiness circle */}
        <GlassCard style={{ display: "flex", justifyContent: "center", marginBottom: "1.5rem" }}>
          <div style={{
            width: 160, height: 160, borderRadius: "50%",
            border: `8px solid ${confidenceColor}`,
            display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
          }}>
            <span style={{ fontSize: "var(--font-size-3xl)", fontWeight: 700, color: "var(--color-text)" }}>
              {data.readiness_percentage}%
            </span>
            <span style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-secondary)" }}>Ready</span>
          </div>
        </GlassCard>

        {/* Stats grid */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "1rem", marginBottom: "1.5rem" }}>
          <GlassCard style={{ textAlign: "center" }}>
            <p style={{ fontSize: "var(--font-size-2xl)", fontWeight: 700, color: "var(--color-text)" }}>
              {(data.passing_probability * 100).toFixed(1)}%
            </p>
            <p style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-secondary)" }}>Passing Probability</p>
          </GlassCard>
          <GlassCard style={{ textAlign: "center" }}>
            <p style={{ fontSize: "var(--font-size-2xl)", fontWeight: 700, color: "var(--color-text)" }}>
              {(data.predicted_score * 100).toFixed(1)}%
            </p>
            <p style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-secondary)" }}>Predicted Score</p>
          </GlassCard>
          <GlassCard style={{ textAlign: "center" }}>
            <p style={{ fontSize: "var(--font-size-2xl)", fontWeight: 700, color: "var(--color-text)" }}>
              {data.recommended_hours_remaining}h
            </p>
            <p style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-secondary)" }}>Recommended Hours</p>
          </GlassCard>
          <GlassCard style={{ textAlign: "center" }}>
            <GlassBadge
              label={data.confidence_level.replace("_", " ")}
              color={CONFIDENCE_BADGE_COLORS[data.confidence_level] || "primary"}
              size="md"
            />
            <p style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-secondary)", marginTop: "0.5rem" }}>
              Confidence Level
            </p>
          </GlassCard>
        </div>

        {/* Strengths and Weaknesses */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
          <GlassCard as="section">
            <h3 style={{ fontSize: "var(--font-size-sm)", fontWeight: 600, color: "var(--color-success)", marginBottom: "0.5rem" }}>
              💪 Strengths
            </h3>
            {data.strengths.length === 0 ? (
              <p style={{ fontSize: "var(--font-size-sm)", color: "var(--color-text-secondary)" }}>
                Keep studying to build strengths!
              </p>
            ) : (
              <ul style={{ paddingLeft: "1rem", fontSize: "var(--font-size-sm)", color: "var(--color-text)" }}>
                {data.strengths.map((s, i) => <li key={i} style={{ marginBottom: "0.25rem" }}>{s}</li>)}
              </ul>
            )}
          </GlassCard>
          <GlassCard as="section">
            <h3 style={{ fontSize: "var(--font-size-sm)", fontWeight: 600, color: "var(--color-danger)", marginBottom: "0.5rem" }}>
              ⚠️ Weaknesses
            </h3>
            {data.weaknesses.length === 0 ? (
              <p style={{ fontSize: "var(--font-size-sm)", color: "var(--color-text-secondary)" }}>
                No weak areas detected!
              </p>
            ) : (
              <ul style={{ paddingLeft: "1rem", fontSize: "var(--font-size-sm)", color: "var(--color-text)" }}>
                {data.weaknesses.map((w, i) => <li key={i} style={{ marginBottom: "0.25rem" }}>{w}</li>)}
              </ul>
            )}
          </GlassCard>
        </div>
      </main>
    </PageTransition>
  );
}
