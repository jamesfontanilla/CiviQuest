import { useState, useEffect } from "react";

// --- Spring Presets ---
export const springDefault = { type: "spring" as const, stiffness: 300, damping: 20 };
export const springGentle = { type: "spring" as const, stiffness: 200, damping: 25 };
export const springBouncy = { type: "spring" as const, stiffness: 400, damping: 15 };

// --- Animation Variants ---
export const fadeIn = {
  initial: { opacity: 0 },
  animate: { opacity: 1 },
  exit: { opacity: 0 },
  transition: { duration: 0.3 },
};

export const slideUp = {
  initial: { opacity: 0, y: 12 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -8 },
  transition: springDefault,
};

export const slideDown = {
  initial: { opacity: 0, y: -12 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: 12 },
  transition: springDefault,
};

export const scaleIn = {
  initial: { opacity: 0, scale: 0.95 },
  animate: { opacity: 1, scale: 1 },
  exit: { opacity: 0, scale: 0.95 },
  transition: springGentle,
};

export const staggerContainer = {
  animate: { transition: { staggerChildren: 0.06 } },
};

export const staggerItem = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0 },
  transition: springDefault,
};

// --- Hooks ---
export function useReducedMotion(): boolean {
  const [reducedMotion, setReducedMotion] = useState(false);

  useEffect(() => {
    const mediaQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReducedMotion(mediaQuery.matches);

    function handleChange(event: MediaQueryListEvent) {
      setReducedMotion(event.matches);
    }

    mediaQuery.addEventListener("change", handleChange);
    return () => mediaQuery.removeEventListener("change", handleChange);
  }, []);

  return reducedMotion;
}

export function useMotionVariants(variants: Record<string, unknown>): Record<string, unknown> {
  const reducedMotion = useReducedMotion();

  if (reducedMotion) {
    return {
      ...variants,
      transition: { duration: 0 },
    };
  }

  return variants;
}
