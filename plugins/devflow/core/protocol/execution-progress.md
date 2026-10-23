# Execution progress and host handoff

`devflow execution handoff <domain>` is a **read-only operational projection** of the
current computed lifecycle action, current Git state, the most recent matching
checkpoint, and unfinished DevFlow CLI mutations. It is not a substitute for
`devflow status`, WORK evidence, audits, or the hosted/standalone lease guards.

The runtime automatically records start/finish events for lifecycle-mutating
DevFlow CLI invocations across planning, WORK, audits, decisions, delivery and
finalization. This records command exit codes, not proof of the result. A missing
finish event means **unknown**, not failure, success, or permission to replay.
Commands that only inspect state do not create journal events. Direct source edits,
model reasoning, and external test commands are not automatically observed.

After a material milestone in any long-running role (planning, implementation,
audit, verification, or finalization), record a concise **caller-reported**
checkpoint when safe. Do not checkpoint every tool call or invent results:

```
devflow execution checkpoint <domain> --stage implementation \
  --note 'Service change made; regression pending' \
  --completed 'Service method updated' \
  --pending 'Run the controller integration test' \
  --verification './gradlew test -> not yet run' --host codex
```

Use a stage appropriate to the actual lifecycle action (planning, implementation,
verification, audit, finalization, etc.). Never claim a verification result that
was not observed. Do not copy full conversations, source bodies, private tokens,
credentials, or raw test logs into a checkpoint. Prefer references to existing
WORK/PLAN/DECISIONS/audit evidence and Git paths. No new mandatory checkpoint
or lifecycle artifact is introduced, and this facility requires no additional model call. If a journal write fails,
continue the ordinary lifecycle and report the missing observation.

On another host, run `devflow execution handoff <domain>` once when recovery
context is needed. Use `devflow status` to select the actual next action, verify
source changes and test outcomes, and inspect original cited files on demand.
An action-specific checkpoint from a former HEAD or worktree is **advisory**;
its freshness flags never imply its observations are correct. A completed claim
in a checkpoint does not mark WORK done or bypass verification/audit gates.

All journal rows are local under `.devflow/runtime/<domain>/execution-journal.sqlite3`.
They never copy STATE/WORK as another source of lifecycle authority; action
identities are only correlation hints. Corrupt records fail clearly rather than
silently authorizing progress. This journal does not reclaim pending native
children, steal leases, infer provider rate limits or automatically switch CLIs.
The existing `host-telemetry.md` recovery requirements still apply.
