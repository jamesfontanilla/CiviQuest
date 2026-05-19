interface GlassProgressBarProps {
  value: number;
  max?: number;
  label?: string;
  animated?: boolean;
  height?: number;
  color?: string;
}

export function GlassProgressBar({
  value,
  max = 100,
  label,
  animated = false,
  height = 8,
  color,
}: GlassProgressBarProps) {
  const percentage = Math.min(Math.max((value / max) * 100, 0), 100);

  return (
    <div className="glass-progress" role="progressbar" aria-valuenow={value} aria-valuemin={0} aria-valuemax={max} aria-label={label}>
      {label && (
        <span style={{ display: "block", marginBottom: "0.25rem", fontSize: "var(--font-size-xs)", color: "var(--color-text-secondary)" }}>
          {label}
        </span>
      )}
      <div
        style={{
          height: `${height}px`,
          borderRadius: "var(--radius-full)",
          background: "var(--glass-bg-subtle)",
          border: "1px solid var(--glass-border-light)",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            width: `${percentage}%`,
            height: "100%",
            borderRadius: "var(--radius-full)",
            background: color || "linear-gradient(90deg, var(--color-accent), var(--color-metallic))",
            boxShadow: "inset 0 1px 2px rgba(255, 255, 255, 0.2), 0 0 8px rgba(212, 165, 116, 0.2)",
            transition: "width var(--transition-normal)",
            animation: animated ? "gentle-pulse 2s ease-in-out infinite" : "none",
          }}
        />
      </div>
    </div>
  );
}
