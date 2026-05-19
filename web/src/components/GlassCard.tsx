import { motion } from "framer-motion";
import { useReducedMotion } from "../design-system";

interface GlassCardProps {
  children: React.ReactNode;
  className?: string;
  blur?: "sm" | "md" | "lg";
  hoverable?: boolean;
  onClick?: () => void;
  style?: React.CSSProperties;
  as?: "div" | "section" | "article";
}

export function GlassCard({
  children,
  className = "",
  blur = "md",
  hoverable = false,
  onClick,
  style,
  as = "div",
}: GlassCardProps) {
  const reducedMotion = useReducedMotion();
  const Component = motion[as];

  const hoverAnimation =
    hoverable && !reducedMotion
      ? { scale: 1.01, boxShadow: "var(--shadow-glow)" }
      : {};

  const tapAnimation =
    hoverable && !reducedMotion ? { scale: 0.99 } : {};

  return (
    <Component
      className={`glass-${blur} glass-card ${className}`}
      style={{ position: "relative", padding: "1.5rem", willChange: hoverable ? "transform" : undefined, ...style }}
      whileHover={hoverAnimation}
      whileTap={onClick ? tapAnimation : undefined}
      onClick={onClick}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={
        onClick
          ? (e: React.KeyboardEvent) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onClick();
              }
            }
          : undefined
      }
      transition={{ type: "spring", stiffness: 300, damping: 20 }}
    >
      {children}
    </Component>
  );
}
