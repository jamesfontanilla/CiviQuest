/**
 * Voice/TTS controls — read aloud, speed control, stop.
 * Uses the browser's built-in SpeechSynthesis API via useSpeech hook.
 */

import { useState } from "react";
import { useSpeech } from "../hooks/useSpeech";

interface VoiceControlsProps {
  /** The text content to read aloud */
  text: string;
  /** Compact mode shows only the read button */
  compact?: boolean;
}

const SPEED_OPTIONS = [0.75, 1.0, 1.25, 1.5] as const;

export function VoiceControls({ text, compact = false }: VoiceControlsProps) {
  const { speak, stop, speaking } = useSpeech();
  const [rate, setRate] = useState(1.0);
  const [autoRead, setAutoRead] = useState(false);

  const handleRead = () => {
    if (speaking) {
      stop();
    } else {
      speak(text, { rate });
    }
  };

  if (compact) {
    return (
      <button
        className="btn-glass"
        onClick={handleRead}
        aria-label={speaking ? "Stop reading" : "Read aloud"}
        title={speaking ? "Stop reading" : "Read aloud"}
        style={{ fontSize: "0.875rem", padding: "0.25rem 0.5rem" }}
      >
        {speaking ? "⏹️ Stop" : "🔊 Read Aloud"}
      </button>
    );
  }

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: "0.5rem",
        padding: "0.5rem",
        borderRadius: "var(--radius-sm)",
        background: "var(--color-surface)",
        flexWrap: "wrap",
      }}
      role="toolbar"
      aria-label="Voice controls"
    >
      <button
        className="btn-glass"
        onClick={handleRead}
        aria-label={speaking ? "Stop reading" : "Read aloud"}
        style={{ fontSize: "0.875rem", padding: "0.375rem 0.625rem" }}
      >
        {speaking ? "⏹️ Stop" : "🔊 Read Aloud"}
      </button>

      <div style={{ display: "flex", alignItems: "center", gap: "0.25rem" }}>
        <span style={{ fontSize: "0.75rem", color: "var(--color-text-secondary)" }}>
          Speed:
        </span>
        {SPEED_OPTIONS.map((s) => (
          <button
            key={s}
            className={`btn-glass ${rate === s ? "btn-glass-primary" : ""}`}
            onClick={() => setRate(s)}
            aria-label={`Speed ${s}x`}
            aria-pressed={rate === s}
            style={{ fontSize: "0.75rem", padding: "0.25rem 0.375rem", minWidth: "auto" }}
          >
            {s}x
          </button>
        ))}
      </div>

      <label
        style={{
          display: "flex",
          alignItems: "center",
          gap: "0.25rem",
          fontSize: "0.75rem",
          color: "var(--color-text-secondary)",
          cursor: "pointer",
        }}
      >
        <input
          type="checkbox"
          checked={autoRead}
          onChange={(e) => setAutoRead(e.target.checked)}
          aria-label="Auto-read new content"
        />
        Auto-read
      </label>
    </div>
  );
}
