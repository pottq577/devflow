# Domain pitfalls and accumulated context

Traps a fresh session must know before touching this domain. This is the half of a handoff that
`status` cannot compute: `STATE.yaml` says where the work is, this file says what will bite you.

Every entry earns its place by having cost something once. Delete an entry when the trap is gone,
not when it feels obvious.

`plan`, `run`, and `audit` all load this file. Keep it short enough that they can.

## Environment and tooling

- Which verification command actually runs the full suite, and which one silently skips it.
- Build cache or up-to-date behavior that makes a test look green without running.
- Which parts of the tree are ignored by version control, and what that means for handoffs.

## Test doubles and local profiles

- Fakes and mocks that always return success, and the paths they therefore cannot exercise.
- Seams a fake exposes for simulating failure, and how to trigger them.

## Code behavior that surprises

- Methods that fail silently instead of raising, and what that forces callers to do.
- Guards that admit more states than their name suggests, and why.
- Ordering or locking rules that are load-bearing but not obvious from the call site.

## Schema and migration

- The next free migration number.
- Migrations that must never be edited, and the forward-only rule.

## Out of scope

- Work that looks like a defect here but is a deliberate, recorded decision. Name the decision id
  so nobody "fixes" it.

## Lessons carried forward

- What the last cycle got wrong, and the rule that came out of it.
