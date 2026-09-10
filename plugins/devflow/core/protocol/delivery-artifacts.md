# Implementation comments and branch delivery artifacts

## Execution contract

Every new domain enables `STATE.delivery.version: 1`. For a legacy active domain, run
`devflow delivery enable <domain>` before planning/execution. This idempotent command preserves
existing PLAN/WORK contents and snapshots already-done WORK as grandfathered. Ready and in-progress
WORK then receives the new requirements. Rendering alone never migrates legacy files. Keep the
Architect -> Executor -> Auditor sequence and exactly one selected WORK per run.

For each code-changing WORK, retain or add a relevant comment/docstring explaining an invariant,
domain rule, transaction boundary, idempotency decision, security constraint, non-obvious tradeoff
or externally imposed limitation. Record at least one anchor in committed, changed source.
Write comments in the repository's language/style. Favor explanations that help a maintainer
change the code safely. Avoid narrating syntax, repeating method names, decorative headings,
commented-out code and placeholder TODOs. Existing accurate comments in changed files count;
update stale comments when behavior changes. There is no per-file or per-method comment quota.
For documentation/config/deletion-only WORK, record a concrete `comments_note` N/A explanation.
An auditor checks semantic usefulness; runtime checks establish source existence and provenance.

## Per-branch outputs

Read the consuming project's **docs/PR/templates.md**. Preserve its headings/order and fill the
body from the actual branch diff, executed verification, migration/rollback impact and remaining
limits. Keep the template unchanged. Include an explained N/A where a section does not apply.
Never mark an unexecuted check as passed. PR generation prepares a local body, with remote
publication/push/merge controlled by the user.

Run `devflow delivery paths <domain>` for the exact output filenames. The runtime derives safe,
collision-resistant names from both domain and branch. One cumulative PR body and one cumulative
Postman collection represent each implemented branch, including stacked branches and remediation.
Update the pair after every WORK on that branch; preserve earlier branch changes and requests.
A stacked branch uses its actual parent as `base_ref`. Pin `base_sha` when that parent moves.
Commit source/tests first, then generate local outputs against that source HEAD. Keep generated
handoffs local/ignored to avoid a commit containing its own hash. Their hashes live in STATE.

PR metadata, above the untouched template headings:

```html
<!-- devflow-delivery: {"branch":"feature/example","base_sha":"<full source base SHA>","head_sha":"<full source HEAD SHA>"} -->
```

Put the same object in collection `info._devflow`. This custom informational property travels
with the Postman v2.1 JSON. The profile does not require Git history for generated documentation.

## WORK evidence

Populate these fields in the existing selected WORK YAML before `work done`:

```yaml
evidence:
  # start_sha is machine-owned by work start. A resumed legacy in-progress item conservatively
  # uses the domain source baseline when no start SHA was previously recorded.
  comments:
    - path: backend/src/main/java/example/Service.java
      line: 42
      reason: Explains why a retry shares the same transaction and idempotency result.
  comments_note: null
  delivery:
    base_ref: develop
    # base_sha: <approved pinned base SHA>  # optional; useful for stacked branches
    pr_file: <pr_file returned by delivery paths>
    postman_file: <postman_file returned by delivery paths>
    api_endpoints: ["GET /api/example", "POST /api/example"]
    api_note: Covers the affected endpoints and their normal, authorization and invalid-input paths.
```

Continue using `devflow work done <domain> <ID> --commit <HEAD> --command '<cmd> -> <actual result>'`.
The runtime resolves the source commit, derives changed files, checks comments and both artifacts,
and records their hashes/provenance in STATE and WORK in the existing atomic transaction.
The narrow artifact allowance covers these two files plus WORK/STATE evidence even when an older
WORK.scope.allowed predates this policy. It grants no other implementation scope expansion.

## Postman authoring

Read actual routes/controllers, DTO validation, authentication and response/error contracts.
Build a **Postman Collection v2.1.0 JSON**, starting from core/templates/POSTMAN.collection.json.
Use collection variables for baseUrl, credentials, tenant/company IDs and created resource IDs.
Keep credentials empty and baseUrl empty or loopback in distributable output. Use synthetic data.
Declare every referenced variable, including IDs populated by response scripts. Preserve IDs/names
when refreshing an existing collection. Add success, invalid-input, permission and relevant
idempotency/concurrency scenarios according to the actual implemented contract.

Every request has or inherits an executed-on-demand `pm.test` assertion script. The offline
profile checks JSON types, folder/request nesting, raw URLs beginning with {{baseUrl}}/,
variables, authentication/header/body/script shape, declared endpoint coverage, credential
literals and source metadata. It deliberately supports a conservative subset of v2.1; it is
not the full official JSON Schema validator. Review unsupported constructs before changing the
profile. Structural validation and actual API execution are separate evidence categories.

For a branch with no affected HTTP surface, still produce a valid empty collection (`item: []`),
set `api_endpoints: []`, and explain the no-HTTP assessment in `api_note` and info.description.
Do not invent routes merely to populate it. The auditor verifies this assessment against the diff.

Generation itself sends no requests. Mark write/payment/deletion/notification scenarios clearly
and document test-only preconditions and cleanup. Protocol 1.7 finalization explicitly executes
authorized isolated local/test Newman runs under `finalization.md`. Production or shared-data
side effects retain separate approval. Missing servers/tools/credentials keep finalization open;
record execution as passed only when the actual run supports it.

## Validation, refresh and audits

`devflow delivery check <domain>` checks all recorded artifacts and source evidence.
`devflow delivery check <domain> --final` also checks extant local branch tips. Integration
verification invokes the final checks through normal domain validation. A deleted/merged local
branch retains its pinned commit provenance; no checkout or branch recreation is required.

When correcting only generated artifact content or adopting a changed PR template, regenerate it
at the same recorded source commit, then run `devflow delivery refresh <domain> --branch <name>`.
Refresh verifies content and updates hashes atomically. New source commits require ordinary WORK;
refresh cannot authenticate uncovered code. Repeated enable calls never expand legacy exemptions.

Auditors verify meaningful comments, PR template fidelity and actual base/head diff scope,
cumulative coverage across WORK, Postman route/DTO/auth/error accuracy, honest execution evidence,
secret hygiene and no-HTTP rationales. Confirmed defects follow ordinary remediation WORK; its
completion refreshes the same branch outputs. All branch artifacts must be current at integration
closure. STATE/WORK/AUDIT remain the lifecycle record; PR/Postman are deliverable outputs.

## Whole-work handoff

When `delivery.finalization` is enabled, follow `finalization.md` after branch generation. Its
single ELI5 HTML covers every WORK/branch and its Newman receipts refer to actual foreground runs.
These outputs join the narrow derived-artifact allowance. Refresh PR test outcomes at the same
source HEAD; source/test repairs require ordinary committed WORK and re-executed tests.
