import { motion } from "framer-motion";
import { springDefault } from "../design-system";

interface GlassButtonProps {
  children: React.ReactNode;
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md" | "lg";
  disabled?: boolean;
  loading?: boolean;
  onClick?: () => void;
  type?: "button" | "submit" | "reset";
  className?: string;
  style?: React.CSSProperties;
  "aria-label"?: string;
}

export function GlassButton({
  children,
  variant = "primary",
  size = "md",
  disabled = false,
  loading = false,
  onClick,
  type = "button",
  className = "",
  style,
  ...rest
}: GlassButtonProps) {
  const sizeStyles: Record<string, React.CSSProperties> = {
    sm: { padding: "0.375rem 0.75rem", fontSize: "var(--font-size-sm)" },
    md: { padding: "0.625rem 1.25rem", fontSize: "var(--font-size-base)" },
    lg: { padding: "0.875rem 1.75rem", fontSize: "var(--font-size-lg)" },
  };

  return (
    <motion.button
      className={`btn-glass btn-glass-${variant} ${className}`}
      style={{ ...sizeStyles[size], ...style }}
      onClick={onClick}
      type={type}
      disabled={disabled || loading}
      whileHover={!disabled && !loading ? { scale: 1.02 } : undefined}
      whileTap={!disabled && !loading ? { scale: 0.97 } : undefined}
      transition={springDefault}
      {...rest}
    >
      {loading ? (
        <span
          className="btn-spinner"
          aria-hidden="true"
          style={{
            display: "inline-block",
            width: "1em",
            height: "1em",
            border: "2px solid currentColor",
            borderTopColor: "transparent",
            borderRadius: "50%",
            animation: "spin 0.6s linear infinite",
          }}
        />
      ) : (
        children
      )}
    </motion.button>
  );
}
