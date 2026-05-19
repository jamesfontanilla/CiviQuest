# Requirements Document

## Introduction

The CSE Reviewer System is a web-based learning platform that helps Filipino candidates prepare for the Civil Service Examination (CSE) in either the Professional or Sub-Professional track. Learners study lesson modules organized by topic and subtopic, take auto-graded practice quizzes, attempt timed mock exams, and earn experience points (XP) that drive a level/leaderboard system. Administrators manage users, content, and exams. The platform is intended to run locally on a learner's machine after installation, with offline study support via a Progressive Web App (PWA) shell.

This document captures only **what** the system must do. Stack choice, schema, and component breakdown are deferred to design.

---

## Open Questions and Risks (resolve before design)

These are unresolved before locking requirements. Each has a working assumption baked into the EARS statements below; adjust the requirements when each is resolved.

1. **Tech stack mismatch.** The original request specifies Node.js + Express + JSON files. The workspace steering files (`code-conventions.md`, `api-standard.md`, `testing-standards.md`, `security-policy.md`) describe a Python + FastAPI + SQLAlchemy + Pydantic architecture. Requirements here are written stack-agnostic. **Decision needed:** follow Node/JSON as requested, or align with workspace Python/FastAPI conventions. This will materially change non-functional requirements (e.g., persistence semantics, validation library, auth library).
2. **Scope vs. MVP.** Full scope is ~9 Professional modules + 8 Sub-Professional modules, with lessons + question banks + topic quizzes + module quizzes + 165-question mocks per category, plus auth/OTP, admin, XP, leaderboards, achievements, PWA, dark mode, and analytics. **Recommended MVP slice:** auth (without OTP email delivery — local OTP only), one module per category with 2 topics × 2 subtopics each, lesson + 20-question subtopic quizzes, one 50-question mock (not 165), XP and a single leaderboard. Everything else is Phase 2+. Requirements below mark Phase 2 items with `(Phase 2)` so the MVP can be carved out cleanly. **Decision needed:** confirm MVP slice or commit to full scope.
3. **"AI-powered" definition under offline + 99% accuracy.** Generating exam-grade Filipino civil service questions with a local LLM at ≥99% factual accuracy is not currently feasible. **Working assumption:** "AI-powered" means the question bank is AI-assisted *during authoring* (offline tooling not part of this spec) and *served* deterministically from a pre-built bank at runtime. Runtime question selection is randomized but not generative. **Decision needed:** confirm, or specify a different interpretation (e.g., bundled local model, online-only generation, deterministic templates).
4. **Question count arithmetic.** The original request says "EXACTLY 20 questions per subtopic, 50 per topic, 100 per module." These are not aggregations of each other (5 subtopics × 20 ≠ 50). **Working assumption:** each level is a *separate quiz* drawing from a level-specific pool — the subtopic quiz has 20 questions from that subtopic's bank; the topic quiz has 50 questions from that topic's bank (which may overlap subtopic content); the module quiz has 100 questions from that module's bank. **Decision needed:** confirm this interpretation.
5. **OTP email delivery offline.** Email-based OTP requires an outbound SMTP path, which contradicts "fully offline." **Working assumption:** in offline mode the OTP is written to a local file/log the user can read; in online mode an SMTP relay is used. **Decision needed:** confirm.
6. **Content authorship.** The full bank requires thousands of authored questions and lessons. Requirements assume content is authored externally and loaded as data. **Decision needed:** is content authoring in scope for this spec?

---

## Glossary

- **System**: The CSE Reviewer System as a whole.
- **Auth_Service**: The component that handles signup, login, password reset, and session token issuance.
- **OTP_Service**: The component that generates, delivers, and verifies one-time passwords used for email verification and password reset.
- **Content_Service**: The component that serves modules, topics, subtopics, and lesson content to authenticated users.
- **Quiz_Service**: The component that assembles and grades practice quizzes (subtopic, topic, and module level).
- **Mock_Exam_Service**: The component that assembles, times, and grades the 165-question final mock exam.
- **Progress_Service**: The component that records lesson completion, quiz attempts, scores, and unlocks.
- **XP_Service**: The component that awards experience points, computes levels, and updates streaks.
- **Leaderboard_Service**: The component that ranks users by XP across global, weekly, and monthly windows.
- **Achievement_Service**: The component that grants badges based on user activity criteria.
- **Admin_Service**: The component that exposes administrative actions (user management, content edits, analytics, exports).
- **Notification_Service**: The component that displays in-app toasts and announcements.
- **Learner**: A user with the standard role who consumes lessons and takes quizzes/exams.
- **Admin**: A user with elevated privileges who can manage users, content, and exams.
- **Category**: One of `PROFESSIONAL` or `SUB_PROFESSIONAL`. Determines which Modules a Learner sees.
- **Module**: A top-level content unit (e.g., "English Verbal Ability") scoped to one Category.
- **Topic**: A child of a Module (e.g., "Vocabulary").
- **Subtopic**: A child of a Topic (e.g., "Synonyms").
- **Lesson**: The instructional content attached to a Subtopic that must be read before its quiz unlocks.
- **Subtopic_Quiz**: A 20-question quiz drawn from a Subtopic's question pool.
- **Topic_Quiz**: A 50-question quiz drawn from a Topic's question pool.
- **Module_Quiz**: A 100-question quiz drawn from a Module's question pool.
- **Mock_Exam**: A 165-question timed final exam, one variant per Category.
- **Question**: A single graded item with a stem, options (where applicable), one correct answer, an explanation, a difficulty (`EASY` | `MEDIUM` | `HARD`), and a type (`MULTIPLE_CHOICE` | `IDENTIFICATION` | `LOGICAL_REASONING` | `READING_COMPREHENSION` | `PROBLEM_SOLVING`).
- **XP**: A non-negative integer score awarded for completing learning activities.
- **Level**: A tier derived from a Learner's cumulative XP via a fixed mapping.
- **Streak**: The count of consecutive calendar days (in the user's local timezone) on which a Learner completed at least one qualifying activity.
- **Achievement**: A named badge granted when a defined criterion is met.
- **Session_Token**: A signed token issued by Auth_Service that authenticates subsequent requests.
- **OTP**: A 6-digit numeric one-time password with a 5-minute expiry.

---

## Requirements

### Requirement 1: Account Signup

**User Story:** As a prospective learner, I want to create an account with my full name, age, email, password, and CSE category, so that I can access category-appropriate content.

#### Acceptance Criteria

1. WHEN a signup request is submitted with all required fields valid, THE Auth_Service SHALL create a Learner account in the `UNVERIFIED` state and trigger OTP_Service to issue a verification OTP.
2. IF the submitted email already belongs to an existing account, THEN THE Auth_Service SHALL reject the signup with a conflict error and SHALL NOT create a duplicate account.
3. IF the submitted password is fewer than 8 characters, or lacks at least one uppercase letter, one lowercase letter, one digit, or one symbol from the set `! @ # $ % ^ & * ( ) - _ = + [ ] { } ; : , . < > ? /`, THEN THE Auth_Service SHALL reject the signup with a validation error identifying the failed rule(s).
4. IF the submitted age is not an integer between 15 and 100 inclusive, THEN THE Auth_Service SHALL reject the signup with a validation error.
5. IF the submitted category is not one of `PROFESSIONAL` or `SUB_PROFESSIONAL`, THEN THE Auth_Service SHALL reject the signup with a validation error.
6. THE Auth_Service SHALL store the password as a bcrypt hash with a work factor of at least 10 and SHALL NOT persist the plaintext password.
7. THE Auth_Service SHALL respond to a successful signup within 2 seconds at the 95th percentile under a load of 10 concurrent signups on the local development hardware.

### Requirement 2: Email Verification via OTP

**User Story:** As a learner, I want to verify my email with a one-time code, so that the system confirms I own the address before granting access.

#### Acceptance Criteria

1. WHEN OTP_Service is asked to issue a verification OTP, THE OTP_Service SHALL generate a 6-digit numeric code, persist it with an expiry timestamp 5 minutes in the future, and deliver it to the user's email address.
2. WHEN a user submits an OTP for an `UNVERIFIED` account and the submitted code matches the latest unexpired unused OTP for that account, THE Auth_Service SHALL transition the account to the `VERIFIED` state and invalidate the OTP.
3. IF the submitted OTP does not match, is expired, or has already been used, THEN THE Auth_Service SHALL reject the verification with a generic `OTP invalid or expired` error and SHALL NOT reveal which condition failed.
4. WHILE an account is in the `UNVERIFIED` state, THE Auth_Service SHALL reject login attempts with an `email not verified` error.
5. WHEN a user requests a new OTP for an `UNVERIFIED` account, THE OTP_Service SHALL invalidate any previous unused OTP for that account before issuing a new one.
6. THE OTP_Service SHALL allow no more than 5 OTP issuance requests per account per rolling 60-minute window.
7. THE OTP_Service SHALL allow no more than 5 OTP verification attempts per OTP code; on the 6th attempt the OTP SHALL be invalidated.
8. WHERE the System is operating in offline mode, THE OTP_Service SHALL write the issued OTP to a local file at a configured path in addition to (or in place of) email delivery, so the local user can retrieve it without network access.

### Requirement 3: Login and Session

**User Story:** As a verified learner, I want to log in with my email and password, so that I can resume my studies.

#### Acceptance Criteria

1. WHEN a login request is submitted with an email and password matching a `VERIFIED` account, THE Auth_Service SHALL issue a Session_Token valid for 24 hours and return it to the client.
2. IF the submitted credentials do not match any `VERIFIED` account, THEN THE Auth_Service SHALL reject the login with a generic `invalid credentials` error and SHALL NOT disclose whether the email or password was incorrect.
3. IF a single account receives 5 failed login attempts within 15 minutes, THEN THE Auth_Service SHALL reject further login attempts on that account for 15 minutes from the most recent failure with a `temporarily locked` error.
4. THE Auth_Service SHALL invalidate a Session_Token on user logout and SHALL reject subsequent requests bearing that token with a 401 status.
5. WHEN a request bearing an expired or invalid Session_Token is received, THE System SHALL respond with a 401 status and SHALL NOT process the request.

### Requirement 4: Forgot Password

**User Story:** As a learner who forgot my password, I want to request a reset and confirm via OTP, so that I can regain access without contacting an admin.

#### Acceptance Criteria

1. WHEN a forgot-password request is submitted for an existing email, THE OTP_Service SHALL issue a password-reset OTP using the same generation, expiry, and delivery rules as Requirement 2.
2. IF a forgot-password request is submitted for an email that does not exist, THEN THE Auth_Service SHALL respond with the same success message as the existing-email case and SHALL NOT reveal whether the email exists.
3. WHEN a password-reset request is submitted with a valid unexpired unused reset OTP and a new password meeting Requirement 1.3, THE Auth_Service SHALL update the account's password hash and invalidate the OTP.
4. WHEN a password is successfully reset, THE Auth_Service SHALL invalidate all existing Session_Tokens for that account.

### Requirement 5: Category-Gated Content Access

**User Story:** As a learner, I want to see only the modules relevant to my chosen CSE category, so that I am not distracted by content I will not be tested on.

#### Acceptance Criteria

1. WHEN a `VERIFIED` Learner with category `PROFESSIONAL` requests the module list, THE Content_Service SHALL return only Modules tagged for the `PROFESSIONAL` category.
2. WHEN a `VERIFIED` Learner with category `SUB_PROFESSIONAL` requests the module list, THE Content_Service SHALL return only Modules tagged for the `SUB_PROFESSIONAL` category.
3. IF a Learner attempts to access a Module, Topic, Subtopic, Lesson, or Quiz not tagged for their Category, THEN THE Content_Service SHALL respond with a 403 status.
4. (Phase 2) WHERE a Learner has the `CROSS_CATEGORY_PREVIEW` flag enabled by an Admin, THE Content_Service SHALL return Modules from both Categories.

### Requirement 6: Lesson-Before-Quiz Gating

**User Story:** As a learner, I want quizzes to unlock only after I have read the corresponding lesson, so that I do not skip the instructional content.

#### Acceptance Criteria

1. WHILE a Learner has not marked a Subtopic's Lesson as complete, THE Quiz_Service SHALL refuse to start that Subtopic's Subtopic_Quiz with a `lesson not completed` error.
2. WHEN a Learner reaches the end of a Lesson and submits a completion event, THE Progress_Service SHALL record the Lesson as completed for that Learner.
3. THE Content_Service SHALL include for each Lesson at least one detailed explanation section, at least one worked example, a key-takeaways section, and a mini summary, as determined by the Lesson's content schema.
4. IF a Lesson lacks any of the sections required by Requirement 6.3, THEN the Content_Service SHALL flag the Lesson as `INCOMPLETE` in admin views and SHALL NOT expose it to Learners.

### Requirement 7: Subtopic Quizzes

**User Story:** As a learner, I want a 20-question practice quiz per subtopic, so that I can verify my understanding of that subtopic.

#### Acceptance Criteria

1. WHEN a Learner starts a Subtopic_Quiz for a Subtopic whose Lesson is complete, THE Quiz_Service SHALL assemble exactly 20 Questions drawn from that Subtopic's question pool.
2. IF the Subtopic's question pool contains fewer than 20 Questions, THEN the Quiz_Service SHALL refuse to start the Subtopic_Quiz with an `insufficient question pool` error and SHALL log the deficient pool for admin review.
3. THE Quiz_Service SHALL randomize Question order and (for Multiple_Choice Questions) option order on each quiz instance.
4. WHEN a Learner submits an answer to a Question in an active quiz, THE Quiz_Service SHALL grade the answer and SHALL include the correct answer and explanation in the response only after the quiz instance is submitted.
5. WHEN a Learner submits a Subtopic_Quiz, THE Quiz_Service SHALL return per-Question correctness, the correct answer, and the Question's explanation for every Question in the quiz.
6. WHERE a Learner achieves a perfect score (20/20) on a Subtopic_Quiz, THE XP_Service SHALL award 50 XP for that submission.
7. WHERE a Learner achieves a non-perfect passing score on a Subtopic_Quiz, THE XP_Service SHALL award 20 XP for that submission.

### Requirement 8: Topic Quizzes

**User Story:** As a learner, I want a 50-question quiz per topic, so that I can confirm I have integrated the subtopics within that topic.

#### Acceptance Criteria

1. WHILE any Subtopic_Quiz under a Topic has not been passed at least once by the Learner, THE Quiz_Service SHALL refuse to start that Topic's Topic_Quiz with a `prerequisites not met` error.
2. WHEN a Learner starts a Topic_Quiz, THE Quiz_Service SHALL assemble exactly 50 Questions drawn from that Topic's question pool.
3. THE Quiz_Service SHALL apply the randomization, grading, and feedback rules from Requirements 7.3 through 7.5 to Topic_Quizzes.
4. WHERE a Learner passes a Topic_Quiz (defined as ≥80% correct), THE XP_Service SHALL award 100 XP for that submission.
5. WHEN every Subtopic_Quiz under a Topic has been passed and the Topic_Quiz has been passed, THE Progress_Service SHALL mark the Topic as complete for that Learner.

### Requirement 9: Module Quizzes

**User Story:** As a learner, I want a 100-question quiz per module, so that I can confirm I have integrated all topics in that module.

#### Acceptance Criteria

1. WHILE any Topic_Quiz under a Module has not been passed at least once by the Learner, THE Quiz_Service SHALL refuse to start that Module's Module_Quiz with a `prerequisites not met` error.
2. WHEN a Learner starts a Module_Quiz, THE Quiz_Service SHALL assemble exactly 100 Questions drawn from that Module's question pool.
3. THE Quiz_Service SHALL apply the randomization, grading, and feedback rules from Requirements 7.3 through 7.5 to Module_Quizzes.
4. WHERE a Learner passes a Module_Quiz (defined as ≥80% correct), THE XP_Service SHALL award 250 XP for that submission and THE Progress_Service SHALL mark the Module as complete for that Learner.

### Requirement 10: Final Mock Exam

**User Story:** As a learner, I want a 165-question timed mock exam matching CSC structure, so that I can rehearse the real exam experience.

#### Acceptance Criteria

1. WHEN a Learner with category `PROFESSIONAL` starts a Mock_Exam, THE Mock_Exam_Service SHALL assemble exactly 165 Questions drawn from the Professional question banks across all Professional Modules, distributed according to the published CSC Professional category weights configured in `mock_exam_config`.
2. WHEN a Learner with category `SUB_PROFESSIONAL` starts a Mock_Exam, THE Mock_Exam_Service SHALL assemble exactly 165 Questions drawn from the Sub-Professional question banks across all Sub-Professional Modules, distributed according to the published CSC Sub-Professional category weights configured in `mock_exam_config`.
3. THE Mock_Exam_Service SHALL impose a hard time limit of 180 minutes on each Mock_Exam attempt and SHALL auto-submit any in-progress exam when the timer reaches zero.
4. WHILE a Mock_Exam attempt is in progress, THE Quiz_Service SHALL NOT reveal correct answers or explanations to the Learner.
5. WHEN a Mock_Exam is submitted (manually or via auto-submit), THE Mock_Exam_Service SHALL produce a result containing: total score, percentage, pass/fail flag (pass = ≥80%), per-Module score breakdown, weakness summary listing the three Modules with the lowest score percentages, and per-Question correctness with explanations.
6. WHERE a Learner passes a Mock_Exam (≥80%), THE XP_Service SHALL award 500 XP for that submission.
7. THE Mock_Exam_Service SHALL persist every Mock_Exam attempt with start time, end time, submission mode (`MANUAL` | `AUTO_SUBMIT`), and full answer record.
8. IF a Learner has an in-progress Mock_Exam attempt, THEN THE Mock_Exam_Service SHALL refuse to start a new one until the active one is submitted or expired.

### Requirement 11: XP, Levels, and Streaks

**User Story:** As a learner, I want XP, levels, and a daily streak, so that I am motivated to study consistently.

#### Acceptance Criteria

1. THE XP_Service SHALL award XP only for the events listed in Requirements 7.6, 7.7, 8.4, 9.4, 10.6, 11.2, and 11.3, and SHALL reject any other XP-award request.
2. WHEN a Learner completes any Lesson for the first time, THE XP_Service SHALL award 20 XP for that Lesson.
3. WHEN a Learner extends their Streak to a new calendar day (in the Learner's stored timezone) by completing any qualifying activity (Lesson completion, quiz pass, or mock exam submission), THE XP_Service SHALL award 25 XP for that day.
4. THE XP_Service SHALL compute Level from cumulative XP using a deterministic mapping defined in `xp_levels_config`, where Level N requires `100 * N * (N + 1) / 2` cumulative XP.
5. WHEN a Learner's cumulative XP crosses a Level threshold, THE Notification_Service SHALL emit a `level_up` toast naming the new Level.
6. IF a Learner does not complete any qualifying activity for more than 36 consecutive hours since their last qualifying activity, THEN THE XP_Service SHALL reset the Streak to zero on the next read.
7. THE XP_Service SHALL never produce a negative XP balance and SHALL never decrement XP except via an explicit Admin correction action.

### Requirement 12: Leaderboards

**User Story:** As a learner, I want to see how my XP compares to other learners, so that I have a competitive incentive to study.

#### Acceptance Criteria

1. WHEN a Learner requests the global leaderboard, THE Leaderboard_Service SHALL return the top 100 Learners ordered by cumulative XP descending, with ties broken by earliest Level-reached timestamp.
2. WHEN a Learner requests the weekly leaderboard, THE Leaderboard_Service SHALL return the top 100 Learners ordered by XP earned in the current ISO week (Monday 00:00 to Sunday 23:59 in UTC) descending.
3. WHEN a Learner requests the monthly leaderboard, THE Leaderboard_Service SHALL return the top 100 Learners ordered by XP earned in the current calendar month (UTC) descending.
4. THE Leaderboard_Service SHALL include only Learners who have a `VERIFIED` account and who have not been banned.
5. THE Leaderboard_Service SHALL include each entry's display name, Level, XP value for the relevant window, and Category.

### Requirement 13: Achievements

**User Story:** As a learner, I want badges that recognize specific milestones, so that my effort is acknowledged beyond raw XP.

#### Acceptance Criteria

1. THE Achievement_Service SHALL evaluate each defined Achievement criterion at the end of every XP-awarding event for the affected Learner.
2. WHEN a Learner first satisfies an Achievement criterion, THE Achievement_Service SHALL grant the Achievement with the earned timestamp and SHALL emit an `achievement_unlocked` toast via the Notification_Service.
3. THE Achievement_Service SHALL never grant the same Achievement to the same Learner more than once.
4. THE set of Achievement definitions SHALL include at minimum: `FIRST_LESSON`, `FIRST_PERFECT_SUBTOPIC_QUIZ`, `FIRST_TOPIC_PASSED`, `FIRST_MODULE_PASSED`, `FIRST_MOCK_PASSED`, `STREAK_7_DAYS`, `STREAK_30_DAYS`, `LEVEL_10`, `LEVEL_25`.

### Requirement 14: Progress Persistence and Resume

**User Story:** As a learner, I want my progress saved as I go, so that I can resume exactly where I left off after closing the app.

#### Acceptance Criteria

1. WHEN a Learner submits an answer in an active quiz or mock exam, THE Progress_Service SHALL persist the answer before responding to the client.
2. WHEN a Learner reopens the application after closing it, THE Progress_Service SHALL restore: the most recently viewed Lesson position, any in-progress quiz or mock exam (with elapsed time and answers so far), and current XP, Level, and Streak values.
3. IF a Mock_Exam is in progress and the elapsed time exceeds the 180-minute limit at the time of resume, THEN THE Mock_Exam_Service SHALL auto-submit the exam using the answers persisted so far.
4. THE Progress_Service SHALL preserve previously completed Lessons, passed quizzes, earned XP, and earned Achievements across application restarts.

### Requirement 15: Admin User Management

**User Story:** As an admin, I want to view, ban, and delete user accounts, so that I can manage the user base.

#### Acceptance Criteria

1. THE Admin_Service SHALL require requests to bear a Session_Token belonging to an account with the `ADMIN` role and SHALL respond with 403 to any other authenticated request.
2. WHEN an Admin requests the user list, THE Admin_Service SHALL return paginated user records including id, email, display name, category, role, account state, cumulative XP, Level, and ban status, with `skip` >= 0 and `1 <= limit <= 100`.
3. WHEN an Admin bans a user, THE Admin_Service SHALL set that user's ban status to true and THE Auth_Service SHALL reject any subsequent login or token-bearing request from that user with a 403 `account banned` error.
4. WHEN an Admin deletes a user, THE Admin_Service SHALL remove the user's account and all the user's progress, quiz attempts, and mock exam attempts, and SHALL retain only an anonymized aggregate counter for analytics.
5. THE Admin_Service SHALL log every admin action (actor id, target id, action, timestamp) to an append-only audit log.

### Requirement 16: Admin Content Management

**User Story:** As an admin, I want to edit modules, topics, subtopics, lessons, and questions, so that I can correct errors and add content.

#### Acceptance Criteria

1. WHEN an Admin creates or edits a Module, Topic, or Subtopic, THE Admin_Service SHALL validate that the parent reference exists and that the Category tag matches the parent's Category.
2. WHEN an Admin creates or edits a Question, THE Admin_Service SHALL validate that the Question references an existing Subtopic, has exactly one correct answer, has between 2 and 6 options for `MULTIPLE_CHOICE` types, has a non-empty stem, and has a non-empty explanation.
3. IF an Admin attempts to delete a Subtopic, Topic, or Module that has any Learner progress associated, THEN THE Admin_Service SHALL require an explicit `force=true` flag and SHALL cascade-delete progress only when that flag is present; otherwise THE Admin_Service SHALL respond with a 409 conflict error.
4. WHEN an Admin imports or replaces a question pool, THE Admin_Service SHALL validate that no two Questions in the pool share the same id and SHALL reject the import on any duplicate id.

### Requirement 17: Admin Mock Exam and Analytics

**User Story:** As an admin, I want to reset mock exam attempts, view analytics, and export the database, so that I can support learners and operate the platform.

#### Acceptance Criteria

1. WHEN an Admin resets a Learner's mock exam attempts, THE Admin_Service SHALL delete that Learner's Mock_Exam attempt records and SHALL NOT modify any other progress.
2. WHEN an Admin requests analytics, THE Admin_Service SHALL return at minimum: total registered users, count of `VERIFIED` users, count of banned users, total Lessons completed, total quiz attempts, total mock exam attempts, mock exam pass rate, and the 10 Subtopics with the lowest average quiz score.
3. WHEN an Admin requests a database export, THE Admin_Service SHALL produce a single export artifact containing all persisted application data in a documented structured format and SHALL exclude password hashes, OTP records, and Session_Tokens.
4. WHEN an Admin creates an announcement, THE Notification_Service SHALL display the announcement to all matching Learners on their next Learner-facing page load until the announcement's expiry timestamp.

### Requirement 18: Question Bank Quality Constraints

**User Story:** As a content owner, I want every served question to meet a minimum quality bar, so that learners trust the platform.

#### Acceptance Criteria

1. THE Content_Service SHALL refuse to serve any Question that does not have a non-empty stem, exactly one correct answer, a non-empty explanation, a defined difficulty in `{EASY, MEDIUM, HARD}`, and a defined type in the supported set.
2. THE Content_Service SHALL refuse to serve any `MULTIPLE_CHOICE` Question with fewer than 2 or more than 6 options.
3. THE Content_Service SHALL refuse to serve any Question whose correct-answer field does not exactly match one of its option values (for `MULTIPLE_CHOICE` and `IDENTIFICATION` types).
4. WHEN the Content_Service rejects a Question by Requirements 18.1, 18.2, or 18.3, THE Content_Service SHALL log the rejection with the Question id and the failed rule and SHALL exclude the Question from any quiz assembly.

### Requirement 19: Mock Exam Anti-Cheat

**User Story:** As a learner, I want the mock exam to behave like a real exam, so that my score reflects true readiness.

#### Acceptance Criteria

1. WHILE a Mock_Exam attempt is in progress, THE Mock_Exam_Service SHALL prevent the Learner from navigating directly to Lessons or other quizzes via the API and SHALL respond to such requests with a 409 `exam in progress` error.
2. WHILE a Mock_Exam attempt is in progress, THE Mock_Exam_Service SHALL record every focus-loss event reported by the client in the attempt record without changing the timer.
3. THE Mock_Exam_Service SHALL compute and authoritatively enforce the remaining time on the server side and SHALL NOT trust client-reported elapsed time.
4. THE Mock_Exam_Service SHALL not allow a Learner to revisit a Question after the Question has been marked as submitted within the same attempt unless the attempt UI explicitly supports navigation; navigation policy SHALL be defined in `mock_exam_config`.

### Requirement 20: Offline / PWA Support

**User Story:** As a learner with intermittent connectivity, I want to study lessons and take practice quizzes without an internet connection, so that I am not blocked by network issues.

#### Acceptance Criteria

1. THE System SHALL be installable as a Progressive Web App on a modern desktop browser, including a manifest, an icon set, and a registered service worker.
2. WHILE the device is offline AND the Learner has previously authenticated within the past 24 hours, THE System SHALL allow the Learner to: open previously fetched Lessons, take Subtopic_Quizzes for which the question pool was previously fetched, and accumulate progress and XP locally.
3. WHEN connectivity is restored, THE System SHALL synchronize locally accumulated progress and XP to the server and SHALL resolve conflicts by preferring the record with the later client timestamp.
4. (Phase 2) WHILE the device is offline, THE Mock_Exam_Service SHALL NOT permit a new Mock_Exam attempt to start.

### Requirement 21: Auditability and Logging

**User Story:** As an operator, I want every security-relevant event logged, so that I can investigate incidents.

#### Acceptance Criteria

1. THE Auth_Service SHALL log every signup, login (success and failure), logout, password reset, OTP issuance, and OTP verification attempt with timestamp, account id (where known), and outcome.
2. THE Admin_Service SHALL log every admin action as defined in Requirement 15.5.
3. IF any logged event includes a password, OTP code, Session_Token value, or password hash, THEN the logging layer SHALL redact the field before writing.
4. THE System SHALL include a request correlation id on every server log line generated while handling a request and SHALL return that id to the client in a response header.

### Requirement 22: Performance and Capacity (Local Deployment)

**User Story:** As a learner, I want the app to feel responsive on a typical laptop, so that studying is not interrupted by lag.

#### Acceptance Criteria

1. WHEN a Learner requests a Lesson, the Content_Service SHALL respond within 300 ms at the 95th percentile on the local development hardware specified in `perf_baseline_config`.
2. WHEN a Learner starts any quiz or Mock_Exam, the assembly response SHALL complete within 800 ms at the 95th percentile on the local development hardware specified in `perf_baseline_config`.
3. THE System SHALL support at least 50 concurrent active Learner sessions on the local development hardware specified in `perf_baseline_config` without violating Requirements 22.1 or 22.2.

### Requirement 23: Accessibility and UI Conformance

**User Story:** As a learner using a keyboard or screen reader, I want the UI to be navigable and readable, so that I can study regardless of input device.

#### Acceptance Criteria

1. THE UI SHALL apply Helvetica (with a documented fallback stack) as the global font on all Learner-facing and Admin-facing screens.
2. THE UI SHALL render correctly on viewport widths from 360 px to 1920 px without horizontal scrolling on the primary content column.
3. THE UI SHALL support full keyboard navigation of all interactive elements with a visible focus indicator that meets a minimum 3:1 contrast ratio against its background.
4. THE UI SHALL provide an accessible name (via `aria-label`, visible label, or `aria-labelledby`) for every interactive element.
5. THE UI SHALL meet WCAG 2.1 Level AA color-contrast requirements for all text in the default theme and the dark theme.
6. (Phase 2) THE UI SHALL provide a dark-mode toggle that persists per Learner.

### Requirement 24: Data Lifecycle and Backup

**User Story:** As an operator, I want a way to back up and restore the database, so that learner progress is not lost on reinstall.

#### Acceptance Criteria

1. THE System SHALL provide an admin-triggered export action that produces a single artifact containing all persisted Learner, content, progress, attempt, XP, and achievement data, excluding the fields named in Requirement 17.3.
2. THE System SHALL provide an admin-triggered import action that restores from an artifact produced by Requirement 24.1 and SHALL validate referential integrity before committing the import.
3. IF an import artifact fails referential integrity validation, THEN THE System SHALL reject the import without modifying any existing data and SHALL return a report listing every failed reference.

### Requirement 25: Content Seeding and Question Bank Generation

**User Story:** As an admin, I want to seed the platform with pre-authored lesson content and question banks for each subtopic, so that learners have sufficient high-quality content to study and practice with from day one.

#### Acceptance Criteria

1. THE Admin_Service SHALL support bulk-loading of lesson content and question banks from structured data files, where lessons are authored in Markdown and question banks are authored in JSON.
2. WHEN a lesson content file is submitted for import, THE Admin_Service SHALL validate that the content conforms to the LessonContent schema defined in Requirement 6.3 (at least one explanation section, at least one worked example, a key-takeaways section, and a mini summary).
3. WHEN a question bank file is submitted for import, THE Admin_Service SHALL validate that every Question in the file conforms to the QuestionCreate schema and passes the quality gate defined in Requirements 18.1, 18.2, and 18.3.
4. THE Admin_Service SHALL support bilingual content (English and Filipino) for all lesson content and question banks targeting the Philippine Civil Service Examination.
5. THE Admin_Service SHALL accept question banks tagged for either the `PROFESSIONAL` or `SUB_PROFESSIONAL` category level and SHALL validate that the category tag matches the target Subtopic's parent Module category.
6. WHEN a subtopic question bank is submitted for import, THE Admin_Service SHALL reject the import with an `insufficient pool depth` error IF the file contains fewer than 500 Questions for that Subtopic.
7. WHEN a question bank is submitted for import, THE Admin_Service SHALL validate that the difficulty distribution across the file approximates the target ratio of 40% Easy, 40% Medium, and 20% Hard, with a tolerance of plus or minus 5 percentage points per difficulty level.
8. THE Admin_Service SHALL accept question banks containing varied question types including direct questions, sentence correction, error recognition, logical completion, and contextual application, and SHALL validate that each Question's type field is within the supported set defined in Requirement 18.1.
9. WHEN the admin bulk-import endpoint (`POST /v1/admin/questions:bulk-import`) receives a question bank file, THE Admin_Service SHALL validate the entire file against Requirements 25.2 through 25.8 and SHALL reject the file in its entirety if any Question fails validation, returning a report listing every failed Question id and the violated rule(s).
10. WHEN the admin lesson create or update endpoint receives a lesson content file, THE Admin_Service SHALL validate the file against Requirement 25.2 and SHALL reject the file if validation fails, returning a report listing the missing or invalid sections.
