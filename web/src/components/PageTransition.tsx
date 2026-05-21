import { useRef } from "react";
import { motion } from "framer-motion";
import { slideUp, useReducedMotion } from "../design-system";

interface PageTransitionProps {
  children: React.ReactNode;
}

export function PageTransition({ children }: PageTransitionProps) {
  const reducedMotion = useReducedMotion();
  const isFirstRender = useRef(true);

  if (reducedMotion) {
    return <>{children}</>;
  }

  // Skip the enter animation on the very first mount so the hero
  // (and any above-fold content) is visible immediately on page load.
  const skipInitial = isFirstRender.current;
  if (isFirstRender.current) {
    isFirstRender.current = false;
  }

  return (
    <motion.div
      initial={skipInitial ? false : slideUp.initial}
      animate={slideUp.animate}
      exit={slideUp.exit}
      transition={slideUp.transition}
    >
      {children}
    </motion.div>
  );
}
