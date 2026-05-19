interface HeatMapProps {
  /** Array of { date: "YYYY-MM-DD", count: number } */
  data: { date: string; count: number }[];
  label?: string;
}

export function HeatMap({ data, label = "Study Activity" }: HeatMapProps) {
  const cellSize = 14;
  const gap = 2;
  const weeks = 12;
  const days = 7;

  // Build a map of date -> count
  const countMap = new Map<string, number>();
  for (const d of data) {
    countMap.set(d.date, d.count);
  }

  // Generate last 12 weeks of dates
  const today = new Date();
  const cells: { date: string; count: number; col: number; row: number }[] = [];

  for (let w = weeks - 1; w >= 0; w--) {
    for (let d = 0; d < days; d++) {
      const date = new Date(today);
      date.setDate(today.getDate() - (w * 7 + (today.getDay() - d)));
      if (date > today) continue;
      const dateStr = date.toISOString().split("T")[0];
      cells.push({
        date: dateStr,
        count: countMap.get(dateStr) || 0,
        col: weeks - 1 - w,
        row: d,
      });
    }
  }

  const maxCount = Math.max(...cells.map((c) => c.count), 1);

  function getColor(count: number): string {
    if (count === 0) return "var(--color-surface)";
    const intensity = Math.min(count / maxCount, 1);
    if (intensity < 0.25) return "rgba(212, 165, 116, 0.2)";
    if (intensity < 0.5) return "rgba(212, 165, 116, 0.4)";
    if (intensity < 0.75) return "rgba(212, 165, 116, 0.65)";
    return "rgba(212, 165, 116, 0.9)";
  }

  const width = weeks * (cellSize + gap) + gap;
  const height = days * (cellSize + gap) + gap;

  return (
    <div
      style={{
        padding: "1rem",
        background: "var(--glass-bg-subtle)",
        backdropFilter: "var(--glass-blur-sm)",
        WebkitBackdropFilter: "var(--glass-blur-sm)",
        border: "1px solid var(--glass-border-light)",
        borderRadius: "var(--radius-md)",
      }}
    >
      {label && (
        <div style={{ fontSize: "0.8125rem", color: "var(--color-text-secondary)", marginBottom: "0.5rem" }}>
          {label}
        </div>
      )}
      <svg
        width={width}
        height={height}
        role="img"
        aria-label={`${label} heat map showing last ${weeks} weeks`}
        style={{ display: "block" }}
      >
        {cells.map((cell, i) => (
          <rect
            key={i}
            x={cell.col * (cellSize + gap) + gap}
            y={cell.row * (cellSize + gap) + gap}
            width={cellSize}
            height={cellSize}
            rx={3}
            fill={getColor(cell.count)}
            stroke="var(--glass-border-medium)"
            strokeWidth={0.5}
          >
            <title>{`${cell.date}: ${cell.count} session${cell.count !== 1 ? "s" : ""}`}</title>
          </rect>
        ))}
      </svg>
      <div style={{ display: "flex", alignItems: "center", gap: "0.25rem", marginTop: "0.375rem", fontSize: "0.6875rem", color: "var(--color-text-muted)" }}>
        <span>Less</span>
        {[0, 0.25, 0.5, 0.75, 1].map((intensity, i) => (
          <span
            key={i}
            style={{
              width: 10,
              height: 10,
              borderRadius: 2,
              background: intensity === 0 ? "var(--color-surface)" : `rgba(212, 165, 116, ${intensity * 0.9})`,
              border: "0.5px solid var(--glass-border-medium)",
              display: "inline-block",
            }}
          />
        ))}
        <span>More</span>
      </div>
    </div>
  );
}
