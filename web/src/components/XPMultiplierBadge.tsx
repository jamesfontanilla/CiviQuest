import { useState, useEffect } from "react";

interface XPMultiplierBadgeProps {
  multiplier: number;
  reason: string;
  expiresAt: string;
}

export function XPMultiplierBadge({ multiplier, reason, expiresAt }: XPMultiplierBadgeProps) {
  const [timeLeft, setTimeLeft] = useState("");

  useEffect(() => {
    function update() {
      const diff = new Date(expiresAt).getTime() - Date.now();
      if (diff <= 0) {
        setTimeLeft("Expired");
        return;
      }
      const hours = Math.floor(diff / (1000 * 60 * 60));
      const minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
      setTimeLeft(hours > 0 ? `${hours}h ${minutes}m` : `${minutes}m`);
    }
    update();
    const interval = setInterval(update, 60000);
    return () => clearInterval(interval);
  }, [expiresAt]);

  const label = reason.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

  return (
    <div
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: "0.375rem",
        padding: "0.375rem 0.75rem",
        borderRadius: "var(--radius-full, 9999px)",
        background: "linear-gradient(135deg, var(--color-primary), var(--color-primary-dark, #4f46e5))",
        color: "#fff",
        fontSize: "0.8125rem",
        fontWeight: 600,
        animation: "glow 2s ease-in-out infinite",
      }}
      aria-label={`${multiplier}x XP multiplier from ${label}, ${timeLeft} remaining`}
    >
      <span style={{ fontSize: "1rem" }}>⚡</span>
      <span>{multiplier}x XP</span>
      <span style={{ opacity: 0.8, fontSize: "0.75rem" }}>({timeLeft})</span>
      <style>{`
        @keyframes glow {
          0%, 100% { box-shadow: 0 0 4px rgba(99, 102, 241, 0.4); }
          50% { box-shadow: 0 0 12px rgba(99, 102, 241, 0.7); }
        }
      `}</style>
    </div>
  );
}
