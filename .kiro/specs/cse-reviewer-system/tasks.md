# Implementation Plan: CSE Reviewer System

## Overview

This plan implements the FastAPI + SQLAlchemy + SQLite backend and the React PWA frontend for the CSE Reviewer System, sequenced so that prerequisite infrastructure (DB engine, base repository, security primitives, middlewares) lands before any feature slice depends on it. Each feature slice produces three test files per `testing-standards.md` (`test_repository.py`, `test_service.py`, `test_router.py`), and property-based tests using `hypothesis` are required (not optional) sub-tasks for the 37 correctness properties defined in `design.md`.

**Asterisk convention:** sub-tasks marked `- [ ]*` are Phase 2 and may be deferred. Unmarked sub-tasks are MVP and required. Per the workflow rule, the implementer MUST NOT implement asterisked sub-tasks; they are listed so Phase 2 work has a known landing surface but does not block MVP shipping.

**Sequencing rationale:** Shared infrastructure → security primitives → auth + otp → users + admin guards → content + quality gate → progress + xp ledger → quizzes (subtopic → topic → module) → mock exams (MVP 50q first, then Phase 2 165q + offline-block) → leaderboards → achievements → admin (analytics/export/import) → audit log surfacing → PWA shell + service worker + IndexedDB sync → wiring + smoke run.

## Tasks

- [ ] 1. Project scaffolding and shared infrastructure
  - [x] 1.1 Initialize Python project layout
    - Create `pyproject.toml` with dependencies: `fastapi`, `uvicorn[standard]`, `sqlalchemy`, `pydantic`, `bcrypt`, `pyjwt`, `apscheduler`, `python-multipart`
    - Create dev-dependencies: `pytest`, `pytest-mock`, `hypothesis`, `httpx`, `bandit`, `mypy`, `ruff`
    - Create the `app/` package skeleton matching the folder tree in design (`app/main.py`, `app/common/`, `app/infrastructure/`, `app/features/`)
    - Create `tests/` skeleton mirroring `app/features/`
    - _Requirements: stack alignment per design "Stack decision"_

  - [x] 1.2 Implement database engine, session, and SQLite pragmas
    - Implement `app/infrastructure/database/base.py` with declarative `Base`
    - Implement `app/infrastructure/database/session.py` (engine, `SessionLocal`, `get_db` generator)
    - Implement `app/infrastructure/database/pragmas.py` registering an `event.listens_for(Engine, "connect")` callback that sets `journal_mode=WAL`, `synchronous=NORMAL`, `foreign_keys=ON`, `temp_store=MEMORY`, `mmap_size=268435456`
    - _Requirements: 14.1, 22.3, 24.2_

  - [x] 1.3 Implement `BaseRepository[ModelType]`
    - In `app/infrastructure/repositories/base.py`: generic `get`, `list(skip, limit)`, `create`, `update`, `delete` methods using SQLAlchemy ORM
    - All methods accept a `Session`; no module-level state
    - _Requirements: 22.1, 22.2 (predictable indexed access)_

  - [x] 1.4 Implement common request/response schemas
    - `app/common/schemas/request.py`: `PaginationParams` with `skip >= 0`, `1 <= limit <= 100` validators
    - `app/common/schemas/response.py`: generic `PaginatedResponse[T]` (`items, total, skip, limit`) and `ErrorResponse` (`error.message`, `error.code`)
    - _Requirements: 15.2, api-standard.md error envelope_

  - [x] 1.5 Implement middlewares
    - `app/common/middlewares/error_handler.py`: catch unhandled exceptions, return generic 500 `ErrorResponse` without stack trace
    - `app/common/middlewares/logging.py`: read or generate `X-Request-ID` (UUIDv4), bind into `request.state.request_id`, attach to structured-log context, echo header on response, redact field names `password`, `password_hash`, `code`, `otp_code`, `token`, `authorization`
    - `app/common/middlewares/auth.py`: decode bearer JWT, load user, attach to `request.state.user`; defer 401/403 decisions to dependencies
    - _Requirements: 21.3, 21.4_

  - [x] 1.6 Write property tests for request correlation and redaction
    - **Property 33: Audit log redaction** — for any payload containing redaction-listed field names, the emitted log line and audit row contain `***REDACTED***` and never the value
    - **Property 34: Request correlation propagation** — response `X-Request-ID` equals `request.state.request_id` and equals the value on every log line; missing client header → fresh UUIDv4
    - **Validates: Requirements 21.3, 21.4**

- [ ] 2. Security primitives
  - [x] 2.1 Implement password hashing
    - `app/infrastructure/security/passwords.py`: `hash_password`, `verify_password` using `bcrypt` with `rounds >= 10` constant
    - _Requirements: 1.6_

  - [x] 2.2 Implement JWT encode/decode
    - `app/infrastructure/security/jwt.py`: HS256 with secret from env var; encode claims `sub, jti, iat, exp` (24h); decode raising on invalid/expired signature
    - _Requirements: 3.1, 3.5_

  - [x] 2.3 Implement RNG wrapper
    - `app/infrastructure/security/rng.py`: thin wrapper over `secrets.SystemRandom` exposing `randbits`, `sample`, `shuffle`, `randbelow_six_digits`
    - _Requirements: 7.3, 10.1, 10.2 (assembly randomization), 2.1 (OTP)_

  - [x] 2.4 Write unit tests for security primitives
    - Test bcrypt round trip, cost-factor assertion, plaintext never returned
    - Test JWT round trip, expired-token rejection, tampered-signature rejection
    - _Requirements: 1.6, 3.1, 3.5_

- [ ] 3. External adapters and scheduler skeleton
  - [x] 3.1 Implement `ExternalServiceBase` ABC
    - `app/infrastructure/external/base.py` per `security-policy.md`
    - _Requirements: extension surface for OTP delivery_

  - [x] 3.2 Implement OTP delivery adapters
    - `app/infrastructure/external/smtp_otp_sender.py`: stub online sender (env-gated, no-op when SMTP host unset for MVP)
    - `app/infrastructure/external/offline_otp_writer.py`: append `{timestamp, email, purpose, code}` to `data/otp_offline.log`
    - _Requirements: 2.1, 2.8_

  - [x] 3.3 Implement scheduler jobs
    - `app/infrastructure/scheduler/jobs.py`: APScheduler with hourly OTP cleanup job (delete rows where `expires_at < now - 24h`) and daily offline-OTP log rotation (rotate + gzip)
    - Wire scheduler start/stop into `main.py` lifespan
    - _Requirements: 2.1, 2.8_

  - [x] 3.4 Write unit tests for offline OTP writer
    - Verify file is created with restrictive permissions, lines are append-only, plaintext code is written exactly once per call
    - _Requirements: 2.8_

- [ ] 4. Auth + OTP slice (auth + otp + sessions + lockouts)
  - [x] 4.1 Implement `users.models` (User ORM) and `users.schemas`
    - `app/features/users/models.py`: `User` table per design (email lowercased UNIQUE, age CHECK 15..100, category CHECK enum, role default LEARNER, account_state default UNVERIFIED, is_banned, tz_name, password_hash, cross_category_preview)
    - `app/features/users/schemas.py`: `UserCreate`, `UserUpdate`, `UserResponse` with `from_attributes=True`
    - Custom Pydantic validators: password rule (Req 1.3), age range (Req 1.4), category enum (Req 1.5), email lowercased
    - _Requirements: 1.1, 1.3, 1.4, 1.5, 1.6, 15.1, 15.3_

  - [x] 4.2 Implement `users.repository`
    - `get_by_email`, `create`, `set_account_state`, `set_banned`, `delete_with_progress_cascade`, `paginated_admin_list(filters)`
    - _Requirements: 1.1, 1.2, 15.2, 15.3, 15.4_

  - [x] 4.3 Implement OTP slice models, schemas, and repository
    - `app/features/otp/models.py`: `OTP` table per design (purpose enum, code_hash, expires_at, used, invalidated, attempt_count) with required indexes
    - Schemas: `OTPIssueRequest`, `OTPVerifyRequest`
    - Repository methods: `count_issuances_in_last_60min(user_id)`, `invalidate_unused_for(user_id, purpose)`, `get_latest_active(user_id, purpose)`, `bump_attempt(otp)`, `mark_used(otp)`, `mark_invalidated(otp)`
    - _Requirements: 2.1, 2.5, 2.6, 2.7_

  - [x] 4.4 Implement OTP service
    - `issue(user_id, purpose, mode)`: rate-limit check → invalidate prior unused → generate 6-digit code via `rng.randbelow_six_digits` → bcrypt-hash → persist → deliver via online + offline adapters per `mode`
    - `verify(email, code, purpose)`: load user by email → load latest active OTP → expiry check → attempt-count bump → bcrypt verify → on success mark used and return user; all failures return canonical `otp_invalid_or_expired` (do not differentiate)
    - _Requirements: 2.1, 2.2, 2.3, 2.5, 2.6, 2.7, 2.8_

  - [x] 4.5 Write property tests for OTP state machine
    - **Property 3: OTP issuance shape** — issued record satisfies all invariants; code_hash != plaintext
    - **Property 4: OTP single-use and generic failure** — second verify after success returns canonical error; failure responses byte-equal across (wrong, expired, used, invalidated)
    - **Property 5: At-most-one active OTP per (user, purpose)** — invariant after every event
    - **Property 6: OTP issuance rate limit** — (k+1)-th issuance in 60min window rejected when k >= 5
    - **Property 7: OTP verification attempt cap** — invalidated on 6th attempt regardless of correctness thereafter
    - **Validates: Requirements 2.1, 2.2, 2.3, 2.5, 2.6, 2.7**

  - [x] 4.6 Implement sessions and login-attempt models + repository
    - `app/features/auth/models.py`: `Session` (jti PK, user_id, issued_at, expires_at, revoked_at), `LoginAttempt(user_id, attempted_at, success)`, `UserLockout(user_id PK, locked_until)`
    - Repository methods: `create_session`, `revoke_session_by_jti`, `revoke_all_for_user`, `is_jti_active`, `record_login_attempt`, `failed_count_in_window(user_id, since)`, `set_lockout`, `get_lockout`
    - _Requirements: 3.1, 3.3, 3.4, 4.4_

  - [x] 4.7 Implement auth service
    - `signup(payload)`: validate uniqueness → bcrypt → insert User UNVERIFIED → trigger `otp_service.issue(VERIFY_EMAIL)` in same transaction
    - `verify_email(payload)`: delegate to `otp_service.verify` then transition account to VERIFIED and invalidate the OTP
    - `login(email, password)`: lockout check → bcrypt verify → record attempt → on success mint JWT and persist session row; on failure increment attempt and set lockout if threshold crossed
    - `logout(jti)`: set `revoked_at`
    - `request_password_reset(email)`: same response shape regardless of whether email exists; if exists, issue PASSWORD_RESET OTP
    - `reset_password(payload)`: verify reset OTP → update password_hash → revoke all sessions for user
    - _Requirements: 1.1, 1.2, 2.2, 2.4, 3.1, 3.2, 3.3, 3.4, 4.1, 4.2, 4.3, 4.4_

  - [x] 4.8 Write property tests for auth state machines
    - **Property 1: Password rule completeness** — validator iff all 5 rules
    - **Property 2: Age range bounds** — accepts iff 15 <= n <= 100
    - **Property 8: Session token validity window** — JWT claims `iat`, `exp == iat + 24h`, fresh UUIDv4 jti, `revoked_at == NULL`
    - **Property 9: Login lockout** — locked iff >= 5 failures in 15-minute window ending at most-recent failure; expires 15min later
    - **Property 10: Forgot-password enumeration resistance** — byte-equal response across existing/non-existing email
    - **Property 11: Password reset invalidates all sessions** — every prior session row has `revoked_at != NULL`; subsequent requests with old tokens return 401
    - **Validates: Requirements 1.3, 1.4, 3.1, 3.3, 4.2, 4.4**

  - [x] 4.9 Implement auth and otp routers
    - `app/features/auth/router.py`: `POST /v1/auth/signups`, `POST /v1/auth/email-verifications`, `POST /v1/auth/email-verifications:resend`, `POST /v1/auth/sessions`, `DELETE /v1/auth/sessions/me`, `POST /v1/auth/password-reset-requests`, `POST /v1/auth/password-resets`
    - `app/features/otp/router.py`: internal-only helpers if any (otherwise OTP is invoked through auth router)
    - All routers use `Depends(get_auth_service)` factory; no business logic in routes
    - _Requirements: 1.1, 2.2, 2.5, 3.1, 3.4, 4.1, 4.3_

  - [x] 4.10 Write router tests for auth + otp
    - One happy-path + one 422 validation-failure per endpoint
    - 401 on missing token; 403 on banned user attempting `DELETE /v1/auth/sessions/me`
    - Verify `X-Request-ID` is echoed
    - _Requirements: 1.1–1.5, 2.2, 2.4, 3.1, 3.2, 3.4, 4.1–4.4_

- [ ] 5. Common dependencies (`get_current_user`, `require_admin`, `require_no_active_mock`)
  - [x] 5.1 Implement `app/common/deps.py`
    - `get_current_user`: decode JWT via middleware-attached state → load user → reject 401 if expired/revoked, 403 if `is_banned` (Req 15.3)
    - `require_admin`: depends on `get_current_user` and asserts `role == ADMIN`, else 403
    - `require_no_active_mock`: queries `mock_exam_attempts` for an `IN_PROGRESS` row; if found, raises 409 `exam_in_progress`
    - _Requirements: 3.5, 15.1, 15.3, 19.1_

  - [x] 5.2 Write service-layer tests for guards
    - Happy path, expired token, revoked token, banned user, non-admin hitting admin route
    - _Requirements: 3.5, 15.1, 15.3_

- [x] 6. Checkpoint - Auth slice green
  - Ensure all auth + OTP unit, property, and router tests pass; ask the user if questions arise.

- [ ] 7. Content slice (modules, topics, subtopics, lessons, questions + quality gate)
  - [x] 7.1 Implement content models
    - `app/features/content/models.py`: `Module`, `Topic`, `Subtopic`, `Lesson` (`content_json`, `status` enum), `Question` (denormalized `topic_id`, `module_id`, `category`, `level_scope`, `qtype` enum, `difficulty` enum, `options` JSON), `QuestionRejectionLog`
    - Required indexes per design: `questions(subtopic_id, is_active)`, `(topic_id, is_active, level_scope)`, `(module_id, is_active, level_scope)`, `(category, is_active)`
    - _Requirements: 5.1, 5.2, 6.3, 6.4, 16.1, 16.2, 18.1, 22.2_

  - [x] 7.2 Implement Pydantic schemas with `LessonContent` validator
    - `LessonContent`: `>=1 explanations`, `>=1 worked_examples`, non-empty `key_takeaways`, non-empty `summary` (Req 6.3)
    - `QuestionCreate`/`QuestionUpdate`: enforce 2..6 options for MULTIPLE_CHOICE, exactly-one correct, non-empty stem and explanation, `correct_answer ∈ options` for MULTIPLE_CHOICE/IDENTIFICATION
    - _Requirements: 6.3, 16.2, 18.1, 18.2, 18.3_

  - [x] 7.3 Implement quality-gate predicate
    - `app/features/content/algorithms/quality_gate.py`: `valid_question_filter()` returning a SQLAlchemy boolean expression encoding all 18.1–18.3 rules
    - Used by every assembly query and by admin-write validation
    - _Requirements: 18.1, 18.2, 18.3, 18.4_

  - [x] 7.4 Implement content repositories
    - `module_repository.py`, `topic_repository.py`, `subtopic_repository.py`, `lesson_repository.py`, `question_repository.py` each with feature-specific queries (`list_by_category`, `list_active_passing_quality_gate(subtopic_id|topic_id|module_id, category, level_scope)`, `log_rejection(question_id, rule)`)
    - Repository tests against in-memory SQLite verify quality-gate predicate excludes bad questions
    - _Requirements: 5.1, 5.2, 6.4, 18.1–18.4, 22.2_

  - [x] 7.5 Implement content services
    - `ModuleService`, `LessonService`, `QuestionService`: read-side category isolation (raise 403 on mismatch — never 404 per `security-policy.md`); admin-side create/update with quality-gate validation; on validate-fail-on-write, log to `question_rejection_log` and reject
    - _Requirements: 5.1, 5.2, 5.3, 6.4, 16.1, 16.2, 18.1–18.4_

  - [x] 7.6 Write property tests for content slice
    - **Property 12: Category isolation** — 200 iff `user.category == resource.category` (or Phase 2 cross-category-preview); else 403, never 404
    - **Property 13: Lesson content schema completeness** — accepts iff all required sections present; INCOMPLETE lessons hidden from learners
    - **Property 28: Question quality gate enforcement** — q appears in any assembly iff all gate predicates hold; rejection logged exactly once per failing rule
    - **Validates: Requirements 5.1, 5.2, 5.3, 6.3, 6.4, 18.1, 18.2, 18.3, 18.4**

  - [x] 7.7 Implement content routers
    - `GET /v1/modules`, `GET /v1/modules/{id}`, `GET /v1/modules/{id}/topics`, `GET /v1/topics/{id}/subtopics`, `GET /v1/subtopics/{id}/lesson`, `POST /v1/subtopics/{id}/lesson:complete`
    - All read routes depend on `get_current_user` and `require_no_active_mock`
    - _Requirements: 5.1, 5.2, 5.3, 6.2, 6.4, 19.1_

  - [x] 7.8 Write router tests for content
    - Happy path + 422 + 401 + 403 (wrong category) + 409 (mock-in-progress) per route
    - _Requirements: 5.3, 6.2, 19.1_

- [ ] 8. Progress slice and lesson completion
  - [x] 8.1 Implement progress models and repository
    - `app/features/progress/models.py`: `LessonCompletion` (UNIQUE `(user_id, lesson_id)`, nullable UNIQUE `client_event_id`), `UserTopicProgress`, `UserModuleProgress`
    - Repository: `get_by_client_event_id`, `mark_lesson_complete(user, lesson, client_event_id, completed_at)`, `is_lesson_complete(user, subtopic_id)`, `mark_topic_complete(user, topic_id)`, `mark_module_complete(user, module_id)`
    - _Requirements: 6.2, 8.5, 9.4, 14.1, 14.4, 20.3_

  - [x] 8.2 Implement progress service for lesson completion + snapshot
    - `complete_lesson`: persist before responding; trigger XP `LESSON_FIRST_COMPLETE` (20 XP) only on first completion per (user, lesson)
    - `get_snapshot(user)`: returns most-recent lesson position, IN_PROGRESS quizzes/mock attempts (with elapsed time and persisted answers), current XP/level/streak; auto-submits any expired mock attempt as part of snapshot read
    - _Requirements: 6.2, 11.2, 14.1, 14.2, 14.3, 14.4_

  - [x] 8.3 Write property tests for progress
    - **Property 24: Progress durability before response** — DB observably persisted before HTTP response returns
    - **Property 25: Resume snapshot fidelity** — snapshot fully reconstructs prior session; expired mock attempts auto-submitted in the snapshot
    - **Validates: Requirements 14.1, 14.2, 14.3, 14.4**

  - [x] 8.4 Implement progress router
    - `POST /v1/subtopics/{id}/lesson:complete`, `GET /v1/progress/snapshot`
    - _Requirements: 6.2, 14.2_

  - [x] 8.5 Write router tests for progress
    - Happy path + 422 + 401 + 403 (banned) + 409 (mock-in-progress) per route
    - _Requirements: 6.2, 14.2, 19.1_

- [ ] 9. XP slice (events, level math, streak)
  - [x] 9.1 Implement XP models and repository
    - `app/features/xp/models.py`: `UserXP` (single row per user with `cumulative_xp`, `level`, `level_reached_at`, `streak_count`, `last_activity_at`, `last_streak_day`), `XPEvent` (append-only ledger with closed `source` enum, `client_event_id` nullable UNIQUE)
    - Index: `xp_events(user_id, occurred_at DESC)`
    - Repository: `insert_event_and_recompute(user_id, source, amount, occurred_at, source_ref_id, client_event_id)`, `get_user_xp(user_id)`, `sum_in_window(user_id, since, until)`
    - _Requirements: 11.1, 11.4, 11.7, 12.2, 12.3_

  - [x] 9.2 Implement level math and streak rollover algorithms
    - `app/features/xp/algorithms/level.py`: `level_of(cumulative_xp)` per design A3 (closed-form root + 2-step correction)
    - `app/features/xp/algorithms/streak.py`: `on_qualifying_activity(user, now_utc)` and `streak_for_read(user, now_utc)` per design A4 (timezone-aware via `ZoneInfo(user.tz_name)`; 36h decay rule)
    - _Requirements: 11.3, 11.4, 11.6_

  - [x] 9.3 Implement XP service
    - `award(user, source, amount, occurred_at, source_ref_id=None, client_event_id=None)`: rejects sources outside the closed set; rejects negative amounts unless `source==ADMIN_CORRECTION`; inserts event, updates `cumulative_xp` and `level` denormalized cache, sets `level_reached_at` on level threshold cross, triggers achievement evaluator hook
    - Per-source amount table from Req 7.6, 7.7, 8.4, 9.4, 10.6, 11.2, 11.3 enforced at the service edge
    - `notify_level_up(user, new_level)` emits via Notification_Service (in-app toast surface; for MVP, return value annotation only)
    - _Requirements: 7.6, 7.7, 8.4, 9.4, 10.6, 11.1, 11.2, 11.3, 11.5, 11.7_

  - [x] 9.4 Write property tests for XP and streak
    - **Property 19: Level mapping correctness and monotonicity** — `level_of(xp) == max{N : 50*N*(N+1) <= xp}`; non-decreasing in xp
    - **Property 20: Streak rollover** — across multi-tz timelines: 0 if last_activity null or > 36h gap; otherwise length of longest consecutive-calendar-day tail with consecutive events <= 36h apart; STREAK_DAY 25 XP awarded exactly once per new tail-day
    - **Property 21: XP monotonicity and closed-source ledger** — non-decreasing for non-correction sources; cumulative >= 0 always; insert with disallowed source rejected
    - **Validates: Requirements 11.1, 11.3, 11.4, 11.6, 11.7**

  - [x] 9.5 Implement XP router
    - `GET /v1/xp/me`
    - _Requirements: 11.4, 11.6_

  - [x] 9.6 Write router tests for XP
    - Happy path + 401; verify `cumulative`, `level`, `streak` fields present and decay applied on read
    - _Requirements: 11.4, 11.6_

- [x] 10. Checkpoint - Content + Progress + XP green
  - Ensure all tests pass for content, progress, and XP slices; ask the user if questions arise.

- [ ] 11. Quizzes slice (subtopic 20q + topic 50q + module 100q)
  - [x] 11.1 Implement quiz models and repository
    - `app/features/quizzes/models.py`: `QuizAttempt` (scope_level enum, scope_id, status, score, max_score, seed, nullable UNIQUE `client_event_id`), `QuizAttemptAnswer` (UNIQUE `(attempt_id, question_id)`)
    - Repository: `create_attempt`, `set_answer`, `submit`, `has_passed_attempt(user, scope_level, scope_id)`, `get_in_progress_attempts(user)`, `get_by_client_event_id`
    - _Requirements: 7.1, 7.4, 7.5, 8.1, 8.2, 8.5, 9.1, 9.2, 9.4, 14.1_

  - [x] 11.2 Implement quiz assembly algorithm
    - `app/features/quizzes/algorithms/assembly.py`: `assemble(scope_level, scope_id, count, rng_seed)` — single SQL query with `valid_question_filter()`, in-process sample of size `count`, raise 409 `insufficient_question_pool` if pool < count, then per-question option shuffle for MULTIPLE_CHOICE, persist `seed` for reproducibility (Req 21 audit)
    - Counts: SUBTOPIC=20 (Req 7.1), TOPIC=50 (Req 8.2), MODULE=100 (Req 9.2)
    - _Requirements: 7.1, 7.2, 7.3, 8.2, 9.2, 18.4_

  - [x] 11.3 Implement quiz grading algorithm
    - `app/features/quizzes/algorithms/grading.py`: per-question correctness, score, perfect/passing flags; pass threshold = 0.80 for topic/module
    - _Requirements: 7.5, 7.6, 7.7, 8.4, 9.4_

  - [x] 11.4 Implement quiz service
    - `start_subtopic_quiz(user, subtopic_id)`: lesson-completed gate (Req 6.1) → assemble 20 → persist attempt
    - `start_topic_quiz(user, topic_id)`: prerequisite gate — every subtopic-quiz under T passed (Req 8.1) → assemble 50
    - `start_module_quiz(user, module_id)`: prerequisite gate — every topic-quiz under M passed (Req 9.1) → assemble 100
    - `set_answer(attempt_id, question_id, selected)`: persist BEFORE responding; never reveals correctness mid-attempt
    - `submit(attempt_id)`: grade, persist, on perfect/pass trigger `xp_service.award` with the correct source (`QUIZ_PERFECT` 50 XP for perfect 20/20 subtopic, `QUIZ_PASS` 20 XP for non-perfect passing subtopic, 100 XP for topic pass, 250 XP for module pass), mark topic/module complete when applicable, return per-question correct/explanation
    - _Requirements: 6.1, 7.1, 7.4, 7.5, 7.6, 7.7, 8.1, 8.2, 8.4, 8.5, 9.1, 9.2, 9.4, 14.1_

  - [x] 11.5 Write property tests for quiz assembly and grading
    - **Property 14: Lesson-before-quiz gating** — POST subtopic quiz succeeds iff `lesson_completions` row exists; else 409 `lesson_not_completed`
    - **Property 15: Question-count exactness** — assembled list has exactly `count(S)`; every item drawn from the correct scope's pool; every item passes the quality filter
    - **Property 16: Randomization across attempts** — distinct seeds produce distinct orderings (non-degeneracy); per-MC option order independently shuffled
    - **Property 17: Mid-attempt non-disclosure** — IN_PROGRESS responses never contain `is_correct`, `correct_answer`, `explanation`
    - **Property 18: Prerequisite gating for higher-scope quizzes** — topic/module-quiz start succeeds iff all prerequisite scope quizzes have been passed
    - **Validates: Requirements 6.1, 7.1, 7.3, 7.4, 8.1, 8.2, 9.1, 9.2**

  - [x] 11.6 Implement quiz router
    - `POST /v1/subtopics/{id}/quiz-attempts`, `POST /v1/topics/{id}/quiz-attempts`, `POST /v1/modules/{id}/quiz-attempts`, `GET /v1/quiz-attempts/{id}`, `PATCH /v1/quiz-attempts/{id}/answers/{qid}`, `POST /v1/quiz-attempts/{id}:submit`
    - All depend on `get_current_user` + `require_no_active_mock`
    - _Requirements: 7.1, 7.4, 7.5, 8.1, 8.2, 9.1, 9.2, 19.1_

  - [x] 11.7 Write router tests for quizzes
    - Happy path + 422 + 401 + 403 (wrong category) + 409 (lesson-not-completed) + 409 (prereq-not-met) + 409 (mock-in-progress) per route
    - _Requirements: 6.1, 7.1, 8.1, 9.1, 19.1_

- [ ] 12. Mock exam slice — MVP (50 questions, no offline blocking)
  - [x] 12.1 Implement mock-exam config and models
    - `app/features/mock_exams/models.py`: `MockExamConfig` (one row per category; `total_questions` set to 50 for MVP, `weights_json` summing to 50, `time_limit_minutes=180`, `nav_policy`, `pass_threshold=0.80`), `MockExamAttempt` (status enum, seed, `focus_loss_events` JSON), `MockExamAttemptAnswer` (UNIQUE `(attempt_id, ordinal)`, `finalized_at` nullable)
    - Partial unique index on `mock_exam_attempts(user_id) WHERE status='IN_PROGRESS'` (Req 10.8)
    - _Requirements: 10.1, 10.2, 10.3, 10.7, 10.8, 19.4_

  - [x] 12.2 Implement mock-exam config validation
    - On admin write: weights sum equals `total_questions`; every `module_id` exists and matches `category`
    - _Requirements: 10.1, 10.2, 16.1_

  - [x] 12.3 Implement category-weighted assembler (50q for MVP)
    - `app/features/mock_exams/algorithms/category_weighted_assembly.py` per design A1 — per-module sample with the quality-gate filter, raise 409 `insufficient_question_pool` on any module short, final cross-module shuffle, per-MC option shuffle, persist seed
    - _Requirements: 10.1, 10.2, 18.4, 22.2_

  - [x] 12.4 Implement server-authoritative timer
    - `app/features/mock_exams/algorithms/timer.py`: `remaining_seconds(attempt, now)` = `max(0, time_limit*60 - (now - started_at).seconds)`; on `remaining == 0` and IN_PROGRESS, transition to SUBMITTED with `submission_mode=AUTO_SUBMIT` BEFORE any other side effect on the attempt
    - _Requirements: 10.3, 14.3, 19.3_

  - [x] 12.5 Implement mock-exam service
    - `start_attempt(user)`: `require_no_active_mock` already enforced at dependency; assemble; persist; return attempt with no correctness fields
    - `set_answer(attempt_id, qid, selected)`: timer check first; if LINEAR_NO_REVISIT and answer's `finalized_at` is set, raise 409 `question_finalized`; persist before responding
    - `report_focus_loss(attempt_id, kind, at)`: append to `focus_loss_events` JSON; do not touch `started_at` or remaining time
    - `submit(attempt_id, mode)`: grade, persist, on pass (>= 80%) award `MOCK_PASS` 500 XP, return result with `score`, `max_score`, `percentage`, `passed`, per-module breakdown, weakness summary (3 lowest %, ascending, tie-break by module_id), per-question `selected/correct/is_correct/explanation`
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 14.1, 14.3, 19.2, 19.3, 19.4_

  - [x] 12.6 Write property tests for mock-exam (MVP scope)
    - **Property 15 (mock branch): Question-count exactness for mock** — per-module count exactly equals `weights_json[module_id]`; total equals `total_questions`
    - **Property 17: Mid-attempt non-disclosure** — IN_PROGRESS responses never disclose correctness
    - **Property 29: Mock-exam in-progress guard** — every `/v1/{subtopics|topics|modules|quiz-attempts}/**` returns 409 `exam_in_progress` while a mock is IN_PROGRESS
    - **Property 30: Mock-exam timer authority** — `remaining` derived solely from server clock; on remaining==0 next request transitions to SUBMITTED + AUTO_SUBMIT BEFORE side effects; focus-loss does not modify timer
    - **Property 31: Linear-no-revisit navigation** — under LINEAR_NO_REVISIT, PATCH to a finalized answer returns 409; under FREE_NAV the same PATCH succeeds
    - **Property 35: Mock-exam result completeness and weakness ranking** — submitted result has all required fields; weakness_summary length 3 ascending tie-break by module_id
    - **Property 36: At-most-one in-progress mock attempt per user** — invariant under concurrent creation (one success + one 409)
    - **Validates: Requirements 10.1, 10.2, 10.3, 10.4, 10.5, 10.7, 10.8, 14.3, 19.1, 19.2, 19.3, 19.4**

  - [x] 12.7 Implement mock-exam router (MVP)
    - `POST /v1/mock-exams/attempts`, `GET /v1/mock-exams/attempts/{id}` (returns `remaining_seconds`), `PATCH /v1/mock-exams/attempts/{id}/answers/{qid}`, `POST /v1/mock-exams/attempts/{id}:report-focus-loss`, `POST /v1/mock-exams/attempts/{id}:submit`
    - _Requirements: 10.1, 10.2, 10.5, 19.2, 19.3_

  - [x] 12.8 Write router tests for mock-exam (MVP)
    - Happy path + 422 + 401 + 403 (wrong category) + 409 (`mock_exam_in_progress` on second start) per route
    - _Requirements: 10.1, 10.2, 10.5, 10.8_

- [ ] 13. Mock exam slice — Phase 2 augment (165 questions + offline blocking)
  - [x] 13.1 Update mock-exam config seed to 165 questions per category with CSC-published weights
    - Migration to update `total_questions` and `weights_json`
    - _Requirements: 10.1, 10.2_

  - [x] 13.2 Add offline-blocking surface
    - Service worker returns synthetic `409 mock_exam_offline_unavailable` for `POST /v1/mock-exams/attempts` when offline
    - UI hides the "Start Mock" button when offline
    - _Requirements: 20.4_

  - [x] 13.3 Property test for Phase 2 mock scale
    - Same Property 15 family parametrized at `count(MOCK)=165`
    - **Validates: Requirements 10.1, 10.2**

- [ ] 14. Leaderboards slice
  - [x] 14.1 Implement leaderboard repository (windowing queries)
    - `app/features/leaderboards/repository.py` + `algorithms/windowing.py`: ISO-week and calendar-month bounds per design A5; queries use SQLAlchemy `func.sum`, `func.coalesce`, `outerjoin` against `xp_events` with `WHERE account_state='VERIFIED' AND is_banned=0`; ORDER BY `xp_window DESC, level_reached_at ASC, user_id ASC`; LIMIT 100
    - Covering index on `user_xp(cumulative_xp DESC, level_reached_at ASC, user_id)` for global query
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5_

  - [x] 14.2 Implement leaderboard service
    - `global_top()`, `weekly_top()`, `monthly_top()` returning `LeaderboardEntry(display_name, level, xp_window, category)`
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5_

  - [x] 14.3 Write property tests for leaderboard
    - **Property 22: Leaderboard ordering and eligibility** — len <= 100; sort by (xp_window DESC, level_reached_at ASC, user_id ASC); only VERIFIED + not-banned; field shape matches spec; weekly/monthly window math correct
    - **Validates: Requirements 12.1, 12.2, 12.3, 12.4, 12.5**

  - [x] 14.4 Implement leaderboard router
    - `GET /v1/leaderboards/global` (MVP), `GET /v1/leaderboards/weekly`, `GET /v1/leaderboards/monthly`
    - _Requirements: 12.1, 12.2, 12.3_

  - [x] 14.5 Write router tests for leaderboard
    - Happy path + 401 + ordering verification on a small fixture
    - _Requirements: 12.1, 12.4, 12.5_

  - [x] 14.6 Promote weekly/monthly leaderboards to default UI surfaces (Phase 2)
    - PWA renders three tabs: global / weekly / monthly
    - _Requirements: 12.2, 12.3_

- [ ] 15. Achievements slice
  - [x] 15.1 Implement achievement models and seed data
    - `app/features/achievements/models.py`: `Achievement` (id TEXT PK, criterion_kind, criterion_value JSON), `UserAchievement` (UNIQUE `(user_id, achievement_id)`)
    - Seed MVP set: `FIRST_LESSON`, `STREAK_7_DAYS`, `LEVEL_10`
    - _Requirements: 13.1, 13.2, 13.3, 13.4_

  - [x] 15.2 Implement criterion evaluator and service
    - Evaluator hook called from `xp_service.award` after every event for the affected user; for each defined achievement, check criterion; if met and not already granted, insert `user_achievements` and emit `achievement_unlocked` notification (single emission)
    - _Requirements: 13.1, 13.2, 13.3_

  - [x] 15.3 Write property tests for achievements
    - **Property 23: Achievement uniqueness** — exactly one `user_achievements` row per (user, achievement); `granted_at` equals first satisfying event timestamp; exactly one `achievement_unlocked` notification emitted
    - **Validates: Requirements 13.2, 13.3**

  - [x] 15.4 Implement achievement router and tests
    - `GET /v1/achievements/me`
    - Router test: happy path + 401
    - _Requirements: 13.4_

  - [x] 15.5 Phase 2 achievement set
    - Add `FIRST_PERFECT_SUBTOPIC_QUIZ`, `FIRST_TOPIC_PASSED`, `FIRST_MODULE_PASSED`, `FIRST_MOCK_PASSED`, `STREAK_30_DAYS`, `LEVEL_25` seeds and criteria
    - _Requirements: 13.4_

- [ ] 16. Progress sync ingestion (offline → online)
  - [x] 16.1 Implement sync resolver
    - `app/features/progress/algorithms/sync_resolver.py` per design A8: idempotent on `client_event_id`, "later wins" on `client_timestamp` collision; rejects events whose causally-required prior events are missing with `prerequisite_missing`
    - _Requirements: 14.1, 20.3_

  - [x] 16.2 Implement sync service and router
    - `POST /v1/progress:sync` accepting `{events: [{client_event_id, kind, client_timestamp, payload}]}`; returns `{accepted: [...], rejected: [{client_event_id, reason}]}`
    - Per event, dispatch to lesson-completion / quiz-submission / xp-event handlers using existing services with `client_event_id` plumbed end-to-end
    - _Requirements: 14.1, 20.3_

  - [x] 16.3 Write property tests for sync resolver
    - **Property 32: Offline sync conflict resolution** — idempotent on `client_event_id`; later-wins on `client_timestamp`; re-submitting accepted set produces no further state change
    - **Validates: Requirements 14.1, 20.3**

  - [x] 16.4 Write router tests for sync
    - Happy path with mixed accepted/rejected; 401; 422 on malformed event
    - _Requirements: 20.3_

- [ ] 17. Admin slice (users, content, mock reset, analytics, export, import)
  - [x] 17.1 Implement admin user-management routes
    - `GET /v1/admin/users` paginated, `PATCH /v1/admin/users/{id}` (ban toggle, role), `DELETE /v1/admin/users/{id}` (cascade-delete progress, retain anonymized counter)
    - All routes depend on `require_admin`; all writes log to `audit_log` in the same transaction
    - _Requirements: 15.1, 15.2, 15.3, 15.4, 15.5_

  - [x] 17.2 Implement admin content-management routes
    - CRUD for modules / topics / subtopics / lessons / questions; `DELETE` honors `force=true` flag (Req 16.3); `POST /v1/admin/questions:bulk-import` with duplicate-id rejection (Req 16.4)
    - _Requirements: 16.1, 16.2, 16.3, 16.4_

  - [x] 17.3 Implement admin mock-attempt reset and analytics
    - `DELETE /v1/admin/users/{id}/mock-exam-attempts` (only mock attempts; preserve other progress)
    - `GET /v1/admin/analytics` returning total users, verified count, banned count, lessons completed, quiz attempts, mock attempts, mock pass rate, 10 lowest-avg-score subtopics
    - _Requirements: 17.1, 17.2_

  - [x] 17.4 Implement export and import
    - `app/features/admin/algorithms/export.py`: produce a single JSON artifact of all persisted application data, excluding `password_hash`, OTP rows, sessions
    - `app/features/admin/algorithms/import_validator.py` per design A10: parse staging, FK closure check, duplicate question id check, full transaction rollback on any error returning failed-references list, atomic commit on success
    - `POST /v1/admin/exports`, `POST /v1/admin/imports`
    - _Requirements: 17.3, 24.1, 24.2, 24.3_

  - [x] 17.5 Write property tests for admin cascades and import
    - **Property 26: Cascade delete and force-flag conflict** — DELETE without `force` on entity-with-progress returns 409 and changes nothing; with `force` deletes all transitive children + progress in one transaction; same holds for User DELETE
    - **Property 27: Referential integrity on import** — succeeds iff all unique-id and FK-closure rules hold; on rejection DB is byte-identical to pre-import; on success the artifact round-trips
    - **Validates: Requirements 15.4, 16.3, 16.4, 24.2, 24.3**

  - [x] 17.6 Implement announcements (Phase 2 surface, MVP just-the-data)
    - Models for `Announcement` and `AnnouncementDismissal` per design; admin POST route
    - _Requirements: 17.4_

  - [x] 17.7 Phase 2 announcement display
    - Frontend renders announcements until expiry; per-user dismissal persisted
    - _Requirements: 17.4_

  - [x] 17.8 Write router tests for admin slice
    - Happy path + 401 (no token) + 403 (non-admin) + 422 per route; force-flag cascade test for delete
    - _Requirements: 15.1, 16.3, 17.1, 17.2, 24.2_

- [ ] 18. Audit log surfacing
  - [x] 18.1 Implement audit log writer
    - `app/features/audit/models.py`: `AuditLog` (id, actor_id NULL, action, target_kind, target_id NULL, payload_json, request_id, occurred_at) — append-only; ORM has no `update`/`delete` methods exposed
    - `AuditLogger` service injected into auth, otp, and admin services; writes within the same transaction as the action so log+action are atomic
    - _Requirements: 15.5, 21.1, 21.2_

  - [x] 18.2 Implement audit-log read route
    - `GET /v1/admin/audit-log` paginated; depends on `require_admin`
    - _Requirements: 21.1, 21.2_

  - [x] 18.3 Write router tests for audit log
    - Happy path + 401 + 403 (non-admin)
    - Verify writes produced by signup, login, logout, OTP issue/verify, password reset, every admin action
    - _Requirements: 15.5, 21.1, 21.2_

- [x] 19. Checkpoint - Backend slices green
  - Ensure all backend property, repository, service, and router tests pass; ask the user if questions arise.

- [ ] 20. PWA frontend foundation (lean)
  - [x] 20.1 Initialize React + Vite PWA project
    - Create `web/` workspace with React + TypeScript + Vite; install `vite-plugin-pwa` (Workbox under the hood)
    - Configure `manifest.webmanifest` (name, icons, start_url, display: standalone)
    - Apply Helvetica with documented fallback stack as global font
    - _Requirements: 20.1, 23.1_

  - [x] 20.2 Implement API client and auth state
    - Typed fetch wrapper that attaches `Authorization: Bearer <jwt>`, surfaces `X-Request-ID`, parses `ErrorResponse`
    - Auth state stored in IndexedDB store `auth_state` with `last_authenticated_at`
    - _Requirements: 3.1, 21.4_

  - [x] 20.3 Implement service worker with route-class strategies
    - Static assets: cache-first with versioned URLs; precache app shell
    - Content GETs (`/v1/modules`, `/v1/topics/*`, `/v1/subtopics/*/lesson`): stale-while-revalidate, populate IndexedDB
    - State GETs (`/v1/users/me`, `/v1/progress/snapshot`, `/v1/leaderboards/*`): network-only with cached fallback for `/v1/progress/snapshot` only
    - Mutations: network-only when online; offline → enqueue to `pending_events` IndexedDB store and return synthetic 202
    - _Requirements: 20.1, 20.2_

  - [x] 20.4 Implement IndexedDB stores
    - `cached_lessons`, `cached_subtopic_pools`, `pending_events`, `auth_state` per design schema
    - _Requirements: 20.2, 20.3_

  - [x] 20.5 Implement Background Sync flow
    - Register Background Sync; on sync event POST `/v1/progress:sync` with all `pending_events`; on success drop accepted from the store and `postMessage("sync_complete")`
    - _Requirements: 14.1, 20.3_

  - [x] 20.6 Implement offline auth-window check
    - Before serving offline content, verify `auth_state.last_authenticated_at` is within 24h; otherwise route to login prompt
    - _Requirements: 20.2_

  - [x] 20.7 Write integration tests for service worker offline behavior
    - Use Playwright with offline mode; verify cached-lesson reads and pending-event enqueue/drain end-to-end against the live API
    - _Requirements: 20.1, 20.2, 20.3_

- [ ] 21. PWA pages (lean — wired to API contracts)
  - [x] 21.1 Auth pages
    - Signup, Login, Forgot Password, OTP Verification — wired to `/v1/auth/*`; password rule hints in form errors; responsive 360px–1920px
    - _Requirements: 1.1–1.5, 2.2, 3.1, 4.1, 4.3, 23.2_

  - [x] 21.2 Module navigation and Lesson reader
    - Module → Topic → Subtopic → Lesson tree; lesson reader renders explanations / worked examples / takeaways / summary; "Mark complete" calls `POST /v1/subtopics/{id}/lesson:complete`
    - _Requirements: 5.1, 5.2, 6.2, 6.3_

  - [x] 21.3 Quiz player
    - Subtopic / Topic / Module quiz UI; PATCH per answer; submit shows per-question correct + explanation
    - _Requirements: 7.1, 7.4, 7.5, 8.2, 9.2_

  - [x] 21.4 Mock exam UI
    - Server-driven `remaining_seconds` shown; reports focus-loss; LINEAR_NO_REVISIT enforced in UI; results page renders score + per-module + weakness summary
    - _Requirements: 10.3, 10.5, 19.2, 19.4_

  - [x] 21.5 Leaderboard, Profile/XP, Admin dashboard
    - Leaderboard global tab (MVP); Profile shows XP / level / streak / achievements; Admin dashboard wires user list + analytics + content management + export/import
    - _Requirements: 12.1, 11.4, 11.6, 13.4, 15.2, 17.2, 17.3, 24.1_

  - [x] 21.6 Dark-mode toggle (Phase 2)
    - Toggle persisted per learner; meets WCAG AA contrast in both themes
    - _Requirements: 23.5, 23.6_

  - [x] 21.7 Keyboard navigation and accessible names
    - Visible focus indicator (≥ 3:1 contrast), `aria-label` or visible label on every interactive element
    - _Requirements: 23.3, 23.4_

  - [x] 21.8 Write component tests
    - One happy-path test per page using the mocked API client
    - _Requirements: 23.2, 23.3, 23.4_

- [ ] 22. Wiring and verification
  - [x] 22.1 Wire `app/main.py`
    - Create FastAPI app, register middlewares in correct order (logging → error_handler → auth), mount every feature router under `/v1/` via `app.include_router(..., prefix="/v1")`
    - Add `GET /health` (unauthenticated) returning `{"status": "ok"}`
    - Run startup pragmas via SQLAlchemy `event.listens_for(Engine, "connect")` so every connection has WAL + FK + temp_store + mmap applied
    - Lifespan starts and stops APScheduler
    - _Requirements: api-standard.md health, 14.1, 22.3_

  - [x] 22.2 Implement seed-data loader (fixtures only — content authorship is out of scope per Open Question 6)
    - `scripts/seed.py`: load minimal fixtures sufficient to make the system runnable end-to-end — 1 PROFESSIONAL module + 1 SUB_PROFESSIONAL module, each with 2 topics × 2 subtopics × 1 lesson, each subtopic with 25 quality-gated questions; one admin user; achievement seed rows; mock-exam-config rows for both categories at `total_questions=50` for MVP
    - _Requirements: 1.1, 5.1, 5.2, 6.3, 7.1, 10.1, 10.2, 13.4_

  - [x] 22.3 End-to-end smoke run via automated test
    - Single pytest under `tests/smoke/test_end_to_end.py` that spins up the app with TestClient, runs the seed loader against an in-memory DB, then exercises: signup → OTP verify (read code from offline-OTP file) → login → module list → lesson read → lesson complete → subtopic quiz start → answer all → submit → topic quiz prereq blocked then unlocked → mock exam start → answer → submit → XP / level / leaderboard / achievements assertions
    - This is an automated test, not a manual UAT (per workflow's "no manual testing tasks" rule)
    - _Requirements: 1.1, 2.2, 3.1, 5.1, 6.2, 7.1, 8.1, 10.1, 11.1, 12.1, 13.1, 14.2_

  - [x] 22.4 Final checkpoint - Ensure all tests pass
    - Run `pytest`, `mypy app/`, `ruff check app/`, `bandit -r app/`; resolve all HIGH bandit findings; ask the user if any failures arise.

- [ ] 23. Content seeding infrastructure and seed data generation (Req 25)
  - [ ] 23.1 Implement seed question bank Pydantic schema and validation pipeline
    - `app/features/admin/schemas.py`: add `SeedQuestionItem` and `SeedQuestionBank` models per design
    - `app/features/admin/algorithms/seed_validator.py`: 6-stage validation pipeline (schema → quality gate → duplicate ID → category match → pool depth ≥500 → difficulty distribution 40/40/20 ±5%)
    - Update `POST /v1/admin/questions:bulk-import` to accept seed-format JSON and run the full pipeline
    - _Requirements: 25.1, 25.3, 25.5, 25.6, 25.7, 25.8, 25.9_

  - [ ] 23.2 Implement lesson Markdown parser
    - `app/features/admin/algorithms/lesson_parser.py`: state-machine parser that maps H2/H3 Markdown headings to `LessonContent` JSON fields (explanations, worked_examples, key_takeaways, summary)
    - Update lesson create/update endpoints to accept `Content-Type: text/markdown` and parse before validation
    - _Requirements: 25.2, 25.10_

  - [ ] 23.3 Implement seed script
    - `scripts/seed_content.py`: reads `data/seed/` directory tree, resolves slug paths to DB IDs, calls bulk-import for questions and lesson create for lessons
    - Supports HTTP mode (`--base-url`) and in-process mode (`--in-process`)
    - _Requirements: 25.1, 25.2_

  - [ ] 23.4 Write property tests for content seeding
    - **Property 38: Lesson content validation completeness** — accepts iff all required sections present with non-empty content
    - **Property 39: Question bank atomic rejection** — any invalid question causes zero inserts; error report lists all failures
    - **Property 40: Category match enforcement** — question category must match parent module category
    - **Property 41: Pool depth threshold** — import accepted iff ≥500 valid questions per subtopic
    - **Property 42: Difficulty distribution tolerance** — Easy ∈ [35%,45%], Medium ∈ [35%,45%], Hard ∈ [15%,25%]
    - **Validates: Requirements 25.2, 25.3, 25.5, 25.6, 25.7, 25.9, 25.10**

  - [ ] 23.5 Write router and integration tests for content seeding
    - Happy path: valid 500-question bank → 200; valid lesson markdown → 201
    - Failure paths: invalid question → 422 with full report; pool depth < 500 → 422; distribution out of tolerance → 422; category mismatch → 422; missing markdown section → 422
    - Seed script integration test against test DB
    - _Requirements: 25.1–25.10_

  - [ ] 23.6 Generate seed data: Subject-Verb Agreement lesson and question bank
    - Create `data/seed/lessons/verbal-ability/grammar/subject-verb-agreement/lesson.md` — detailed bilingual lesson (English + Filipino) covering all SVA rules, examples, strategies, and practice sets
    - Create `data/seed/questions/verbal-ability/grammar/subject-verb-agreement/questions.json` — 500 questions (250 English / 250 Filipino, 250 Professional / 250 Sub-Professional, 40% Easy / 40% Medium / 20% Hard)
    - Validate generated files pass the seed validation pipeline
    - _Requirements: 25.1, 25.2, 25.3, 25.4, 25.5, 25.6, 25.7, 25.8_

## Notes

- Sub-tasks marked `*` are Phase 2 and must be skipped during MVP execution per the workflow's optional-task rule.
- Every feature slice produces three test files (`test_repository.py`, `test_service.py`, `test_router.py`) per `testing-standards.md`. Property tests live alongside in `test_algorithms_<name>.py` or as additional test cases in the relevant layer file.
- Every property-test sub-task explicitly references the design's Property number(s) and the requirement clause(s) it validates, per the workflow's traceability rule.
- Performance budgets (Req 22.1–22.3), visual a11y (Req 23.2–23.5), PWA Lighthouse score (Req 20.1), and SMTP integration are explicitly out of unit-test scope and live in separate non-functional / scan harnesses described in design's Testing Strategy section.
- Content authorship (full question banks for all modules) is out of scope per requirements Open Question 6; the seed loader produces only enough data to make the system runnable.
