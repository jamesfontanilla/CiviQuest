# Requirements Document

## Introduction

This specification defines the complete UI/UX redesign of the CSNexus CSE Reviewer System frontend. The redesign transforms the existing interface into a premium Apple-inspired glassmorphism design using a warm gradient brown color palette. All existing functionality, routes, backend logic, authentication, and database structure remain unchanged — only the visual presentation layer and component architecture are refactored.

## Glossary

- **Design_System**: The reusable set of CSS custom properties, TailwindCSS utility classes, and React component primitives that define the glassmorphism visual language across the application
- **Glass_Surface**: A UI element rendered with semi-transparent background, backdrop-filter blur (20–40px), subtle translucent borders, and layered shadow effects to create a frosted glass appearance
- **Ambient_Background**: The full-viewport animated gradient layer composed of blurred color blobs, noise textures, and depth overlays that sits behind all Glass_Surfaces
- **Component_Library**: The collection of reusable React components (GlassCard, GlassButton, GlassInput, GlassModal, GlassNavbar, GlassSidebar) that encapsulate glassmorphism styling and Framer Motion animations
- **Spring_Animation**: A physics-based animation curve provided by Framer Motion that simulates natural spring dynamics for hover, press, and transition effects
- **Brown_Palette**: The fixed warm color system consisting of Espresso Brown, Mocha, Caramel, Walnut, Sandstone, Champagne Beige, Bronze, and Soft Coffee tones used as the sole theme
- **Depth_Hierarchy**: The five-layer z-axis stacking system: Ambient_Background → Glass_Surface → Floating Interaction → Modal → Overlay
- **Existing_Frontend**: The current React application at `web/src/` comprising 16 components, 16+ pages, TailwindCSS styling, CSS custom properties in `global.css`, and a light/dark theme toggle

## Requirements

### Requirement 1: Design System Foundation

**User Story:** As a developer, I want a centralized glassmorphism design system with reusable tokens and utilities, so that all components share a consistent visual language without duplicating styles.

#### Acceptance Criteria

1. THE Design_System SHALL define CSS custom properties for the Brown_Palette including primary (Espresso Brown), secondary (Mocha), accent (Caramel), surface (Walnut), muted (Sandstone), highlight (Champagne Beige), metallic (Bronze), and background (Soft Coffee) color tokens
2. THE Design_System SHALL define glassmorphism tokens for backdrop-filter blur values (20px, 30px, 40px), surface opacity levels (0.08 to 0.25), border opacity levels (0.05 to 0.15), and shadow spread values
3. THE Design_System SHALL provide TailwindCSS utility classes for glass surfaces (`glass-sm`, `glass-md`, `glass-lg`), gradient backgrounds (`gradient-primary`, `gradient-accent`), and translucent borders (`border-glass`)
4. THE Design_System SHALL remove all light mode variables, dark mode variables, `[data-theme="dark"]` selectors, and theme toggle logic from the application
5. THE Design_System SHALL define a typography scale using the font stack `-apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", system-ui, sans-serif` with size tokens from 0.75rem to 3.5rem
6. THE Design_System SHALL define a layered shadow system with ambient shadow, depth shadow, glow shadow, and diffused shadow tokens that use warm brown-tinted rgba values instead of black
7. THE Design_System SHALL define border tokens using translucent white and warm-tinted rgba values (e.g., `rgba(255, 255, 255, 0.08)` to `rgba(255, 255, 255, 0.15)`) for edge highlights

### Requirement 2: Ambient Background System

**User Story:** As a user, I want an immersive animated background that creates visual depth, so that the interface feels premium and layered like a native macOS application.

#### Acceptance Criteria

1. THE Ambient_Background SHALL render animated gradient blobs using CSS radial-gradient and keyframe animations with warm Brown_Palette colors
2. THE Ambient_Background SHALL apply a subtle noise texture overlay using a CSS pseudo-element with a repeating SVG or base64 grain pattern at low opacity (0.02 to 0.05)
3. THE Ambient_Background SHALL remain fixed to the viewport and persist across all route transitions without re-mounting or restarting animations
4. THE Ambient_Background SHALL use GPU-accelerated CSS properties (transform, opacity) for blob movement to maintain 60fps rendering
5. WHILE the user has enabled reduced-motion preferences, THE Ambient_Background SHALL disable all blob animations and display a static gradient
6. THE Ambient_Background SHALL render behind all Glass_Surfaces using the lowest layer of the Depth_Hierarchy (z-index below all content)

### Requirement 3: Glass Component Library

**User Story:** As a developer, I want reusable glass-styled React components, so that I can compose pages consistently without reimplementing glassmorphism effects per component.

#### Acceptance Criteria

1. THE Component_Library SHALL provide a `GlassCard` component that renders a Glass_Surface with configurable blur intensity (sm, md, lg), padding, and border-radius
2. THE Component_Library SHALL provide a `GlassButton` component with translucent background, subtle blur, soft glow on hover, and Spring_Animation on click (scale 1.02 with spring physics)
3. THE Component_Library SHALL provide a `GlassInput` component styled as a frosted surface with inner shadow, thin translucent border, and soft focus glow using Brown_Palette accent colors
4. THE Component_Library SHALL provide a `GlassModal` component that renders a centered Glass_Surface over a blurred backdrop overlay with enter/exit Spring_Animations
5. THE Component_Library SHALL provide a `GlassNavbar` component with translucent background, backdrop-filter blur, and scroll-triggered opacity transition
6. THE Component_Library SHALL provide a `GlassSidebar` component styled as a floating glass panel with translucent navigation items and smooth active-state indicators
7. THE Component_Library SHALL provide a `GlassProgressBar` component with a translucent track, gradient fill using Brown_Palette colors, and subtle inner glow
8. THE Component_Library SHALL provide a `GlassBadge` component with frosted background, soft border, and warm-tinted text colors
9. WHEN a Glass_Surface component receives focus via keyboard navigation, THE Component_Library SHALL display a visible focus ring using a warm-tinted glow (not the default browser outline)
10. THE Component_Library SHALL accept all existing props from the current components (Card, Badge, ProgressBar) to maintain backward compatibility with page-level code

### Requirement 4: Animation System

**User Story:** As a user, I want smooth, physics-based animations throughout the interface, so that interactions feel natural and premium rather than mechanical.

#### Acceptance Criteria

1. THE Design_System SHALL integrate Framer Motion as the animation library for all component transitions, hover effects, and page transitions
2. WHEN a user hovers over a GlassButton, THE GlassButton SHALL animate to scale 1.02 with a soft glow diffusion effect using a spring transition (stiffness: 300, damping: 20)
3. WHEN a user clicks a GlassButton, THE GlassButton SHALL animate a brief scale-down to 0.97 followed by a spring return to scale 1.0
4. WHEN a page route changes, THE Design_System SHALL apply a fade-and-slide entrance animation (opacity 0→1, translateY 12px→0) with spring physics to the incoming page content
5. WHEN a GlassModal opens, THE GlassModal SHALL animate from opacity 0 and scale 0.95 to opacity 1 and scale 1.0 with a spring transition
6. WHILE the user has enabled reduced-motion preferences, THE Design_System SHALL disable all Spring_Animations and apply instant state changes with zero duration
7. THE Design_System SHALL provide reusable Framer Motion animation variants (`fadeIn`, `slideUp`, `scaleIn`, `staggerChildren`) as exported constants for page-level use

### Requirement 5: Navbar Redesign

**User Story:** As a user, I want a translucent navigation bar that blends with the glassmorphism aesthetic, so that navigation feels integrated with the overall premium design.

#### Acceptance Criteria

1. THE GlassNavbar SHALL render with a translucent Brown_Palette background and backdrop-filter blur of 30px
2. WHEN the user scrolls past 10px, THE GlassNavbar SHALL transition from fully transparent to a frosted glass state with increased opacity and visible border-bottom
3. THE GlassNavbar SHALL display navigation links with soft hover states (translucent background highlight) and active states (gradient underline or background pill)
4. THE GlassNavbar SHALL remove the DarkModeToggle component and all references to theme switching
5. THE GlassNavbar SHALL preserve all existing navigation links, mobile hamburger menu behavior, and route-based active detection
6. WHEN the mobile menu opens, THE GlassNavbar SHALL display a glass-styled dropdown panel with Spring_Animation entrance (slide down with fade)
7. THE GlassNavbar SHALL maintain sticky positioning at the top of the viewport with appropriate Depth_Hierarchy z-index

### Requirement 6: Authentication Pages Redesign

**User Story:** As a user, I want login, signup, forgot-password, and OTP pages that feel premium and trustworthy, so that my first interaction with the application establishes a high-quality impression.

#### Acceptance Criteria

1. THE Existing_Frontend auth pages (Login, Signup, ForgotPassword, OTPVerification) SHALL render form content inside a centered GlassCard with the Ambient_Background visible behind
2. THE auth pages SHALL use GlassInput components for all form fields with frosted styling, inner shadows, and focus glow effects
3. THE auth pages SHALL use GlassButton components for submit actions with gradient Brown_Palette backgrounds and Spring_Animation hover/click effects
4. THE auth pages SHALL preserve all existing form validation logic, error display, API calls, and redirect behavior
5. THE auth pages SHALL display the CSNexus logo and heading with large hero typography using the Design_System font stack and Brown_Palette text colors
6. IF a form submission fails with a validation error, THEN THE auth pages SHALL display the error message in a warm-tinted error style (soft red-brown) within the GlassCard without layout shift

### Requirement 7: Content Pages Redesign

**User Story:** As a user, I want module, topic, subtopic, and lesson pages styled with glassmorphism, so that studying content feels immersive and visually engaging.

#### Acceptance Criteria

1. THE ModuleList page SHALL render each module as a GlassCard with gradient accent borders, progress indicators using GlassProgressBar, and Spring_Animation hover effects
2. THE TopicList and SubtopicList pages SHALL render items as GlassCard components with translucent backgrounds and staggered entrance animations
3. THE LessonReader page SHALL render lesson content inside a GlassCard with comfortable reading typography (max-width, line-height 1.7, Brown_Palette text colors)
4. THE content pages SHALL preserve all existing data fetching, loading states, error handling, and navigation between modules, topics, subtopics, and lessons
5. WHEN content is loading, THE content pages SHALL display skeleton loaders styled as pulsing Glass_Surfaces with translucent shimmer animations

### Requirement 8: Quiz and Mock Exam Pages Redesign

**User Story:** As a user, I want quiz and mock exam interfaces styled with glassmorphism, so that timed assessments feel focused and premium.

#### Acceptance Criteria

1. THE QuizPlayer page SHALL render question cards as GlassCard components with answer options as translucent selectable items that highlight with a warm glow on selection
2. THE MockExamPlayer page SHALL render the exam timer as a floating Glass_Surface element with gradient text and subtle pulse animation when time is running low
3. THE quiz and mock exam pages SHALL use GlassButton components for navigation (next, previous, submit) with appropriate Spring_Animations
4. THE quiz and mock exam pages SHALL preserve all existing timer logic, question navigation, answer submission, scoring, and result display functionality
5. WHEN a quiz or exam is completed, THE results display SHALL render inside a GlassCard with animated score reveal using Spring_Animation (scale-in with stagger for individual stats)

### Requirement 9: Dashboard and Analytics Pages Redesign

**User Story:** As a user, I want dashboard, analytics, leaderboard, and profile pages styled with glassmorphism, so that progress tracking feels visually rewarding.

#### Acceptance Criteria

1. THE Leaderboard page SHALL render the rankings table inside a GlassCard with translucent row backgrounds and subtle hover highlights
2. THE Analytics page SHALL render chart containers and stat cards as Glass_Surfaces with translucent backgrounds and warm-tinted data visualization colors from the Brown_Palette
3. THE Profile page SHALL render user information and settings inside GlassCard components with gradient accent headers
4. THE AdminDashboard page SHALL render admin panels and data tables as Glass_Surfaces with appropriate Depth_Hierarchy layering
5. THE StatCard, StreakDisplay, AchievementCard, HeatMap, and Chart components SHALL be restyled as Glass_Surfaces with Brown_Palette color integration
6. THE dashboard and analytics pages SHALL preserve all existing data fetching, state management, and interactive functionality

### Requirement 10: Responsive Glassmorphism

**User Story:** As a user on any device, I want the glassmorphism design to work across mobile, tablet, and desktop viewports, so that the premium experience is consistent regardless of screen size.

#### Acceptance Criteria

1. THE Design_System SHALL define responsive breakpoints (mobile: <640px, tablet: 640–1024px, desktop: >1024px) with appropriate Glass_Surface sizing and padding adjustments
2. WHILE the viewport width is below 640px, THE Glass_Surfaces SHALL reduce backdrop-filter blur to 15px and increase surface opacity to maintain readability on smaller screens
3. THE GlassNavbar SHALL collapse to a hamburger menu below 768px with a glass-styled mobile drawer
4. THE content grid layouts (ModuleList, feature cards on Home) SHALL reflow from multi-column to single-column on mobile viewports
5. THE GlassInput and GlassButton components SHALL scale touch targets to minimum 44px height on mobile viewports for accessibility compliance
6. THE Ambient_Background SHALL reduce the number of animated blobs on mobile viewports to maintain performance (maximum 3 blobs on mobile vs 5+ on desktop)

### Requirement 11: Performance Optimization

**User Story:** As a user, I want the glassmorphism effects to render smoothly without lag, so that visual quality does not come at the cost of usability.

#### Acceptance Criteria

1. THE Design_System SHALL use `will-change: transform` and GPU-accelerated properties for all animated elements to prevent layout thrashing
2. THE Ambient_Background SHALL use CSS-only animations (no JavaScript animation loops) for blob movement to minimize main-thread work
3. THE Component_Library SHALL lazy-render Glass_Surfaces that are below the viewport fold using intersection observer or React lazy patterns
4. THE backdrop-filter blur effects SHALL be applied only to elements currently visible in the viewport to prevent unnecessary GPU compositing
5. IF a device does not support `backdrop-filter` (checked via `@supports`), THEN THE Design_System SHALL fall back to solid semi-transparent backgrounds with matching Brown_Palette colors
6. THE Design_System SHALL maintain a Lighthouse Performance score above 80 on desktop and above 70 on mobile after the redesign

### Requirement 12: Accessibility Compliance

**User Story:** As a user with accessibility needs, I want the glassmorphism interface to remain readable and navigable, so that visual effects do not impair usability.

#### Acceptance Criteria

1. THE Design_System SHALL maintain a minimum contrast ratio of 4.5:1 for body text and 3:1 for large text against Glass_Surface backgrounds, verified with the translucent layers composited over the Ambient_Background
2. THE Component_Library SHALL preserve all existing ARIA labels, roles, and keyboard navigation patterns from the current components
3. WHEN a user navigates via keyboard, THE focus indicators SHALL be clearly visible as warm-tinted glow rings with sufficient contrast against Glass_Surfaces
4. THE Design_System SHALL respect `prefers-reduced-motion` by disabling all animations and transitions system-wide
5. THE GlassInput components SHALL maintain visible label associations, error announcements via `aria-live`, and sufficient placeholder contrast
6. THE typography scale SHALL support browser-level font size adjustments (rem-based sizing) without layout breakage

### Requirement 13: Theme Removal and Single Palette Enforcement

**User Story:** As a developer, I want the light/dark mode system completely removed, so that the single Brown_Palette glassmorphism theme is the only visual mode with no toggle or system-preference detection.

#### Acceptance Criteria

1. THE Existing_Frontend SHALL remove the DarkModeToggle component file and all imports referencing it
2. THE Existing_Frontend SHALL remove the `[data-theme="dark"]` CSS selector block and all associated dark-mode custom properties from `global.css`
3. THE Existing_Frontend SHALL remove the `data-theme` attribute manipulation from `document.documentElement`
4. THE Existing_Frontend SHALL remove the `localStorage` theme persistence logic (`cse_theme` key)
5. THE Existing_Frontend SHALL remove the `prefers-color-scheme` media query detection for theme selection
6. WHEN the application loads, THE Design_System SHALL apply the Brown_Palette glassmorphism theme unconditionally without checking any stored preference or system setting

### Requirement 14: Framer Motion Integration

**User Story:** As a developer, I want Framer Motion properly integrated as a project dependency with reusable animation utilities, so that all components can use consistent physics-based animations.

#### Acceptance Criteria

1. THE Existing_Frontend SHALL add `framer-motion` as a production dependency in `web/package.json`
2. THE Design_System SHALL export reusable animation variant objects for common patterns: `fadeIn`, `slideUp`, `slideDown`, `scaleIn`, `staggerContainer`, and `staggerItem`
3. THE Design_System SHALL export reusable spring transition presets: `springDefault` (stiffness: 300, damping: 20), `springGentle` (stiffness: 200, damping: 25), and `springBouncy` (stiffness: 400, damping: 15)
4. THE Component_Library SHALL wrap page-level content in Framer Motion `AnimatePresence` for route transition animations
5. THE Design_System SHALL provide a `useReducedMotion` hook that reads `prefers-reduced-motion` and returns animation variants with zero duration when motion is reduced

### Requirement 15: Special Visual Effects

**User Story:** As a user, I want subtle premium visual effects like grain texture, ambient lighting, and glass reflections, so that the interface feels polished and luxurious without being distracting.

#### Acceptance Criteria

1. THE Design_System SHALL apply a subtle grain texture overlay across the viewport using a CSS pseudo-element with a noise pattern at opacity 0.02–0.04
2. THE Glass_Surfaces SHALL render a subtle top-edge highlight (1px gradient from `rgba(255,255,255,0.1)` to transparent) to simulate light reflection
3. THE GlassButton components SHALL display a soft ambient glow on hover using a box-shadow with Brown_Palette accent color at low opacity (0.15–0.25)
4. THE Ambient_Background gradient blobs SHALL use soft color transitions (8–15 second animation cycles) to create a living, breathing background effect
5. THE special effects SHALL remain subtle and professional — no particle effects, no sparkles, no lens flares, and no effects that draw attention away from content
