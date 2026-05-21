import { motion } from "framer-motion";
import { slideUp, useReducedMotion } from "../design-system";

// Module-level flag — survives component remounts.
// On the very first page load, skip the enter animation so above-fold
// content (hero) is visible immediately. Subsequent navigations animate.
let isInitialPageLoad = true;

interface PageTransitionProps {
  children: React.ReactNode;
}

export function PageTransition({ children }: PageTransitionProps) {
  const reducedMotion = useReducedMotion();

  if (reducedMotion) {
    return <>{children}</>;
  }

  const skipInitial = isInitialPageLoad;
  if (isInitialPageLoad) {
    isInitialPageLoad = false;
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
