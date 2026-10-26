# Changelog

## 0.13.8 - 2026-10-27 - Terra 6.1 and risk-based reasoning effort

- Upgrade Codex `balanced` to GPT-6.1 Terra; keep Luna routing and Worker retry behavior unchanged.
- Use `high` for default integration audit and diagnosis on Codex and Claude Code. Reserve `xhigh` for high/critical risk and the existing final Worker fallback.
- Test role and risk selection on both hosts. Artifact protocol remains `1.8.0`; live model availability and native-Agent acceptance still require host verification.

## 0.13.7 - 2026-10-26 - Historical suite comparison and regression deltas

- Compare previous and current suite reports by exact test ID, surfacing new failures, recoveries, added failing tests and measured runtime increases. Explicitly disclose unequal selections and never infer full coverage from a partial run.
- Keep the combined efficiency summary under 4 KiB while retaining hosted dispatch metrics and unmeasured token usage. No model routing decisions or lifecycle authority changes.
- Cover invalid evidence, changed selection, bounded reporting and read-only CLI behavior with offline tests. Artifact protocol remains `1.8.0`.

## 0.13.6 - 2026-10-26 - Bounded routing and regression efficiency analysis

- Add a read-only, 4 KiB-bounded efficiency analyzer for existing hosted dispatch JSONL and suite JSON, grouping observed role/model/effort wall time, outcomes, retries and optional caller-observed wait/packet bytes. Never infer billed tokens, model quality, or WORK completion.
- Summarize the three slowest tests and partial/full test evidence without exposing raw dispatch messages, task names, session tokens or giant suite logs. Reject malformed, oversized and symlinked evidence.
- Add focused self-contained tests and explicit change-impact mapping. Preserve full release-gate authority and artifact protocol `1.8.0`.

## 0.13.5 - 2026-10-26 - Advisory change-aware focused regression selection

- Add `run_suite.py --changed-from <ref>` to select exact impacted test modules using committed, staged, unstaged and untracked paths; unclassified plugin changes expand to all focused tests instead of silently passing.
- Preserve compact output, explicit partial evidence and full release-gate authority; keep `--rerun-from` and `--summary-from` independent from change selection.
- Cover Git path collection, mapping drift, fallback and CLI partial-report semantics without running the complete regression gate. Artifact protocol remains `1.8.0`.

## 0.13.4 - 2026-10-26 - Structured execution receipts and compact resume briefs

- Extend existing optional execution checkpoints with bounded decisions, assumptions, constraints, source path pointers and next steps. All values remain caller-reported, never completion or policy approval evidence.
- Add read-only `execution resume-brief` with a hard 4KB JSON output bound, current lifecycle/WORK/Git pointers and explicit pending-child and owner checks. Preserve full `execution handoff` for deeper inspection.
- Add offline receipt/brief regressions. Reuse the existing SQLite journal and avoid extra model calls or new lifecycle artifacts; protocol stays `1.8.0`.

## 0.13.3 - 2026-10-23 - Codex crash recovery and compact regression feedback

- Add subscription-free Codex-only subprocess-crash regression covering persisted WORK anchors, incomplete command journal, guarded restart, termination attestation and retry continuity.
- Make the full/focused suite console output compact by default; preserve detailed unittest traces on `--verbose` and atomic machine-readable test reports.
- Provide bounded prior-suite summary and exact-ID nonpassing reruns without treating a partial rerun as release evidence. Protocol remains `1.8.0`.

## 0.13.2 - 2026-10-23 - Read-only hosted observations and cross-host CLI parity

- Open existing hosted coordinators strictly read-only; absent domains are inspected without creating runtime directories or SQLite databases. Reject malformed coordinator paths instead of treating them as idle.
- Add subscription-free subprocess acceptance tests across Codex and Claude native wrappers: idle status, ownership transfer in both directions, stale owner denial and release, plus read-only lease and expiry checks.
- Preserve existing child fencing, WORK authority, and host-specific routing. Live Claude/Codex native Agent E2E and full release gate remain deferred; artifact protocol stays `1.8.0`.

## 0.13.1 - 2026-10-23 - Claude dynamic-model agents and offline host parity

- Consolidate 16 Claude model/effort/read-only agents into six effort/read-only presets. Supply the selected `haiku|sonnet|opus` model explicitly on each native Agent invocation; never rely on the fallback inherited model.
- Keep foreground/one-child-at-a-time behavior explicit, reject conflicting host-wide model and fork-subagent overrides, and document actual-model verification limitations.
- Add subscription-free, host-neutral integration scenarios covering Codex/Claude routing, idle handoff, inflight fencing, retry and WORK authority continuity. Defer live native-agent E2E and the complete release gate.
- No change to STATE/WORK authority, artifact protocol `1.8.0`, or Codex model registry.

## 0.13.0 - 2026-10-23 - Claude Code host-native Goal integration

- Add an explicit Claude Code host wrapper using the existing hosted Goal guard, lease and operational handoff without starting nested CLI sessions.
- Separate Claude model policy and Agent definitions from Codex routes. Resolve Scout to Haiku, Workers to Sonnet, and high-reasoning review roles to Opus with verified per-effort native Agent presets.
- Fail closed on unsupported model/effort combinations or a higher-priority forced subagent model. Preserve WORK/STATE authority, no-progress counters, child fencing and manual cross-host ownership transfer.
- Add Claude routing/preset tests and operator instructions. Live Claude native Agent activation and bidirectional quota-interruption acceptance remain external verification work; artifact protocol stays 1.8.0.

## 0.12.6 - 2026-10-23 - Durable primary dispatch anchors and recovery visibility

- Persist a bounded action and selected-WORK snapshot at each hosted primary reservation, including the original WORK status, start SHA and dispatch HEAD; no source bodies, transcripts, or extra lifecycle authority.
- Expose the original primary action, pending reservation and most recently acknowledged or administrator-recovered primary via the read-only cross-host handoff projection. Legacy reservations remain readable; child completion is never treated as WORK completion.
- Add focused tests for interrupted primary work, cross-host resume, duplicate/stale acknowledgements, untouched WORK, and no disclosure of private session or step IDs. Keep protocol `1.8.0` and all existing execution guards.

## 0.12.5 - 2026-10-23 - Operator-attested cross-host session handoff

- Add host-labeled hosted sessions, read-only owner markers and explicit operator-attested idle handoff. Fenced reservations and other live owners cannot be taken over; stale observations fail closed.
- Rotate the hosted session token atomically while preserving WORK/STATE, hosted retry and resource counters. Record source/target host transitions and operator evidence in the private coordinator.
- Surface host ownership in execution handoff projections and teach the Codex Goal wrapper to inspect it before claiming a session. Claude native routing remains a separate integration.
- Add bidirectional, pending-child, concurrency and legacy migration regressions. Artifact protocol remains `1.8.0`, with no lifecycle migration.

## 0.12.4 - 2026-10-23 - Host-independent execution progress and handoff observations

- Add a bounded SQLite journal for start/finish of lifecycle-mutating DevFlow CLI operations, and explicitly distinguish incomplete observations from successful transitions.
- Introduce `devflow execution handoff` and optional `execution checkpoint` for host-independent resumption hints, action correlation and Git worktree navigation without duplicating STATE or WORK.
- Keep operational checkpoints advisory: no new lifecycle states, required artifacts, lease transfer, or protocol migration. Hosted child termination and ownership fencing remain unchanged.
- Add targeted synthetic regression coverage; native Codex/Claude Code handoffs still require end-to-end acceptance.

## 0.12.3 - 2026-10-21 - Hosted Scout evidence accuracy and critical cache reuse

- Keep shell command text (including `./gradlew`) out of the evidence-file snapshot; continue hashing explicit structured log/output paths. Treat requirement arithmetic, domain slash pairs and Java method names as narrative instead of filesystem citations. Bind the primary Evidence map source anchors and explicitly rooted references anywhere in a Scout capsule, while still refusing any out-of-scope path or changed source digest.
- Make critical verifier retries reuse an existing host-verified capsule instead of always respawning Scout. Unconditional `scout_before` and fresh evidence checks remain unchanged.
- Return bounded causes when Scout binding is stale (creation/current scope confirmation, moved digest or HEAD, and out-of-scope citations) without repairing provenance.
- Add regressions based on observed hosted Goal Scout text. Keep artifact protocol 1.8.0 and the independent audit, remediation and native usage-measurement boundaries unchanged; this release does not claim measured token savings.

## 0.12.2 - 2026-10-20 - Release-source provenance and protocol mirror repair

- Synchronize the STATE scaffold with the canonical artifact protocol version and reject stale templates before running the full release suite.
- Derive current-version regression assertions from `version.json` instead of fixed release numbers; preserve historical compatibility fixtures.
- Include root marketplace adapters and active root documentation in release source digests and clean-tree checks, without treating local patch files as release artifacts.
- Align README's decision-artifact description with product, technical, and provisional-policy records.
- Retain artifact protocol `1.8.0` with no artifact migration. Native hosted Goal/installed ELI5 acceptance still requires separate evidence.

## 0.12.1 - 2026-10-20 - Documentation contract and version gate repair

- Correct source-approval handoff guidance for captured requirements and align decision templates with technical and provisional-policy records.
- Clarify lifecycle mutation rollback versus persisted Newman execution evidence. Remove duplicated state-transition rules and internal implementation phase names from active documentation.
- Remove stale `0.11.1` assertions from documentation-history tests, require that regression family in the release suite, and fail fast on unsynchronized version metadata.
- Make `version.json` the sole current plugin and artifact protocol version source, with synchronized Claude/Codex manifests and a checked runtime protocol constant. README files link to the source instead of carrying release numbers.
- Keep artifact protocol `1.8.0` and existing compatibility behavior. Native hosted Goal end-to-end and installed ELI5 invocation acceptance remain pending independent evidence.

## 0.12.0 - 2026-10-20 - Requirements provenance and evidence-based reporting

- Capture immutable original requirements and separate supplemental context under `sources/v1/` with content hashes; supplemental context does not grant product-policy approval.
- Add source-to-PRD/PLAN/WORK/acceptance traceability, reciprocal-link validation and explicit uncovered-source diagnostics. Existing domains without opt-in traceability remain readable.
- Separate developer technical decisions from reversible, low-risk provisional product-policy assumptions. Product approval/rejection and corrective WORK independently gate final integration.
- Derive independent per-requirement implementation, original-difference, decision and verification states; missing or stale evidence remains unknown or stale, never a fabricated pass.
- Generate a human checklist (`REQUIREMENTS_STATUS.md`) and complete JSON snapshot (`REQUIREMENTS_STATUS.json`) from one read-only evidence reducer.
- Bind traced requirement evidence into the whole-domain ELI5 scope, verify visible requirement dispositions and maintain finalization/integration blockers for unsupported completion. The existing Newman and installed ELI5 evidence requirements remain in force.
- Release both Claude Code and Codex adapters at plugin `0.12.0` while retaining artifact protocol `1.8.0`; new traceability is additive and legacy artifacts require no migration. Native hosted Goal and real installed ELI5 acceptance remain pending until independently evidenced.

- Add release-gated documentation consistency checks and a reproducible, archived-baseline comparison of Plan/Run/Audit/Finalize/Scout navigation CLI packet bytes. Long exact policy-copy candidates remain advisory. No native Goal, model-token, real Newman or installed ELI5 result is claimed.
- Apply one legacy-compatibility rule everywhere. `delivery check`, `validate` and `delivery newman` share `stale_hashes`, so a 0.10.2 branch record without the optional `postman_structure_sha256` reaches the Newman run preconditions instead of being refused as stale. A recorded digest that disagrees with the collection and a missing required hash are still refused, and compatibility validation still writes no STATE or WORK bytes.
- Reuse one WORK snapshot per hosted Scout invocation. `scout-validate` hands its already verified evidence index, scope and digest to the host-side capsule re-check, `step-start --kind scout` builds them once, and `evidence_scope` reads the WORK index it already loaded instead of querying the selected item again. `scout-validate` stays read-only and never re-binds a capsule.
- Split whole-work integrity from rendered input. Every WORK row and every branch record stay inside `scope_sha256`, while a page now prints pinned sources, branches, runs, diagnoses and metadata. Manifest pages after the first repeat their slice, the digest and the item count instead of the whole WORK set, the PRD, the PLAN and the appended protocol. Whole-work scope, the original `work_file` lookup path and the `scope_sha256` meaning are unchanged, and the ELI5, Newman and integration gates are untouched.
- Correct the role-ownership matrix. `delivery.schema.yaml` and `finalization.schema.yaml` never existed, so those rows now name their owning protocols, and `core/schemas/state.schema.yaml` is linked to `core/protocol/authority.md` for the STATE records it defines. A regression test fails on any ownership reference that names a file that does not exist. No new schema file is added.
- Measured separately, repeated five times per size, same repository and same plugin path in both revisions, with the raw results under the Git-excluded `docs/measurement/` records. Scout capsule validation of a bound capsule: WORK index projections 9 to 1 per invocation, and wall clock 511 to 253 ms at 8 WORK, 892 to 328 ms at 36, 2,407 to 519 ms at 120 and 4,773 to 830 ms at 250. Whole `render finalize` input summed over every manifest page: 96,350 to 72,725 bytes at 60 WORK, 241,695 to 98,139 bytes at 120 and 857,383 to 159,743 bytes at 250, with summed page wall clock 424 to 381 ms, 1,103 to 1,034 ms and 4,463 to 3,875 ms. Evidence digests, capsule verdicts and `scope_sha256` values are identical across the compared revisions.
- These are CLI component and input-volume measurements on local fixtures. Native hosted Goal end-to-end wall clock, native child spawn count and token usage remain unmeasured; no end-to-end improvement and no token saving is claimed. These figures describe pre-0.12.0 refactorings on plugin `0.11.1` and Protocol `1.8.0`; they do not establish native execution gains from this release.
- Retire the original `core/references/vibecoder.md` design-review snapshot (preserved by Git history). Keep the current root README focused on installation/acceptance, and keep detailed commands in the plugin README.

## 0.11.1 - 2026-10-16 - Review defect corrections

- Fix legacy delivery validation when a branch predates the optional `postman_structure_sha256` field. Existing recorded hashes still undergo integrity checks; no STATE migration is required.
- Bind hosted Scout capsules to a creation snapshot of the selected WORK and its related files, cited references, verification evidence, repository instructions, routing settings and Scout instructions. Scoped file bytes and Git index entries detect relevant staged and unstaged changes without reacting to unrelated staged files. Only a completed Scout step's matching `<step_id>.md` output can bind once; a reference outside the snapshot is unconfirmed and falls back. Validation is read-only and host dispatch rechecks the binding. The capsule does not prove Scout opened its cited sources.
- Bound `render evidence` text and row counts, fingerprint the content of cited files for capsule freshness, and key hosted route-engine reuse by the complete loaded routing policy.
- Clarify that same-path DTO, authentication and assertion changes require executor and auditor review; a stable endpoint list or structure digest does not prove the HTTP contract is unchanged.
- Keep protocol `1.8.0`: the changes preserve existing lifecycle states and artifact schemas, including older branch records. Full acceptance remains **pending** until a native hosted Goal end-to-end run and an actual invocation of the installed ELI5 skill are recorded. Local tests and synthetic subprocess fixtures do not satisfy that gate.

## 0.11.0 - 2026-10-15 - Hosted Goal lifecycle efficiency

- Ship hosted Goal runtime refactorings for roadmap R00-R18 on protocol `1.8.0` and record the local R19 release gates below. Native R19 acceptance remains pending. Read-only hosted children start from a bounded evidence index, hosted renders are pinned to the dispatch fingerprint and HEAD, one invocation reuses its WORK snapshot plus its SHA-pinned Git inspections and Newman digests, the finalizer receives a paged WORK manifest with a dedicated role contract, and observation commands no longer extend the lease.
- Additive surface only: `render evidence`, `render finalize --manifest-page`, `render --expected-head/--expected-fingerprint/--check-only`, `dispatch --scout-cached`, a `stale` scout-capsule verdict, the optional branch field `postman_structure_sha256`, and `core/protocol/role-instructions.md`.
- Measured on one machine with the committed benchmark (projection `--reps 9`, packets `--reps 3`), from `b3be7af` against this release: one `validate` over 3 delivered WORK with 4 anchors drops from 27 to 14 Git calls; Scout and Diagnostician child input drops from 36,195 to 2,334 bytes; `render finalize` drops 21 percent at 60 WORK, 37 percent at 120, 49 percent at 250 and 53 percent for 60 delivered WORK; status and render p50 at 8/36/120/250 WORK are unchanged within noise; the audit and run packets grow about 3 percent from the pinned-render and audit-scope text.
- Baseline correction: `b3be7af` is itself later than the R05 implementation commit `36d0fc9`, so these figures cover R06 through R18 only. They are not evidence for R02-R05, and this release does not claim measured improvement for those items. Each row names its own cost class: a CLI component such as one `validate`, a child input byte count, or one rendered `render finalize` packet. None of them is a native hosted Goal end-to-end measurement.
- Historical release record for commit `23124f166125aa43101f0d309c51c804cec2e194`: `release_gate.py --mode merge` and `--mode release` were recorded as passing with 547 of 547 tests, 0 failed, 0 skipped and the real Newman profile executed. These figures describe that historical HEAD and are not evidence for 0.11.1 or current R19 acceptance.
- Not measured at that release: native hosted Goal end-to-end wall clock, native child token usage, Scout capsule spawn cost and cold-cache Newman re-hashing. Agent token savings were not claimed. Native hosted Goal end-to-end and installed ELI5 invocation were not performed.
- Synchronize the Claude marketplace, both plugin manifests and current documentation to `0.11.0`. Lifecycle statuses, audit gates, evidence provenance and every STATE/WORK artifact contract are unchanged, so no protocol migration is required.

### R18 telemetry cleanup and hosted config boundaries

- Prune settled telemetry inflight files when a new telemetry dispatch starts, preserving only the file whose `step_id` is the live reserved step. An interrupted supervisor no longer accumulates files, and another session's live record is untouched.
- State next to the settings that `budget.total_tokens` and `concurrency.read_only` apply to standalone Autopilot only: hosted native token usage is unmeasured and hosted children are dispatched sequentially. Read-only roles keep read-only permissions; no hosted read-only parallelism is introduced.
- Retain Protocol `1.8.0`.

### R16 in-process routing reuse

- Build the hosted model registry, capability registry and route engine once per CLI process and share them across the primary, Scout and candidate routes of one dispatch. Model selection, effort, candidate order and capability fallback are unchanged.
- The cache key is the loaded model configuration, so a changed policy still builds its own registry. Policy YAML was already read once at command startup and is never re-read here.
- Retain Protocol `1.8.0`.

### R15 lease renewal scope

- Separate read-only ownership verification from lease renewal. `dispatch`, `guard-status`, `scout-validate` and `session-status` now open a deferred SQLite transaction, verify the current owner and the pending-child fence, and leave `expires_at` untouched.
- Only `bootstrap`, `bootstrap-finalize`, `step-start`, `step-finish`, `session-start`, `session-checkpoint` and `session-recover` extend the lease, so polling cannot keep a dead owner alive and a long-running child is still covered by its lifecycle edges.
- Retain TTL, ownership, inflight and recovery semantics unchanged. Retain Protocol `1.8.0`.

### R14 incremental PR/Postman refresh

- Record a Postman request-structure digest with each delivered branch and refuse a later WORK on that branch that rewrites the structure while `api_endpoints` is unchanged. Source unrelated to the HTTP surface no longer regenerates unrelated requests.
- Refresh `head_sha`, `base_sha`, branch range, PR body, test results, content hashes and provenance on every WORK as before, and keep declared-endpoint coverage as the change signal for the requests themselves.
- Add the optional `postman_structure_sha256` branch field. Legacy branch records without it stay valid and are compared only once recorded. Retain Protocol `1.8.0`.

### R13 audit-scope delivery checks

- A `work`-scope audit verifies that item's own source, comment anchors and branch delivery evidence instead of repeating the domain-wide `delivery check`. `audit apply` already runs the full domain-wide delivery validation and rejects the transition.
- `phase` and `integration` audits keep the full `delivery check`, and integration closure keeps `--final` for extant branch tips. Damaged evidence on any item still fails an applied audit.
- Retain Protocol `1.8.0`: audit obligations, finding taxonomy and gate authority are unchanged; only the redundant instruction is removed.

### R12 role instruction single source

- Add `core/protocol/role-instructions.md` as the ownership matrix: every rule class names one authoritative protocol or schema, and skills and render prompts keep only role steps, boundaries, receipts and pointers.
- Remove the ELI5/Newman planning obligations duplicated between `core/prompts/plan.md` and `skills/plan/SKILL.md`, and the whole-work review checklist duplicated between `core/prompts/audit.md` and `skills/audit/SKILL.md`. Role input bytes drop and each remaining consumer points at its owner.
- Preserve every obligation: the finalization protocol still owns the evidence bar, and `skills/run/SKILL.md` keeps its Finalize support. Retain Protocol `1.8.0`.

### R11 finalizer manifest and role contract

- Replace the whole-work inline WORK dump with a normalized manifest of `id`, `status`, `kind`, `risk`, `phase`, `commit`, `review`, `changed_files`, recorded verification and the exact `work_file`, paged 60 rows at a time through `--manifest-page`.
- Add `core/prompts/finalize-role.md` as the finalizer's own contract, carrying the run skill's finalize rules and the Newman-before-ELI5 order. The run skill keeps its Finalize support, and both still render the same `finalize` packet and `finalization` protocol.
- Preserve whole-work scope: the finalization scope hash, ELI5 metadata, all WORK dispositions and all branch evidence are unchanged. Protocol remains `1.8.0`.

### R10 evidence-first diagnostician input

- Route the read-only Diagnostician child to the bounded evidence index, now carrying recorded verification output, and name the authoritative run packet as an on-demand fallback.
- Keep `attempt == diagnose_at` routing and the read-only completion contract unchanged. Diagnosis still reads repository sources and command output directly. Protocol remains `1.8.0`.

### R09 bounded scout input and capsule freshness

- Add `render evidence`, a bounded read-only navigation projection of the action, its verification targets, referenced files and failure evidence. Scout children receive it instead of the full action packet and open the cited originals on demand.
- Bind a hosted scout capsule to an evidence digest in addition to the action fingerprint. `scout-validate` records the digest on first success and reports `stale` after the source, verification target, failure evidence or HEAD moves.
- Define `scout_on_retry` as "no current capsule" and let `dispatch --scout-cached` reuse one. Invalid, stale, same-model and oversized capsules still fall back to the authoritative packet. Protocol remains `1.8.0`.

### R08 finalization projection and shared digests

- Stop a state projection at the first definitive finalization error and keep the existing `finalize` action and reason. An error-free projection still needs the complete evidence check, and explicit finalization checks, `delivery finalize` and integration validation keep collecting every error.
- Share Newman raw and server log digests only inside one invocation, re-checking resolved path, size and change times, failing a file that changes while it is read, never caching failures and discarding the scope on return or error. Later invocations re-read content and detect byte changes.
- Retain Protocol `1.8.0`: statuses, gate meaning and evidence provenance are unchanged.

### R07 shared Git inspection in validation

- Share `rev-parse`, `merge-base`, `diff` and `show` results across one validation invocation when every pinned ref is a full commit SHA. Mutable refs, artifact contents and external files always read fresh, and no inspection survives the invocation.
- Read one source blob per path so several anchors parse the same file once. Different roots, heads and starts never share results. Protocol remains `1.8.0`: verdict rules and evidence provenance are unchanged.

### R06 pinned hosted child render

- Pin every hosted child render with the dispatch action fingerprint and projected HEAD. Render rejects a moved fingerprint or HEAD with exit `2`, no packet and no STATE write, and `--check-only` runs the same guards while emitting nothing.
- Replace the child initial full status with the pinned render, or with pinned `--check-only` before a scout capsule. Mutating children keep their post-change status receipt and read-only roles keep `--no-refresh`. Manual render without pins is unchanged.
- Retain Protocol `1.8.0`: CLI options are additive, existing lifecycle gates and audit/approval authority are unchanged, and a child blocker returns to its parent instead of selecting another action.

### R05 invocation WORK snapshots

- Reuse one WORK document/index snapshot across each status, render or state projection, and compute render's current action once. Audit output readers reuse the same documents, including empty files; custom WORK paths keep their existing fallback.
- End the snapshot at invocation scope, including exceptions. Read fresh WORK and HEAD on later calls and rebuild prospective override indexes without contaminating the base snapshot.
- Retain Protocol `1.8.0`: lifecycle decisions, mutation checks, STATE/WORK formats and cross-process freshness remain unchanged. Benchmark counters distinguish index requests from actual builds and WORK YAML reads.

### R03 resource checkpoints

- Add an explicit hosted session checkpoint after acknowledged action progress and child completion. Renew ownership and reset only the resource step segment atomically; preserve retry and cycle counters across checkpoints, session replacement, expiry and recovery.
- Keep the default 100-step segment and policy overrides. Reject pending children, invalid ownership, exhausted semantic guards and a latest capability blocker. Legacy progress permits one migration checkpoint only with positive persisted action-transition evidence.
- Retain Protocol `1.8.0`: optional operational progress fields remain backward-readable, without STATE/WORK changes or automatic child dispatch. Native child termination remains a supervisor-observed fact.

### R04 read-only projections

- Add opt-in no-refresh status and render commands that derive current HEAD and actions without changing STATE bytes or mtime. Scout and Diagnostician use these commands, including conditional authoritative-packet fallback.
- Preserve default refresh and live render mismatch checks against current WORK. Protocol remains `1.8.0`; CLI options are additive and no lifecycle fields or permissions change.

### R02 session fencing

- Preserve expired and orphan inflight reservations as fences for hosted and standalone execution. Check idle progress and release hosted ownership in one SQLite transaction.
- Add explicit administrator-attested recovery of the original owner and step, with atomic retry accounting, lease release and an exact-once private audit receipt. Reject malformed progress and receipts without changing ownership.
- Retain Protocol `1.8.0`: SQLite operational progress remains backward-readable and STATE/WORK schemas and lifecycle artifacts are unchanged. Recovery attests trusted termination facts; it does not verify native child termination or authorize a supervisor to assert it.

### R17 Newman tool checks

- Check the Newman executable and version before starting an owned server. Missing, invalid, nonzero or timed-out tool checks persist the existing `execution`/`tool` blocker and `fix_tool` guidance with server stages marked `not_run`.
- Preserve readiness, owned-process liveness, cleanup and source/evidence verification. Protocol remains `1.8.0`: old receipts remain readable and no STATE/WORK or schema fields change.

### R00 lifecycle measurement

- Ship a reproducible lifecycle benchmark with committed comment anchors, evidence-tamper checks, validated CLI response meanings, raw timing samples and automatic fixture cleanup.
- Record YAML/Git/evidence-read/hash counters and warm-cache/source metadata; opt into expensive Newman and delivered-WORK sweeps explicitly. Synthetic reports and CLI-only steps do not claim native agent execution or token measurements.
- Retain Protocol `1.8.0` and plugin versions: measurement tools do not change lifecycle artifacts or runtime contracts.

### R01 hosted telemetry

- Require the reserved attempt explicitly for hosted telemetry and expose machine-readable failure reasons while retaining fail-open execution.
- Add telemetry schema v3 with optional caller-reported UTF-8 context bytes and measured stage durations, explicit unmeasured token usage and backward-readable v2 inflight completion.
- Keep Protocol `1.8.0`: only operational telemetry changes; STATE/WORK artifacts, lifecycle transitions and independent approval gates remain unchanged. No plugin release or manifest version change is made by this patch.

## 0.10.1 - 2026-10-12 - Hosted execution and release guards

- Permit the final configured no-progress retry index in hosted `/goal`, matching standalone Autopilot. With the default limit of five, attempt 5 reaches the alternative-model worker route and a further non-progressing attempt is blocked.
- Serialize hosted Goal and standalone Autopilot per domain. Persist hosted session ownership, step reservations, retry bounds and cycle detection across supervisor restarts.
- Validate scout capsules before compact specialist dispatch. Bind optional host telemetry to reserved steps, keep telemetry failures fail-open and preserve Newman preflight diagnostics.
- Keep no-change audit-remediation completion outside unnecessary delivery finalization. Route model/effort capability failures without weakening critical WORK policy.
- Consolidate test discovery into one suite and add fresh full-suite merge/release gates with Newman execution evidence and stable-source checks.
- Synchronize marketplace/plugin manifests and release assertions to `0.10.1`. Keep protocol `1.8.0`: STATE/WORK artifacts, statuses, audit contracts and lifecycle transitions are unchanged.

## 0.10.0 - 2026-10-08 - Routed execution efficiency

- Record fail-open hosted `/goal` scout and primary dispatch telemetry under `.devflow/runtime/<domain>/host-dispatch.jsonl`, including model, role, attempt, action fingerprint, outcome and elapsed time. Telemetry remains operational evidence, not lifecycle authority.
- Route `frontier` to GPT-6.1 Sol, retain GPT-6 Luna as `fast` and GPT-5.6 Terra as `balanced`. Allow normal `frontier` to fall back to Terra when Sol cannot spawn; retain Sol-only fail-closed `hardest` for critical authority.
- Select the explicit action or WORK risk for executor and WORK verifier routing, falling back to domain risk when none is present. Keep the domain risk floor for planning, phase/integration audit, diagnosis and finalization.
- Make Terra scouting adaptive: run by default for integration audits and diagnosis, on critical architect/WORK verification, and on selected specialist retries. Hosted primary dispatches reuse a successful scout capsule without repeating full packet exploration; missing evidence can still trigger authoritative packet recovery.
- Omit the whole-work finalization protocol from ordinary plan, run and non-integration audit packets. Include it for finalization, enabled integration audits and traced Newman repair WORK.
- Execute Newman and its diagnosis/repair/rerun loop before invoking installed ELI5. Refuse premature `delivery explain` until branch test evidence and traced repairs are current. Preserve stale-explanation invalidation after later changes.
- Synchronize the Claude marketplace, Claude/Codex plugin manifests, current documentation and release regression assertions to `0.10.0`. Retain protocol `1.8.0` with no STATE/WORK schema, status, enum or lifecycle-transition migration.

## 0.9.4 - 2026-10-07 - Contract/runtime alignment and structure

- Correct `core/protocol/risk-policy.md`, which denied a plan closure audit that `lifecycle.md`, `audit.schema.yaml`, and the runtime all implement. Protocol version stays `1.8.0`; this aligns a stale rule rather than changing behavior.
- Record `target_sha`, `active_phase`, and the `next_action` shape in `state.schema.yaml`, and the runtime-enforced `phase` and `task` keys in `audit.schema.yaml`. Both were runtime-written but absent from the contract.
- Record the detached-checkout `checkout_mode`/`branch_start_sha` delivery branch fields and the WORK `title`, `block_reason`, `risk.axes`, `evidence.commit`, `evidence.changed_files`, `evidence.deviations`, and `evidence.discoveries` fields.
- Enforce `multi_agent` in `ModelRegistry`, which `model-registry.schema.yaml` has always required. Legacy `routing.yaml` `models:` entries predate the key and default it to `false` so an existing project policy stays loadable.
- Document `profile_order` and `delegation.recursive` in `routing.schema.yaml`; the controller reads both before selecting a backend.
- Define the `goal` and `autopilot` skills as execution drivers that own no lifecycle transition. Manual `plan`/`run`/`audit`/`status` behavior is unchanged.
- Route every `work review` refusal through `reject_transition` and share the WORK completeness block between the phase and integration verify guards. Refusal wording is unchanged.
- Report the calling command, not always `Audit apply`, when a YAML transaction rollback fails.
- Package both marketplace adapters. `package.sh` previously produced an archive with no adapter, so it could not resolve `plugins/devflow`, and it shipped the `docs/` tree that `.gitignore` excludes.
- Document the adapter-independent `invoke.py` wrapper as the primary command path in the shared skills. `CLAUDE_PLUGIN_ROOT` is never set under the Codex adapter.
- Report a non-mapping WORK `risk` as `risk must be a mapping` instead of raising `AttributeError: 'str' object has no attribute 'get'`. `validate` now names the field, and `status` projects the domain instead of failing. Every other reader treats a non-mapping `risk` as undeclared through `risk_level()`.
- Split `validate_item`, `base_next_action`, and `work_update` into named per-concern and per-subcommand units. Behavior is unchanged: verified by differential harnesses covering WORK validation, the next-action state machine, and every `work` CLI transition, plus the full regression suites.

## 0.9.3 - 2026-10-02 - Remediation recovery and hosted routing

- Keep verified mitigation separate from unresolved historical evidence through additive `evidence.mitigation` and `evidence.residual_risks` metadata. A mitigation can be verified while an external evidence WORK remains unresolved.
- Include the selected WORK manifest in `next.input`, including integration-scoped `provide-evidence` handoffs.
- Publish the scheduler and external-wait runtime changes as plugin `0.9.3` so plugin caches do not continue serving the older `0.9.2` runtime.
- Keep work-review remediation membership separate from execution dependencies. A stalled sibling no longer forces an immediate human decision before another review closure or runnable WORK is considered.
- Add explicit external-evidence recovery with `work wait-external`, `work resume`, and `work unblock`. External waits persist as a backward-readable blocked subtype, expose `provide-evidence` only after runnable actions are exhausted, and retain transition/evidence provenance.
- Normalize legacy `evidence.delivery: null` on `work start` and validate malformed non-mapping delivery evidence before runtime access.
- Keep protocol `1.8.0`: existing status enums are unchanged, and protocol 1.8 readers continue to see the additive external-wait metadata as ordinary blocked WORK.
- Add a Codex-hosted `/goal` driver that delegates routed specialists through native `spawn_agent` calls instead of nesting `codex exec` under the parent session.
- Keep model and reasoning-effort routing deterministic while sending compact repository-recovery messages. Each child renders the authoritative DevFlow packet from disk, which avoids duplicating large runtime packets in a second Codex session.
- Keep `autopilot start`, `autopilot resume`, and `autopilot bootstrap` as standalone compatibility drivers. Hosted Goal execution no longer depends on their blocking subprocess timeout path.
- Add host-dispatch regression coverage for routed models, execution boundaries, packet recovery, bootstrap finalization, and operation without a Codex subprocess backend. Protocol version remains `1.8.0` because lifecycle artifacts and transitions are unchanged.

## 0.9.2 - 2026-09-29 - Permission inheritance and resilient dispatch

- Remove the accidental `typing_extensions` runtime dependency so the documented Python 3.10+ and PyYAML-only runtime contract remains sufficient.
- Keep `DEVFLOW_CODEX_BIN` as the explicit raw Codex executable override, remove generic wrapper/argv composition, and reuse an inherited `OPENAI_BASE_URL` for child `codex exec` dispatches. This lets a parent Headroom session own one proxy lifecycle instead of nesting `headroom wrap` around every specialist.
- Replace forced legacy `--sandbox` flags with permission-profile routing. Mutating roles inherit the caller's `default_permissions`, scout and diagnostician roles use `:read-only`, and legacy routing overrides remain readable.
- Separate model capability failures from network, permission, backend, and wrapper failures. Only model-specific capability failures mark a model/backend pair unavailable; infrastructure failures block without contaminating later routing.
- Separate timeout recovery from semantic no-progress retries. The first timeout schedules independent diagnosis without incrementing the no-progress attempt, while a second timeout for the same action blocks with persisted timeout telemetry instead of starting another 30-minute retry cycle.
- Preserve the concrete routing exception in blocked controller checkpoints instead of collapsing every routing failure to an opaque `route_unavailable`, and keep critical Luna `max` execution fail-closed when that executor is unavailable.
- Protocol version remains `1.8.0`; these changes affect runtime orchestration and plugin metadata only.

## 0.9.1 - 2026-09-29 - Cost-aware routing and detached delivery

- Support Codex-style detached linked worktrees in delivery lifecycle handling by capturing the target branch at `work start`, preserving it through completion, and allowing final checks/refresh while the target branch remains an ancestor of isolated delivered commits.
- Keep attached-branch provenance strict: explicit branch mismatches, detached divergence, and branch commits beyond delivered HEAD still fail closed.
- Make Sol the decision authority: planning, verification, audit and finalization default to `frontier` at `high`, with `xhigh` reserved for high/critical reasoning, integration audit and diagnosis; `frontier`/`hardest` no longer silently fall back to Terra.
- Keep implementation authority on Luna: routine executor WORK uses `fast/high`, difficult/high-risk execution uses `fast/xhigh`, critical execution uses `fast/max`, and stalled workers climb `high -> xhigh -> max`, receive an independent Sol diagnosis, retry Luna at `max`, then explicitly replace the executor with Terra `xhigh` as the final alternative.
- Make Terra the bounded pre-analysis layer for Sol decision roles: Terra reads the full runtime/repository context at `medium` (or `high` for high/critical risk), emits a capped evidence capsule, and the subsequent Sol dispatch receives that capsule instead of the full packet with an explicit re-render escape hatch. Same-model scout fallback is skipped to avoid paying for duplicate Sol calls.
- Preserve pre-0.9.1 project retry overrides by replacing the staged defaults when legacy retry keys are detected, and align marketplace/plugin version assertions and documentation on plugin `0.9.1` without changing the runtime artifact protocol.

## 0.9.0 - Autonomous routing

- Add foreground `/goal` / Autopilot lifecycle execution over the existing deterministic next-action state machine.
- Add `--until plan|implementation|complete` execution boundaries with successful runtime checkpoints before the next stage dispatch.
- Add task-aware logical model profiles with per-WORK risk promotion, risk/retry escalation, and runtime model/backend fallback persisted across resume.
- Add isolated Codex exec dispatch, optional host native-agent bridge, bounded context capsules, dedicated read-only scouting/diagnosis, measured-token budgeting, a cross-process mutating lease, atomic controller checkpoints, and dispatch ledger.
- Route new-domain `/goal` PRD bootstrap through the Architect profile before initialization, inject the concrete installed DevFlow CLI path into specialist capsules, and fail closed on invalid routed PRDs.
- Treat model-capacity/overload responses as capability failures so routing can fall through to the next candidate; gate Codex candidates by their minimum supported CLI version (GPT-5.6 `0.144.0+`).
- Replace the unenforceable hard-token-ceiling claim with a measured pre-dispatch reservation guard (25k specialist / 8k scout by default) and explicit one-in-flight-dispatch overrun semantics.
- Harden owned-server finalization with a post-readiness liveness window and deterministic process-group TERM/KILL confirmation; harden the server lifecycle fixture so readiness cannot race process initialization.
- Ship both root marketplace adapters and synchronize plugin/skill-set regression expectations for 0.9.0 while retaining protocol 1.8.0 compatibility.
- Keep manual plan/run/audit/status workflows and existing lifecycle artifacts compatible under protocol 1.8.0.

## 0.8.1 - 2026-09-11

Protocol 1.8.0: `delivery newman` owns the server argv lifecycle, including bounded process-group
cleanup and HTTP 200..299 readiness. Startup, readiness, environment, Newman-tool and cleanup
failures are blocked; completed API/assertion failures are failed; code/collection triage requires
a completed failed Newman run. `not_applicable` requires matching zero-HTTP evidence in the
collection and declared endpoint record. Plugin 0.8.1 is required because this runtime contract
is not compatible with the released 0.8.0 finalization behavior.

## 0.8.0 - 2026-09-10

Protocol 1.7.0: whole-domain installed-ELI5 HTML; foreground Newman runs; private diagnostics and sanitized receipts; contract-based code/collection/environment diagnosis; ordinary committed remediation WORK; fresh-evidence finalization gate. Preserves both adapters, private docs and independent audits.

## 0.7.0

### Added

- Protocol 1.6 source-comment evidence and atomic completion checks for changed executable source.
  Audits independently assess semantic usefulness; docs/config/deletion-only WORK records a reason.
- Cumulative per-branch PR Markdown from the consuming project's `docs/PR/templates.md`, with exact
  heading-order checks, pinned base/head metadata, collision-resistant paths and content hashes.
- Cumulative per-branch Postman v2.1 JSON and an offline authoring-profile validator. Checks include
  nested structure, scoped variables, auth/body/test-script shape, declared endpoint coverage and
  common credential literals. No-HTTP branches have explained empty collections.
- `delivery enable`, `delivery paths`, `delivery check [--final]` and `delivery refresh` CLI helpers.
- Independent delivery regression tests using real Git source objects and local ignored artifacts.

### Fixed

- Aligned the previously restrictive artifact budget across protocol, skills and prompts with the
  requested PR/Postman deliverables, so executors receive one coherent completion contract.
- Rendered packets now include the actual project PR template and delivery policy context.
- Run instructions distinguish ready-item start from in-progress resumption, preserving the
  original start SHA instead of invoking a ready-only transition again.
- Enabled completion verifies current source HEAD, comment-source ancestry and uncommitted source;
  arbitrary/stale commit strings cannot establish delivery provenance.
- Restored the executable permission on `bin/devflow`; added a real wrapper launch regression.
- The timeout-diagnostic test skips unrelated Python site initialization while keeping its original
  timeout, sleeping child and output assertions.
- Pinned parent bases survive parent branch deletion; generated filenames distinguish slash,
  punctuation and case variations. Final checks detect advancing source branch tips.

### Compatibility and limits

- Plugin version 0.7.0; protocol version 1.6.0. Legacy domains remain backward-readable. `delivery
  enable` adopts active domains without rewriting PLAN or WORK, preserving already-done items.
- New domains and plan/run preflight enable the policy. Every remaining implementation/remediation
  WORK refreshes outputs before completion; one selected WORK per invocation remains unchanged.
- Local docs stay fully gitignore-compatible. Source Git provenance remains required.
- The validator is an offline, conservative v2.1 profile. Semantic comments, full API accuracy,
  Postman GUI import and real server execution require their corresponding review/runtime evidence.
  Generation performs no remote publication, branch push/merge or API requests.

## 0.6.1

### Fixed

- A closure apply now records `audit_provenance.applied_against` before its atomic validation and
  write. Persisted closures validate against that prior finding set, while
  `audit_provenance.findings` remains the basis for a later closure.
- The recovery command printed for a legacy work closure now accepts a `remediation` review only
  when it has no provenance. Work and plan recovery clear stale `remediation_work_ids`, so the
  documented commands reach a fresh initial audit without weakening normal review guards.
- A closed `DECISION_REQUIRED` finding now validates its linked resolved decision instead of
  requiring the record to remain open. An `accepted_risk` closure can therefore complete after its
  decision is resolved, while active decision findings still require open records.
- The timeout diagnostic test allows two seconds for process startup while its child continues to
  sleep for five seconds, reducing environment-sensitive failures.

### Changed

- Current marketplace documentation now reports plugin `0.6.1` and protocol `1.5.0` consistently.

### Compatibility and migration

- Plugin version is `0.6.1`. Protocol version is `1.5.0`. The plugin identifies the distribution,
  while the protocol identifies the artifact contract.
- The protocol minor moved to `1.5.0` because `audit_provenance.applied_against` adds a validation
  basis that a 1.4 runtime does not understand. An older runtime cannot safely claim full support
  for artifacts carrying this field.
- Protocol 1.0 through 1.4 STATE and WORK remain backward-readable. Existing provenance records
  containing only `findings` use the previous fallback behavior, and no bulk migration is required.

## 0.6.0

### Added

- **`devflow work review <domain> <ID> pending`.** A `blocked` work review can be returned to
  `pending` and re-audited, the work-scope equivalent of `plan-review set pending`,
  `phase set <n> audit` and `integration set <d> audit`.
- **Machine-owned `audit_provenance`.** `STATE.plan_review`, `STATE.phases.<key>`,
  `STATE.integration` and a WORK item's `review` carry an optional `audit_provenance.findings`
  mapping of finding ID to severity, written by `devflow audit apply` and read by a later closure.
- `render audit --mode closure` emits a `prior_findings` line so the auditor can cover the recorded
  prior findings without reading Git.

### Changed

- **Duplicate YAML keys are rejected on every read.** `load_yaml` parses STATE, WORK, DECISIONS
  and `.devflow/config.yaml` through a unique-key loader, so a second `phases:` or `items:` block
  in a hand-edited file fails loudly instead of silently keeping the last value. Audit front matter
  already rejected duplicates; this extends the same rule to the rest.
- The refusal for a closure at a scope with no recorded provenance now spells out the whole
  recovery in one message: run the scope's recovery command, re-render and re-apply the initial
  audit, then retry the closure. `lifecycle.md` carries the same as a "Closure without recorded
  provenance" migration subsection.
- **Closure provenance is machine-owned, not read from Git.** `devflow audit apply` now records the
  applied finding set as an `audit_provenance` mapping of finding ID to severity on the audited
  scope's own machine-owned metadata (`STATE.plan_review`, `STATE.phases.<key>`,
  `STATE.integration`, or the WORK item's `review`), for both initial and closure modes. A later
  closure recovers the prior finding set from that record. The former Git-history reader for the
  canonical audit file, and its `git log` / `git show` reads, are removed. No DevFlow lifecycle
  operation reads Git history for any file under `domains_root`, so the full delivery and
  audit-remediation lifecycle completes with `docs/` fully gitignored and the canonical audit never
  committed. Source-code Git use (baseline/target SHAs, phase diff ranges, `devflow phase ref`
  ancestry checks, `git show <ref>:<path>` for reading source) is unchanged.
- A closure requested at a scope with no recorded `audit_provenance` is refused deterministically
  and names that scope's recovery command (`devflow plan-review set <domain> pending`,
  `devflow work review <domain> <WORK-ID> pending`, `devflow phase set <domain> <phase> audit`, or
  `devflow integration set <domain> audit`). Provenance is never inferred and never reconstructed
  from Git.
- `render audit --mode closure` prints a `prior_findings` line with the recorded prior finding IDs.
- A closure audit can no longer lower the severity the verdict rubric evaluates. A finding recorded
  as `still_open`, and every ID a `reopened` entry names in `reopened_as`, must carry a severity at
  least as high as the severity recorded for that prior finding. Raising a severity with new
  evidence is still allowed; `resolved` and `accepted_risk` findings leave the active set and are
  exempt. The severity order is read from `finding.schema.yaml`, not hardcoded.
- **The project config protocol version is a floor.** When `.devflow/config.yaml` exists, the 1.3
  audit-apply gate decides from the higher of the STATE and config `protocol_version`. Hand-editing
  `STATE.protocol_version` below the config no longer re-enables `plan-review set`, `work review`,
  `phase set`, or `integration set` `verified`, and `validate` reports a STATE protocol older than
  the config as an error. A project with no config file, or one whose config genuinely records the
  older version, keeps the legacy verified transitions unchanged; a newer-than-runtime config keeps
  its existing read-only-plus-mutation-block behavior.

### Fixed

- **A domain is constrained to `domains_root`.** `domain_dir()` now rejects a domain argument whose
  resolved directory escapes the configured root (`../escaped`, `../../../x`, an absolute path),
  exiting `2` with a message naming the root and creating nothing. One guard in the function every
  command routes through covers all call sites. A nested domain that stays inside the root, and a
  custom `domains_root`, keep working.
- **A work closure audit reports `project_status: work_audit`.** `project_status_for_action()` now
  returns `work_audit` for a `scope: work` audit in both modes. A phaseless work closure audit was
  reported as `integration_closure`, and a phase work closure as `remediation`, contradicting the
  `next.scope` printed beside it.
- **Every lifecycle mutation is atomic.** `work start|done|block|review`, `phase set|ref`,
  `plan-review set`, `integration set` and `decision add|resolve` now project their prospective
  STATE (and any changed WORK) on copies and commit the changed documents through one
  `commit_yaml_transaction()`, mirroring `audit apply`. Previously each wrote its primary artifact
  and only then refreshed derived STATE, so a projection failure on structurally invalid input left
  the artifact mutated while the command reported failure. A command that exits non-zero now leaves
  WORK and STATE byte-identical. This remains process-local failure rollback, not crash recovery or
  concurrent-writer isolation.
- **A stop-blocked WORK review can be re-audited.** `devflow work review <domain> <ID> pending`
  returns a `blocked` work review to `pending`, clears its `remediation_work_ids`, and projects a
  fresh work initial audit. It is refused from any other review status and never sets a review
  verified, so a `SPEC_DRIFT` or other `stop` finding no longer strands its phase. This mirrors the
  existing `plan-review set pending`, `phase set <n> audit` and `integration set <d> audit`
  recoveries, which previously had no work-scope equivalent.

### Compatibility and migration

- Plugin version is `0.6.0`. Protocol version is `1.4.0`. These remain separate version domains: the
  plugin identifies the distribution, the protocol identifies the artifact contract.
- **Why the protocol minor moved to `1.4.0`.** Closure provenance became a machine-owned artifact
  field (`audit_provenance`). A protocol 1.3 runtime does not know that field and cannot safely
  mutate a STATE or WORK artifact that carries it, so this is a protocol minor bump rather than a
  plugin-only release.
- Protocol 1.0 through 1.3 STATE and WORK remain backward-readable. `audit_provenance` is optional
  everywhere and is required only at the moment a closure audit is applied or validated.
- **The one deliberate migration cost.** A protocol 1.3.0 domain that is sitting mid-closure when
  this runtime arrives has no recorded provenance, so its closure is refused with a named recovery
  command. Re-run the scope's initial audit through that command and the closure then proceeds:
  `devflow plan-review set <domain> pending` for plan scope,
  `devflow work review <domain> <WORK-ID> pending` for work scope,
  `devflow phase set <domain> <phase> audit` for phase scope, and
  `devflow integration set <domain> audit` for integration scope. The refusal is deterministic, not
  inferred, and no bulk migration command is required.
- A project whose `.devflow/config.yaml` records `1.3.0` or newer and whose `STATE.yaml` was
  hand-edited to an older protocol now fails `validate` with a STATE-older-than-config error, and
  the audit-apply gate decides from the higher of the two versions. A project with no config file,
  or one whose config genuinely records the older version, is unaffected.
- WORK v1 string shapes, missing `workflow_type`, missing `plan_review.audit_file` and missing
  `review` metadata all continue to read as before.

## 0.5.0

### Added

- **Brownfield audit/remediation workflow.** `init --workflow audit-remediation` creates a
  phase-free `audit_remediation` lifecycle that can move from integration initial audit through
  decisions or `work/integration.yaml` remediation, required WORK review, integration closure, and
  project completion without a fake phase.
- **Machine-readable audit outcomes.** The single canonical audit Markdown now carries
  `devflow-audit-v1` YAML front matter for scope, mode, verdict, immutable SHAs, executed
  verification, findings, and closure outcomes. `devflow audit apply` validates the complete
  outcome and commits accepted STATE and WORK changes atomically.
- **WORK v2 acceptance coverage.** New WORK gives acceptance criteria and verification commands
  unique IDs and requires each command to declare `covers`, with every acceptance ID covered by at
  least one executable verification command.
- **Finding, decision, and WORK traceability.** Audit dispositions and WORK origins must link in
  both directions. Decision findings block ready code WORK, and multi-finding WORK requires an
  explicit aggregation rationale for its shared change and verification boundary.
- **End-to-end regression coverage.** Tests exercise no-finding, remediation, decision, reopened
  finding, and delivery lifecycles through real CLI subprocesses.

### Changed

- `render` is lifecycle-aware and rejects a plan, run, or audit request that differs from the exact
  next action before printing a packet or creating an artifact.
- Cross-artifact validation rejects placeholder contracts, orphan or mismatched phase manifests,
  unsupported runtime config versions, invalid audit lifecycle evidence, and findings without an
  evidence-backed `severity_reason`.
- `.devflow/config.yaml` is the project runtime configuration and protocol compatibility guard.
  Domain PRD, PLAN, STATE, PITFALLS, DECISIONS, WORK, and AUDIT artifacts remain under
  `docs/domains/<domain>/` by default. `init` and `status` report both paths explicitly.

### Compatibility and migration

- Plugin version is `0.5.0`. Protocol version is `1.3.0`. These are separate version domains: the
  plugin identifies the distribution, while the protocol identifies the artifact contract.
- The protocol minor bump records contract additions that a 1.2 runtime cannot safely mutate:
  explicit workflow type, audit metadata and apply transitions, WORK v2 coverage, and new lifecycle
  states and traceability rules.
- Protocol 1.0 through 1.2 STATE and WORK artifacts remain backward-readable. Missing
  `workflow_type` reads as `delivery`, WORK v1 keeps its legacy string shape, and existing review
  defaults are supplied in memory without rewriting artifacts.
- Legacy audit Markdown without front matter remains readable as historical evidence, but cannot
  authorize a protocol 1.3 verified transition. No bulk migration command is required. A fresh
  project initialization records protocol `1.3.0` in runtime config and STATE, while existing
  artifacts migrate only when a user intentionally adopts the new workflow or audit transition
  contract.

## 0.4.0

### Added

- **Normative peer-skill composition policy.** `core/protocol/skill-composition.md` defines where
  DevFlow authority ends and optional peer skill behavior begins, and `lifecycle.md` cross-references
  it without duplicating the policy.
- **Superpowers execution-discipline composition.** The `run` skill composes test-driven-development
  for behavior-changing WORK, systematic-debugging for defect and remediation WORK, and
  verification-before-completion before a WORK is reported done, all inside the one selected ready
  WORK. Explicit repository or user instructions already authorize a TDD exception, so the run does
  not stop to re-ask.
- **Ponytail reuse/YAGNI composition.** The `plan` and `run` skills apply the currently active
  Ponytail policy as a minimalism lens inside DevFlow-owned boundaries.
- **Ponytail-backed complexity discovery as an advisory audit lens.** The `audit` skill treats
  Ponytail observations as leads mapped to the existing overengineering axis; only an independently
  verified lead becomes a DevFlow AUDIT finding.
- **Regression coverage** protecting DevFlow lifecycle ownership, the optional and non-coupling
  nature of peer composition, and the absence of peer-plugin state fields in templates and schemas.

### Changed

- DevFlow skills now explicitly distinguish lifecycle ownership from optional peer execution and
  minimization policies.
- Documentation describes safe composition with separately installed Superpowers and Ponytail,
  including the warning against running a Superpowers controller workflow nested inside an active
  DevFlow lifecycle.

### Compatibility

- Plugin version: 0.4.0.
- Protocol version: 1.2.0, unchanged. Peer composition is documentation and skill guidance only and
  creates no new artifact contract.
- No STATE, WORK, or AUDIT schema migration is required, and existing 0.3.1 project artifacts remain
  readable.
- Superpowers and Ponytail remain optional external plugins. No DevFlow command fails when a peer
  plugin is absent.

## 0.3.1

### Fixed

- **`validate` now gates verification instead of only reporting.** A domain whose WORK manifests
  failed validation could be driven all the way to `project_status: complete`. No transition
  consulted the validator, so items missing `objective`, `scope`, `requirements`, and
  `stop_conditions` rode through phase verification and integration verification untouched. `phase
  set <phase> verified` and `integration set verified` now refuse while the domain has validation
  errors, and report them prefixed with `validation:`.
- **`protocol_version` is read, not just written.** The runtime recorded the version in STATE and in
  `.devflow/config.yaml` and never compared it to its own. A STATE claiming `2.0.0`, or a malformed
  value, validated cleanly. `protocol_version` must use the numeric x.y.z form. Malformed short,
  extended, prefixed, or non-numeric forms are rejected. `validate` now errors on a different major
  version, errors on an unparseable one, and warns when the minor version is newer than the runtime's.
- **The schema's required phase entry fields are enforced.** `state.schema.yaml` declared
  `phase_entry.required: [status, work_file, audit_file]`, but the validator only checked `status`,
  so a phase entry missing both file paths passed without so much as a warning.
- **`phase set` and `phase ref` no longer invent a phase.** A mistyped number created a new STATE
  entry that could never be verified, which blocked integration permanently because integration
  requires every phase verified. Both commands now accept a phase that is already in STATE or has its
  WORK file on disk, and refuse otherwise.
- **An initial work audit reports its own lifecycle position.** `project_status` projected a
  work-scope audit as `phase_audit`, contradicting the `next.scope: work` printed beside it. The
  derived value is now `work_audit`.
- **Work review selection orders by phase before id.** `work_review_action` sorted by WORK id first
  while `choose_next` sorted by phase first, so a later phase's review could be handed out ahead of
  an earlier phase's. Both halves of the runtime now use the same ordering.
- **An unknown WORK id prints a clean message.** `str(KeyError)` is the repr of its argument, so the
  CLI reported `DevFlow error: 'Unknown WORK item: X'` with the quotes included.
- **`bin/devflow` resolves symlinks.** Linking it into a `PATH` directory made `dirname "$0"` resolve
  to the link's directory, and the wrapper looked for the runtime under the wrong root.

### Changed

- Generated `.devflow/config.yaml` no longer duplicates `protocol_version`. `STATE.yaml` is the
  protocol-version source of truth for each domain. Existing configs carrying the old field remain
  readable and the stale field is ignored.
- Protocol version is `1.2.0`. `project_status` gained the derived value `work_audit`, and a `1.1.0`
  runtime validates that field against its own allowed set, so it would reject a STATE this runtime
  writes. Existing `1.0.0` and `1.1.0` domains keep validating here, and no migration is required.
- Removed four parameters that every caller passed and no body read: `root` and `domain` from
  `work_start_errors`, `index` from `phase_verify_errors` and `integration_verify_errors`, and
  `state` from `project_status_for_action`.

## 0.3.0

### Added

- Schema-backed validation constants, atomic YAML writes, computed lifecycle state, and subprocess
  timeouts for diagnostics.
- `work` audit scope with initial and closure modes, plus the high/critical WORK review gate before
  dependents proceed.
- Runtime transition guards for WORK, plan review, phase, and integration state changes.
- Scope-aware context assembly: full PRD for planning, origin-linked context for WORK and work/phase
  audits, and bounded integration summaries and paths.

### Changed

- Plan review now uses its own artifact and defaults legacy missing `audit_file` to `audits/plan.md`.
- Existing WORK without review remains readable. Legacy high/critical done WORK is treated as
  requiring review before dependents, with no mandatory migration command.
- Plugin version is 0.3.0. Protocol version remains `1.1.0`: review metadata and plan audit-file
  defaults are backward-readable runtime normalization, so this release does not create an
  incompatible artifact contract. The stronger dependency gate is a runtime behavior change, not a
  protocol-version reset.
- Autonomous orchestration is explicitly out of scope. The runtime computes and renders the next
  action; agents or humans perform it.

## 0.2.0

### Fixed

- **Phase key normalization.** `choose_next` normalized its lookup key but not the STATE keys it
  looked up in, so a phase written as `"5"` never matched `"05"` and the runtime kept handing out
  work items from a phase already marked `verified`. The SSOT's own example used the unpadded form,
  so following the reference documentation produced the broken state. All readers now normalize both
  sides.
- **Duplicate phase entries.** `phase set` created a second entry when STATE already held the same
  phase under a differently formatted key, and `validate` reported no error. `phase set` now updates
  the existing entry, and `validate` rejects two raw keys that normalize to one phase.
- **`status` no longer rewrites STATE on every read.** It writes only when the computed state
  actually changed, so an inspection command stops producing diff noise.

### Added

- **`PITFALLS.md`, a seventh project artifact.** The half of a handoff that no state machine can
  compute: fakes that always succeed, methods that no-op instead of raising, a verification command
  that skips the suite it appears to run, the next free migration number, behavior that looks like a
  defect but is a recorded decision. `plan`, `run`, and `audit` all load it.
- **WORK item contract depth.** New `context`, `premise_checks`, `pitfalls`, `blocks`, `transfer`,
  and `references` fields, so an item carries what the Architect learned instead of forcing the
  Executor to re-derive it. `validate` requires `premise_checks` on `high` and `critical` risk.
- **`devflow phase ref`.** Pins `base_sha`, `head_sha`, and `diff_range` into STATE after verifying
  with `git merge-base --is-ancestor` that a 3-dot range is trustworthy. It refuses rather than
  guessing when the history diverged, and takes `--range` for that case. `authority.md` documented
  `diff_range` as mandatory but nothing computed it.
- **Transfer enforcement.** `validate` now requires a `transferred` item to name `transfer.to` and
  requires the receiving item to carry the same `origin.requirements`. The rule existed in the
  protocol; the check that makes it real did not.
- **Evidence enforcement.** `devflow work done` refuses a completion with no recorded command, and
  `validate` errors on a `done` item with an empty `evidence.commands`, except for
  `kind: documentation`.
- **Lifecycle consistency checks.** `validate` rejects a phase marked `verified` while its own work
  is unfinished, and an integration marked `verified` while a phase is not.
- **Audit extension resolution.** `.devflow/extensions/<name>.md`, then the bundled
  `core/extensions/<name>.md`, then `default.md`, selected per domain through `STATE.extension` or
  per project through `.devflow/config.yaml`. Previously every audit silently got `default.md`.
- **`status` reports more.** Blocked work items, the phase diff range, and `next.input` lines naming
  the documents and requirement ids the next action needs.

### Changed

- **`render` now assembles a complete prompt.** It inlines the relevant protocol documents, the
  resolved extension, and `PITFALLS.md` instead of printing a list of file paths.
- **`audit-core.md` restored to working depth.** Ten one-line axis labels became concrete per-axis
  checks, plus severity definitions, a pass / conditional_pass / fail rubric, the "never write pass
  without evidence" rule, the merge-base verification procedure, and the do-not-check-out-branches
  rule.
- **`AUDIT.md` template** gained a verdict rubric, a findings table, per-axis sections, an
  integration-only section, and an executed-verification table.
- **Skill reference duplication removed.** Eight byte-identical copies of `core/protocol/*.md` under
  `skills/*/references/` are gone; `render` inlines the originals, so they cannot drift.
- **Skill runtime invocation documented explicitly** instead of assuming a working directory.
- `finding.schema.yaml` carries severity meanings, verdicts, and per-classification dispositions.
- Agent interface descriptions no longer truncate mid-word.
- Protocol version is `1.1.0`. Existing `1.0.0` domains keep validating.
- Removed an unused `os` import from the runtime.

## 0.1.0

- Initial DevFlow protocol extracted from the historical `vibecoder.md` design review (preserved in Git history).
- Added plan, run, audit, status lifecycle.
- Added STATE/WORK validation and prompt rendering runtime.
