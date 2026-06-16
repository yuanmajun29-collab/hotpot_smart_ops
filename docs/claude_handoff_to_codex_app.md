# Claude handoff to Codex

**Topic**: hotpot_smart_ops intelligent operations software — organization review, fusion, and implementation handoff
**Source**: Claude.app conversation `Hotpot smart ops项目内容查看`
**Receiver**: codex.app
**Date**: 2026-06-16
**Status**: synced into PR branch

> This handoff belongs to the hotpot_smart_ops intelligent operations workflow. It is not part of the separate security installation project baseline.

## 1. Background

Claude.app reviewed the hotpot_smart_ops product and architecture design against the target organization model: executive overview, region/store execution, shift-lead supervision, sales growth, receiving, SOP, safety, and traceability. The conclusion was that the project covers roughly 70% of the desired organization model, with gaps concentrated around execution ownership, task follow-up, review responsibility, sales growth, and traceability.

The resulting correction set is:

| Correction | Scope |
| --- | --- |
| A | F-TASK task supervision engine |
| B | F-SALES rule-based sales growth |
| C | F-TRACE traceability chain |
| D | Generic restaurant integration slots |
| E | Role completion for shift_lead, marketing_ops, finance_audit |

## 2. Claude Outputs

Claude's final handoff listed these fused V1.2 document outputs:

| File | Purpose |
| --- | --- |
| `docs/org_hierarchy_coverage_assessment.md` | Organization coverage assessment and correction list |
| `docs/task_supervision_engine_design.md` | F-TASK detailed design |
| `docs/architecture_decisions.md` | ADR-010/011/012 |
| `docs/product_hierarchy_national_chain.md` | L4 shift layer, roles, and F-TASK/F-SALES/F-TRACE families |
| `docs/architecture_hierarchy_phase_plan.md` | tasks/task_events and `/v1/tasks`/`/v1/trace` planning |
| `docs/product_design.md` | Phase 2 sales-growth adjustment |

Claude also exported implementation patch `0002-feat-tasks-migration-script-3-new-roles-DEV-520-528-.patch`, which has been applied in this PR branch.

## 3. Synced Decisions

| # | Decision |
| --- | --- |
| 1 | F-TASK main statuses are `pending`, `in_progress`, `submitted`, `closed`, `cancelled`. |
| 2 | `draft` is out of MVP scope; `accept` is recorded as a `task_event`, not a main status. |
| 3 | `reopen` returns to `pending`, requires a reason, and is limited to store manager, regional supervisor, or HQ PMO. |
| 4 | `verify` must not allow the original submitter to self-close. |
| 5 | `reassign` must explicitly set `sla_policy` as `reset_from_reassign` or `keep_original_due_at`; default is `keep_original_due_at`. |
| 6 | `sop_assignments` migration uses legacy `assignment_id` as the idempotent `source_id`. |
| 7 | Legacy `/v1/sop/assign` remains as a compatibility path while F-TASK is introduced. |
| 8 | Franchise owner remains a P3 role; current implementation is the existing 7 roles plus 3 added roles. |
| 9 | `finance_audit` is read-only; `marketing_ops` can only write F-SALES configuration. |
| 10 | `task_events.event_type` uses an explicit action enum such as `create`, `start`, `submit`, `verify`, `reject`, `reopen`, `cancel`, `accept`, `reassign`, `escalate`, `comment`. |

## 4. Applied Implementation

The Claude implementation patch adds:

| File | Change |
| --- | --- |
| `cloud/event_hub/scripts/migrate_sop_assign_to_tasks.py` | Idempotent `sop_assignments` to `tasks/task_events` migration script |
| `cloud/event_hub/auth.py` | Demo users and scope logic for 班组长, 营销运营, 财务审计 |
| `dashboard/assets/rbac.json` | 10-role menu/action matrix with `tasks`, `sales`, and `trace` menus |

The existing repository version of `docs/task_supervision_engine_design.md` intentionally keeps the corrected "5 main statuses" wording in the MVP checklist; Claude's cached artifact still had one stale "7 main statuses" phrase there.

## 5. Next Work

Recommended next implementation step is DEV-521:

- Add `cloud/event_hub/task_store.py`.
- Add `/v1/tasks/*` routes for create, assign, accept, start, submit, verify, reject, reassign, cancel, reopen, list, detail, and timeline.
- Keep `/v1/sop/assign` compatibility.
- Gate rollout behind a feature flag.
- Do not make F-TASK an IMP-402 Go-Live prerequisite.
- Do not take resources from BL-01 through BL-08.

## 6. Security Note

Claude's handoff mentioned that a GitHub PAT had appeared in earlier conversation context. No token is included here. Any exposed token should be revoked in GitHub.
