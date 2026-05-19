/**
 * Wellness/burnout prevention alert banner.
 * Shows a gentle, dismissible alert when cognitive fatigue is detected.
 * Reappears after 30 minutes if conditions persist.
 */

import { useState, useEffect, useCallback } from "react";
import { apiClient } from "../api/client";

interface WellnessData {
  is_fatigued: boolean;
  fatigue_level: string;
  message: string;
  suggestion: string;
}

const RECHECK_INTERVAL_MS = 30 * 60 * 1000; // 30 minutes

export function WellnessAlert() {
  const [wellness, setWellness] = useState<WellnessData | null>(null);
  const [dismissed, setDismissed] = useState(false);

  const fetchWellness = useCallback(async () => {
    try {
      const data = await apiClient.get<WellnessData>("/v1/focus/wellness/me");
      setWellness(data);
      if (data.is_fatigued) {
        setDismissed(false);
      }
    } catch {
      // Silent fail — wellness is non-critical
    }
  }, []);

  useEffect(() => {
    fetchWellness();
    const interval = setInterval(fetchWellness, RECHECK_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [fetchWellness]);

  if (!wellness || !wellness.is_fatigued || dismissed) {
    return null;
  }

  const bgColor =
    wellness.fatigue_level === "high"
      ? "var(--color-warning-light, #fff3cd)"
      : "var(--color-info-light, #d1ecf1)";

  const borderColor =
    wellness.fatigue_level === "high"
      ? "var(--color-warning, #ffc107)"
      : "var(--color-info, #17a2b8)";

  return (
    <div
      role="alert"
      aria-live="polite"
      style={{
        padding: "0.875rem 1.25rem",
        borderRadius: "var(--radius-md)",
        background: bgColor,
        border: `1px solid ${borderColor}`,
        marginBottom: "1rem",
        display: "flex",
        justifyContent: "space-between",
        alignItems: "flex-start",
        gap: "0.75rem",
      }}
    >
      <div>
        <p style={{ margin: 0, fontWeight: 500, fontSize: "0.9375rem" }}>
          {wellness.message}
        </p>
        {wellness.suggestion === "take_break" && (
          <p style={{ margin: "0.5rem 0 0", fontSize: "0.8125rem", color: "var(--color-text-secondary)" }}>
            Try starting a focus session with a built-in break! ⏱️
          </p>
        )}
      </div>
      <button
        className="btn-glass"
        onClick={() => setDismissed(true)}
        aria-label="Dismiss wellness alert"
        style={{ padding: "0.25rem 0.5rem", fontSize: "1rem", flexShrink: 0 }}
      >
        ✕
      </button>
    </div>
  );
}
