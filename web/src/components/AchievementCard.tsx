interface AchievementCardProps {
  title: string;
  description: string;
  icon: string | null;
  rarity: "COMMON" | "RARE" | "EPIC" | "LEGENDARY";
  xpReward: number;
  grantedAt: string | null;
  unlocked?: boolean;
}

const RARITY_COLORS: Record<string, string> = {
  COMMON: "var(--color-muted)",
  RARE: "#64B5F6",
  EPIC: "#CE93D8",
  LEGENDARY: "var(--color-accent)",
};

const RARITY_LABELS: Record<string, string> = {
  COMMON: "Common",
  RARE: "Rare",
  EPIC: "Epic",
  LEGENDARY: "Legendary",
};

export function AchievementCard({
  title,
  description,
  icon,
  rarity,
  xpReward,
  grantedAt,
  unlocked = false,
}: AchievementCardProps) {
  const borderColor = RARITY_COLORS[rarity] || RARITY_COLORS.COMMON;

  return (
    <div
      style={{
        padding: "1rem",
        borderRadius: "var(--radius-md)",
        border: `2px solid ${borderColor}`,
        background: unlocked ? "var(--glass-bg-medium)" : "var(--glass-bg-subtle)",
        backdropFilter: "var(--glass-blur-sm)",
        WebkitBackdropFilter: "var(--glass-blur-sm)",
        boxShadow: unlocked ? "var(--shadow-glow)" : "var(--shadow-diffused)",
        opacity: unlocked ? 1 : 0.6,
        position: "relative",
        overflow: "hidden",
        transition: "transform var(--transition-fast), box-shadow var(--transition-fast)",
      }}
      aria-label={`${title} achievement, ${RARITY_LABELS[rarity]}, ${unlocked ? "unlocked" : "locked"}`}
    >
      {/* Unlock animation overlay */}
      {unlocked && (
        <div
          style={{
            position: "absolute",
            top: 0,
            right: 0,
            padding: "0.125rem 0.5rem",
            background: borderColor,
            color: "var(--color-background-warm)",
            fontSize: "0.625rem",
            fontWeight: 700,
            borderBottomLeftRadius: "var(--radius-sm)",
          }}
        >
          {RARITY_LABELS[rarity]}
        </div>
      )}

      <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
        <span style={{ fontSize: "2rem" }} role="img" aria-hidden="true">
          {icon || "🏅"}
        </span>
        <div style={{ flex: 1 }}>
          <h3 style={{ fontSize: "0.9375rem", fontWeight: 600, marginBottom: "0.125rem", color: "var(--color-text)" }}>{title}</h3>
          <p style={{ fontSize: "0.8125rem", color: "var(--color-text-secondary)", margin: 0 }}>{description}</p>
          {xpReward > 0 && (
            <span style={{ fontSize: "0.75rem", color: "var(--color-accent)", fontWeight: 600 }}>
              +{xpReward} XP
            </span>
          )}
        </div>
      </div>

      {grantedAt && (
        <div style={{ marginTop: "0.5rem", fontSize: "0.75rem", color: "var(--color-text-secondary)" }}>
          Unlocked {new Date(grantedAt).toLocaleDateString()}
        </div>
      )}
    </div>
  );
}
