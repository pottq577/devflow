# DevFlow Plugin

DevFlow is a state-based development protocol for agentic coding workflows.

It keeps product/domain intent in PRD, repository implementation intent in PLAN, executable changes in WORK, independent review in AUDIT, and lifecycle position in STATE. The protocol is derived from the bundled `core/references/vibecoder.md` SSOT.

## Commands / skills

- Plan: repository-grounded architecture and WORK generation.
- Run: exactly one ready WORK item.
- Audit: plan, phase, integration, and closure reviews.
- Status: deterministic next-action reconstruction.

## Runtime dependency

Python 3.10+ and PyYAML 6.x:

```bash
python3 -m pip install -r requirements.txt
```

## Project artifacts

```text
.devflow/config.yaml
docs/domains/<domain>/
├── PRD.md
├── PLAN.md
├── STATE.yaml
├── DECISIONS.md
├── work/
└── audits/
```

Initialize a domain with the platform skill or directly with `python3 scripts/devflow.py init <domain> --prd <path>`.
