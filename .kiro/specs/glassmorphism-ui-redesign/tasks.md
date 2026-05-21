# Implementation Plan: Glassmorphism UI Redesign

## Overview

This plan transforms the CSNexus CSE Reviewer frontend from its current flat UI into a premium Apple-inspired glassmorphism interface. The migration follows a bottom-up approach: design system foundation → glass components → app shell → page migrations → cleanup. Each task builds incrementally so the app remains functional throughout.

## Tasks

- [x] 1. Set up design system foundation
  - [x] 1.1 Install Framer Motion dependency
    - Add `framer-motion` as a production dependency in `web/package.json`
    - Run install to update lockfile
    - _Requirements: 14.1_

  - [x] 1.2 Create `web/src/design-system/tokens.css`
    - Define all CSS custom properties for the Brown_Palette (primary, secondary, accent, surface, muted, highlight, metallic, background, background-warm)
    - Define text color tokens (text, text-secondary, text-muted)
    - Define semantic color tokens (success, warning, danger, info)
    - Define glass tokens (blur-sm/md/lg, bg-subtle/medium/strong, border-light/medium/strong)
    - Define warm-tinted shadow tokens (ambient, depth, glow, diffused, inner)
    - Define border-radius tokens (sm, md, lg, xl, full)
    - Define typography tokens (font-family with SF Pro stack, font-size scale from xs to 5xl)
    - Define transition tokens (fast, normal, slow)
    - Define focus-ring token using caramel accent color
    - Define z-index scale (background, content, floating, navbar, modal, toast)
    - _Requirements: 1.1, 1.2, 1.5, 1.6, 1.7_

  - [x] 1.3 Create `web/src/design-system/utilities.css`
    - Implement `.glass-sm`, `.glass-md`, `.glass-lg` utility classes with backdrop-filter, background, border, and border-radius
    - Add `::before` pseudo-element for top-edge highlight on glass surfaces
    - Implement gradient utility classes (`.gradient-primary`, `.gradient-accent`, `.gradient-warm`)
    - Implement `.btn-glass`, `.btn-glass-primary` button utility classes with hover states
    - Add `@supports not (backdrop-filter: blur(10px))` fallback with solid semi-transparent backgrounds
    - Add `@media (prefers-reduced-motion: reduce)` rule to disable all animations/transitions
    - Add responsive glass adjustments for mobile (<640px) with reduced blur and increased opacity
    - _Requirements: 1.3, 10.2, 11.5, 12.4_

  - [x] 1.4 Create `web/src/design-system/animations.css`
    - Define `@keyframes blob-drift-1`, `blob-drift-2`, `blob-drift-3` for ambient background blobs
    - Define `@keyframes glass-shimmer` for skeleton loading
    - Define `@keyframes gentle-pulse` for timer warnings
    - Define `@keyframes grain-shift` for noise texture overlay
    - _Requirements: 2.1, 15.4_

  - [x] 1.5 Create `web/src/design-system/motion.ts`
    - Export spring presets: `springDefault`, `springGentle`, `springBouncy`
    - Export animation variants: `fadeIn`, `slideUp`, `slideDown`, `scaleIn`, `staggerContainer`, `staggerItem`
    - Implement `useReducedMotion` hook that reads `prefers-reduced-motion` media query
    - Implement `useMotionVariants` hook that returns instant transitions when reduced motion is active
    - _Requirements: 14.2, 14.3, 14.5, 4.7_

  - [x] 1.6 Create `web/src/design-system/index.ts`
    - Re-export all motion utilities, spring presets, animation variants, and hooks
    - _Requirements: 14.2_

- [x] 2. Checkpoint - Verify design system foundation
  - Ensure all design system files compile without errors, ask the user if questions arise.

- [x] 3. Build glass component library
  - [x] 3.1 Create `web/src/components/AmbientBackground.tsx` and its CSS
    - Render fixed full-viewport layer with 5 gradient blobs using Brown_Palette colors
    - Add noise texture overlay with SVG filter at low opacity (0.03)
    - Add depth gradient overlay (vignette effect)
    - Apply `aria-hidden="true"` for accessibility
    - Use CSS-only animations (no JS animation loop) with `will-change: transform`
    - Hide blobs 4 and 5 on mobile via CSS media query
    - Disable animations when `prefers-reduced-motion` is set
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 15.1, 15.4_

  - [x] 3.2 Create `web/src/components/GlassCard.tsx`
    - Implement component with `blur`, `hoverable`, `onClick`, `className`, `style`, `as` props
    - Use Framer Motion `motion[as]` for hover scale (1.01) and tap scale (0.99) animations
    - Apply glass utility class based on `blur` prop
    - Add keyboard interaction support (Enter/Space) when `onClick` is provided
    - Respect `useReducedMotion` hook to disable animations
    - _Requirements: 3.1, 3.9, 3.10, 4.2, 12.2_

  - [x] 3.3 Create `web/src/components/GlassButton.tsx`
    - Implement component with `variant`, `size`, `disabled`, `loading`, `onClick`, `type`, `aria-label` props
    - Support variants: primary, secondary, ghost, danger
    - Use Framer Motion for hover (scale 1.02) and tap (scale 0.97) with spring physics
    - Show spinner when loading, disable interactions when disabled/loading
    - _Requirements: 3.2, 4.2, 4.3, 15.3_

  - [x] 3.4 Create `web/src/components/GlassInput.tsx` and its CSS
    - Implement as forwardRef component with `label`, `error`, `icon` props extending InputHTMLAttributes
    - Style with frosted surface, inner shadow, translucent border
    - Add focus glow using accent color
    - Maintain label association via `htmlFor`/`id`
    - Add `aria-invalid` and `aria-describedby` for error states
    - Add `aria-live="polite"` on error message element
    - _Requirements: 3.3, 3.9, 12.5_

  - [x] 3.5 Create `web/src/components/GlassModal.tsx`
    - Implement with `isOpen`, `onClose`, `title`, `children`, `size` props
    - Use Framer Motion `AnimatePresence` for enter/exit animations (scale 0.95→1.0, opacity 0→1)
    - Render blurred backdrop overlay
    - Apply appropriate z-index from depth hierarchy
    - Handle Escape key to close, trap focus within modal
    - _Requirements: 3.4, 4.5_

  - [x] 3.6 Create `web/src/components/GlassProgressBar.tsx`
    - Implement with `value`, `max`, `label`, `animated`, `height`, `color` props
    - Render translucent track with gradient fill using Brown_Palette
    - Add subtle inner glow on the fill
    - Support animated pulse when `animated` is true
    - _Requirements: 3.7_

  - [x] 3.7 Create `web/src/components/GlassBadge.tsx`
    - Implement with `label`, `color`, `size` props
    - Support color variants: primary, success, warning, danger, accent
    - Style with frosted background, soft border, warm-tinted text
    - _Requirements: 3.8_

  - [x] 3.8 Create `web/src/components/GlassSkeleton.tsx`
    - Implement glass-styled loading skeleton with shimmer animation
    - Use `glass-shimmer` keyframe from animations.css
    - Accept `width`, `height`, `borderRadius` props for flexible sizing
    - _Requirements: 7.5, 11.3_

  - [x] 3.9 Create `web/src/components/GlassStatCard.tsx`
    - Implement stat display card using GlassCard as base
    - Accept `title`, `value`, `icon`, `trend` props
    - Style with gradient accent and warm typography
    - _Requirements: 9.5_

  - [x] 3.10 Create `web/src/components/PageTransition.tsx`
    - Wrap children in Framer Motion `motion.div` with `slideUp` variant
    - Check `useReducedMotion` — render children directly without animation wrapper when true
    - _Requirements: 4.4, 4.6, 14.4_

- [x] 4. Checkpoint - Verify glass component library
  - Ensure all glass components compile without TypeScript errors, ask the user if questions arise.

- [x] 5. Implement app shell migration
  - [x] 5.1 Create `web/src/components/GlassNavbar.tsx` and its CSS
    - Implement sticky translucent navbar with backdrop-filter blur
    - Add scroll-triggered opacity transition (transparent → frosted at scrollY > 10px)
    - Implement navigation links with soft hover states and active state indicators
    - Implement mobile hamburger menu with glass-styled dropdown using AnimatePresence + slideDown
    - Close mobile menu on route change
    - Preserve all existing navigation links and route-based active detection
    - Do NOT include DarkModeToggle
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7_

  - [x] 5.2 Create `web/src/components/GlassSidebar.tsx`
    - Implement floating glass navigation panel
    - Style with translucent navigation items and smooth active-state indicators
    - _Requirements: 3.6_

  - [x] 5.3 Replace `web/src/global.css` with design system imports
    - Replace current content with `@import` statements for tokens.css, utilities.css, animations.css
    - Keep reset styles (box-sizing, html, body) updated to use new tokens
    - Update body to use `--color-background-warm` and `--font-family` from new tokens
    - Add warm-tinted `:focus-visible` style with caramel glow ring
    - Add `@media (forced-colors: active)` support for high contrast mode
    - Preserve layout utilities (`.container`, `.page`) updated with new token values
    - Preserve toast styles updated with new token values
    - _Requirements: 1.4, 12.1, 12.3, 12.6_

  - [x] 5.4 Update `web/src/App.tsx` to use new app shell
    - Replace `<Navbar />` with `<GlassNavbar />`
    - Add `<AmbientBackground />` as first child inside `<ToastProvider>` (renders at z-index 0)
    - Wrap `<Routes>` with Framer Motion `<AnimatePresence mode="wait">` for page transitions
    - Add `useLocation` hook and pass `location` as key to Routes for AnimatePresence
    - _Requirements: 2.3, 5.4, 14.4_

- [x] 6. Checkpoint - Verify app shell renders correctly
  - Ensure the app compiles and the ambient background, navbar, and page transitions work, ask the user if questions arise.

- [x] 7. Migrate authentication pages
  - [x] 7.1 Migrate `web/src/pages/auth/Login.tsx`
    - Wrap form content in centered GlassCard with Ambient_Background visible behind
    - Replace form inputs with GlassInput components
    - Replace submit button with GlassButton (primary variant)
    - Add hero typography for logo/heading using design system font stack
    - Wrap page in PageTransition
    - Preserve all existing form validation, API calls, and redirect logic
    - Style error messages with warm-tinted error style
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

  - [x] 7.2 Migrate `web/src/pages/auth/Signup.tsx`
    - Apply same glassmorphism pattern as Login
    - Replace inputs with GlassInput, buttons with GlassButton
    - Wrap in centered GlassCard with PageTransition
    - Preserve all validation and API logic
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

  - [x] 7.3 Migrate `web/src/pages/auth/ForgotPassword.tsx`
    - Apply glassmorphism pattern with GlassCard, GlassInput, GlassButton
    - Wrap in PageTransition
    - Preserve all existing functionality
    - _Requirements: 6.1, 6.2, 6.3, 6.4_

  - [x] 7.4 Migrate `web/src/pages/auth/OTPVerification.tsx`
    - Apply glassmorphism pattern with GlassCard, GlassInput, GlassButton
    - Wrap in PageTransition
    - Preserve all existing OTP logic
    - _Requirements: 6.1, 6.2, 6.3, 6.4_

- [x] 8. Migrate content pages
  - [x] 8.1 Migrate `web/src/pages/content/ModuleList.tsx`
    - Render each module as GlassCard with gradient accent borders
    - Replace progress indicators with GlassProgressBar
    - Add staggered entrance animations using `staggerContainer` and `staggerItem` variants
    - Add hover effects on module cards
    - Replace skeleton loaders with GlassSkeleton
    - Wrap in PageTransition
    - Preserve all data fetching and navigation logic
    - _Requirements: 7.1, 7.5, 10.4_

  - [x] 8.2 Migrate `web/src/pages/content/TopicList.tsx`
    - Render items as GlassCard components with translucent backgrounds
    - Add staggered entrance animations
    - Replace skeleton loaders with GlassSkeleton
    - Wrap in PageTransition
    - Preserve all existing logic
    - _Requirements: 7.2, 7.4, 7.5_

  - [x] 8.3 Migrate `web/src/pages/content/SubtopicList.tsx`
    - Render items as GlassCard components with staggered animations
    - Replace skeleton loaders with GlassSkeleton
    - Wrap in PageTransition
    - Preserve all existing logic
    - _Requirements: 7.2, 7.4, 7.5_

  - [x] 8.4 Migrate `web/src/pages/content/LessonReader.tsx`
    - Render lesson content inside GlassCard with comfortable reading typography (max-width, line-height 1.7)
    - Apply Brown_Palette text colors
    - Replace skeleton loaders with GlassSkeleton
    - Wrap in PageTransition
    - Preserve all data fetching and navigation logic
    - _Requirements: 7.3, 7.4, 7.5_

- [x] 9. Migrate quiz and mock exam pages
  - [x] 9.1 Migrate `web/src/pages/quiz/QuizPlayer.tsx`
    - Render question cards as GlassCard components
    - Style answer options as translucent selectable items with warm glow on selection
    - Replace navigation buttons with GlassButton components
    - Add animated score reveal on completion using scaleIn + stagger
    - Wrap in PageTransition
    - Preserve all timer logic, question navigation, answer submission, and scoring
    - _Requirements: 8.1, 8.3, 8.4, 8.5_

  - [x] 9.2 Migrate `web/src/pages/mock-exam/MockExamPlayer.tsx`
    - Render exam timer as floating Glass_Surface with gradient text
    - Add gentle-pulse animation on timer when time is running low
    - Render question cards as GlassCard components
    - Replace buttons with GlassButton
    - Add animated results display on completion
    - Wrap in PageTransition
    - Preserve all timer logic, navigation, submission, and scoring
    - _Requirements: 8.2, 8.3, 8.4, 8.5_

- [x] 10. Checkpoint - Verify content and quiz pages
  - Ensure all migrated pages compile and render correctly, ask the user if questions arise.

- [x] 11. Migrate dashboard and analytics pages
  - [x] 11.1 Migrate `web/src/pages/Leaderboard.tsx`
    - Render rankings table inside GlassCard with translucent row backgrounds
    - Add subtle hover highlights on rows
    - Wrap in PageTransition
    - Preserve all data fetching and display logic
    - _Requirements: 9.1_

  - [x] 11.2 Migrate `web/src/pages/Analytics.tsx`
    - Render chart containers and stat cards as Glass_Surfaces
    - Use GlassStatCard for stat displays
    - Apply warm-tinted data visualization colors from Brown_Palette
    - Wrap in PageTransition
    - Preserve all data fetching and interactive functionality
    - _Requirements: 9.2, 9.5_

  - [x] 11.3 Migrate `web/src/pages/Profile.tsx`
    - Render user information and settings inside GlassCard components
    - Add gradient accent headers
    - Wrap in PageTransition
    - Preserve all existing functionality
    - _Requirements: 9.3_

  - [x] 11.4 Migrate `web/src/pages/AdminDashboard.tsx`
    - Render admin panels and data tables as Glass_Surfaces
    - Apply appropriate depth hierarchy layering
    - Wrap in PageTransition
    - Preserve all existing functionality
    - _Requirements: 9.4_

  - [x] 11.5 Migrate `web/src/pages/Home.tsx`
    - Restyle feature cards and hero section with GlassCard components
    - Add staggered entrance animations for feature grid
    - Apply gradient accents and warm typography
    - Reflow grid to single-column on mobile
    - Wrap in PageTransition
    - Preserve all existing functionality
    - _Requirements: 10.4_

  - [x] 11.6 Migrate remaining pages (Mastery, Goals, Tournaments, StudyPlan, Readiness, Focus, Tutor)
    - Apply GlassCard, GlassButton, GlassProgressBar, GlassBadge as appropriate
    - Wrap each in PageTransition
    - Preserve all existing functionality
    - _Requirements: 9.5, 9.6_

- [ ] 12. Migrate existing utility components
  - [x] 12.1 Restyle `web/src/components/StatCard.tsx` as Glass_Surface
    - Apply glass styling with Brown_Palette color integration
    - Maintain existing prop interface for backward compatibility
    - _Requirements: 9.5, 3.10_

  - [x] 12.2 Restyle `web/src/components/StreakDisplay.tsx` and `web/src/components/AchievementCard.tsx`
    - Apply glass styling with warm-tinted colors
    - Maintain existing prop interfaces
    - _Requirements: 9.5_

  - [x] 12.3 Restyle `web/src/components/HeatMap.tsx` and `web/src/components/Chart.tsx`
    - Apply Glass_Surface backgrounds to chart containers
    - Update data visualization colors to use Brown_Palette
    - Maintain existing prop interfaces
    - _Requirements: 9.5_

  - [x] 12.4 Update `web/src/context/ToastContext.tsx` toast styles
    - Update toast notifications to use glass styling with warm colors
    - Maintain z-index at toast level (9999)
    - Preserve all existing toast functionality
    - _Requirements: 1.2_

- [x] 13. Checkpoint - Verify all page migrations
  - Ensure all pages compile and render with glassmorphism styling, ask the user if questions arise.

- [x] 14. Theme removal and cleanup
  - [x] 14.1 Remove DarkModeToggle and theme infrastructure
    - Delete `web/src/components/DarkModeToggle.tsx`
    - Remove all imports of DarkModeToggle across the codebase
    - Remove `[data-theme="dark"]` CSS block (already replaced by new global.css)
    - Remove `document.documentElement.setAttribute("data-theme", ...)` calls from any component
    - Remove `localStorage.getItem/setItem("cse_theme")` logic
    - Remove `prefers-color-scheme` media query for theme detection
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6_

  - [x] 14.2 Remove deprecated component files
    - Verify no remaining imports of old `Card`, `Badge`, `ProgressBar`, `SkeletonLoader` components in page files
    - If all pages have been migrated, delete or mark deprecated: `web/src/components/Card.tsx`, `web/src/components/Badge.tsx`, `web/src/components/ProgressBar.tsx`, `web/src/components/SkeletonLoader.tsx`
    - _Requirements: 13.1_

  - [x] 14.3 Clean up old CSS classes from global.css
    - Remove old `.card`, `.btn-primary`, `.btn-secondary`, `.btn-ghost`, `.badge-*`, `.progress-bar`, `.skeleton`, `.form-group` classes that are now replaced by glass equivalents
    - Remove old `@keyframes shimmer`, `slideUp`, `fadeIn`, `pulse` that are replaced by design system animations
    - Ensure no remaining references to removed classes in any component
    - _Requirements: 1.4_

- [ ] 15. Performance and accessibility verification
  - [x] 15.1 Add performance optimizations
    - Add `will-change: transform` to animated elements (ambient blobs, hoverable cards)
    - Add `contain: layout style paint` to glass cards to limit repaint scope
    - Implement `useInView` hook for lazy rendering of below-fold glass surfaces in grid layouts (ModuleList, Home)
    - Verify backdrop-filter is only applied to visible elements
    - _Requirements: 11.1, 11.2, 11.3, 11.4_

  - [x] 15.2 Verify responsive design across breakpoints
    - Ensure mobile (<640px) glass surfaces use reduced blur (15px) and increased opacity
    - Ensure GlassNavbar collapses to hamburger below 768px
    - Ensure content grids reflow to single-column on mobile
    - Ensure touch targets are minimum 44px on mobile
    - Ensure ambient background reduces to 3 blobs on mobile
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6_

  - [x] 15.3 Verify accessibility compliance
    - Ensure all existing ARIA labels, roles, and keyboard navigation are preserved
    - Verify focus rings are visible warm-tinted glow on all interactive glass elements
    - Verify `prefers-reduced-motion` disables all animations system-wide (CSS and Framer Motion)
    - Verify all typography uses rem units for browser font size adjustment support
    - Verify AmbientBackground has `aria-hidden="true"`
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6_

- [x] 16. Final checkpoint - Full build verification
  - Ensure the entire application compiles without errors, all pages render with glassmorphism styling, no console errors on navigation, and the theme is applied unconditionally without any toggle. Ask the user if questions arise.

## Notes

- No property-based tests are included because this is a visual UI redesign with no algorithmic logic changes. Verification is through visual inspection, Lighthouse audits, and accessibility tools.
- Each task references specific requirements for traceability.
- Checkpoints ensure incremental validation throughout the migration.
- Old components are preserved during migration (Phase 4 pages) and only removed in the cleanup phase (Task 14) to avoid breaking intermediate states.
- The only new dependency is `framer-motion` (~30KB gzipped). No other libraries are introduced.
