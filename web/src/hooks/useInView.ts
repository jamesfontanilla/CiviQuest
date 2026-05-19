import { useState, useEffect, useRef, type RefObject } from "react";

/**
 * Hook that uses IntersectionObserver to detect when an element enters the viewport.
 * Used for lazy rendering of below-fold glass surfaces to avoid unnecessary
 * backdrop-filter GPU compositing on off-screen elements.
 */
export function useInView(options?: IntersectionObserverInit): [RefObject<HTMLDivElement>, boolean] {
  const ref = useRef<HTMLDivElement>(null!);
  const [isInView, setIsInView] = useState(false);

  useEffect(() => {
    const element = ref.current;
    if (!element) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setIsInView(true);
          // Once visible, stop observing — no need to re-hide
          observer.unobserve(element);
        }
      },
      { rootMargin: "200px", ...options }
    );

    observer.observe(element);
    return () => observer.disconnect();
  }, [options]);

  return [ref, isInView];
}
