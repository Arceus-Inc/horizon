# Offline demo — AI note-taker for working professionals

_generated 2026-07-07T18:33:37+00:00_

## Decomposition — Decision → Goals (LLM)

**Decision:** Build an AI note-taker for working professionals  
**Goals produced:** 3

| # | score | goal | metric | target |
|---|------|------|--------|--------|
| 1 | 0.90 | Build the note-capture REST API | endpoints live + integration tests green | 3 endpoints, 100% of contract tests passing |
| 2 | 0.70 | Design the mobile capture UI | usability pass rate in review | >=2 screens, >=80% reviewers rate 'usable' |
| 3 | 0.50 | Add full-text search over saved notes | top-5 retrieval success on a test set | >=90% success, p95 < 500ms on 1k notes |

## Intake — Goals → chorus tasks (Submitter + Prioritiser)

| goal | task | priority | assignee |
|------|------|----------|----------|
| Build the note-capture REST API | `task_1b18f81f3b0d` | **high** | — |
| Design the mobile capture UI | `task_18ee7c7d9906` | **medium** | — |
| Add full-text search over saved notes | `task_ce3be16b96be` | **medium** | — |

## Feedback — landed outcomes → health → re-priority (OutcomeListener)

**Verdicts folded:** 3

| goal | verdict | health | score | priority |
|------|---------|--------|-------|----------|
| Build the note-capture REST API | PASS | unknown → on_track | 0.90 → 0.45 | high → medium |
| Design the mobile capture UI | FAIL | unknown → blocked | 0.70 → 0.95 | medium → high |
| Add full-text search over saved notes | PASS | unknown → on_track | 0.50 → 0.25 | medium → low |

## Current direction (read model)

### Build an AI note-taker for working professionals  
`dec_offline` · status=active

| score | priority | health | goal | task |
|-------|----------|--------|------|------|
| 0.95 | high | blocked | Design the mobile capture UI | `task_18ee7c7d9906` |
| 0.45 | medium | on_track | Build the note-capture REST API | `task_1b18f81f3b0d` |
| 0.25 | low | on_track | Add full-text search over saved notes | `task_ce3be16b96be` |