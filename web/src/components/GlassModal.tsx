import { useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { scaleIn, springGentle } from "../design-system";

interface GlassModalProps {
  isOpen: boolean;
  onClose: () => void;
  title?: string;
  children: React.ReactNode;
  size?: "sm" | "md" | "lg";
}

export function GlassModal({ isOpen, onClose, title, children, size = "md" }: GlassModalProps) {
  const modalRef = useRef<HTMLDivElement>(null);

  const sizeStyles: Record<string, React.CSSProperties> = {
    sm: { maxWidth: "400px" },
    md: { maxWidth: "560px" },
    lg: { maxWidth: "720px" },
  };

  useEffect(() => {
    if (!isOpen) return;

    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();

      // Focus trap
      if (e.key === "Tab" && modalRef.current) {
        const focusable = modalRef.current.querySelectorAll<HTMLElement>(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
        );
        if (focusable.length === 0) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];

        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  // Focus the modal when it opens
  useEffect(() => {
    if (isOpen && modalRef.current) {
      modalRef.current.focus();
    }
  }, [isOpen]);

  return (
    <AnimatePresence>
      {isOpen && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            zIndex: "var(--z-modal)" as unknown as number,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: "1rem",
          }}
        >
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            style={{
              position: "absolute",
              inset: 0,
              background: "rgba(26, 15, 10, 0.6)",
              backdropFilter: "blur(8px)",
              WebkitBackdropFilter: "blur(8px)",
            }}
          />

          {/* Modal Content */}
          <motion.div
            ref={modalRef}
            className="glass-lg"
            role="dialog"
            aria-modal="true"
            aria-label={title}
            tabIndex={-1}
            initial={scaleIn.initial}
            animate={scaleIn.animate}
            exit={scaleIn.exit}
            transition={springGentle}
            style={{
              position: "relative",
              width: "100%",
              padding: "2rem",
              ...sizeStyles[size],
            }}
          >
            {title && (
              <h2 style={{ margin: "0 0 1rem", fontSize: "var(--font-size-xl)", fontWeight: 600, color: "var(--color-text)" }}>
                {title}
              </h2>
            )}
            {children}
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
}
