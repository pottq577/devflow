"""Whole-domain explanation receipts and executed-delivery evidence.

The Executor authors HTML through the installed eli5 skill. These functions verify provenance;
they never claim that reading a SKILL.md alone proves semantic compliance with that skill.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import yaml
import devflow_delivery as delivery
from devflow_postman import strict_json

FINAL_VERSION = 1
TERMINAL = {'done', 'cancelled', 'transferred'}
RUN_STATUSES = {'passed', 'failed', 'blocked', 'not_applicable'}
CLASSIFICATIONS = {'code', 'collection', 'environment', 'unknown'}
HTML_META = re.compile(r'<!--\s*devflow-explanation:\s*(\{.*?\})\s*-->', re.S)


def default_policy() -> dict[str, Any]:
    return {'version': FINAL_VERSION, 'runs': [], 'diagnoses': {}, 'explanation': None}


def active(state: dict[str, Any]) -> bool:
    policy = state.get('delivery')
    return isinstance(policy, dict) and 'finalization' in policy


def policy(state: dict[str, Any]) -> dict[str, Any]:
    if not active(state):
        raise ValueError('Whole-work finalization requires devflow delivery enable <domain>')
    value = state['delivery']['finalization']
    if not isinstance(value, dict) or type(value.get('version')) is not int or value.get('version') != FINAL_VERSION:
        raise ValueError('delivery.finalization must be a mapping with version: 1')
    if not isinstance(value.get('runs'), list) or not isinstance(value.get('diagnoses'), dict):
        raise ValueError('delivery.finalization requires runs list and diagnoses mapping')
    return value


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def html_path(domain: str) -> str:
    return f'docs/explanations/{delivery.slug(domain)}/implementation.html'


def work_index(docs: dict[Path, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(i['id']): i for doc in docs.values() for i in doc.get('items', []) if isinstance(i, dict) and 'id' in i}


def scope(root: Path, domain: str, state: dict[str, Any], docs: dict[Path, dict[str, Any]], domain_path: Path) -> dict[str, Any]:
    """Pin all WORK and branch records. HEAD alone never defines an explanation's scope."""
    works = []
    for path, doc in sorted(docs.items(), key=lambda entry: str(entry[0])):
        for item in doc.get('items', []):
            ev = item.get('evidence') or {}
            works.append({'id': item['id'], 'status': item.get('status'), 'phase': str(doc.get('phase')),
                          'objective': item.get('objective'), 'origin': item.get('origin'),
                          'commit': ev.get('commit'), 'changed_files': ev.get('changed_files', []),
                          'commands': ev.get('commands', []), 'deviations': ev.get('deviations', []),
                          'transfer': item.get('transfer'), 'work_file': str(path.relative_to(root))})
    branches = (state.get('delivery') or {}).get('branches', {})
    sources = {}
    for name in ('PRD.md', 'PLAN.md', 'DECISIONS.md'):
        path = domain_path / name
        sources[name] = {'file': str(path.relative_to(root)),
                         'sha256': hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None}
    fin = policy(state)
    # Exclude volatile STATE projections, audit status and the explanation itself from this hash.
    # A new run, repaired WORK, changed PR, or changed collection invalidates the old explanation.
    snapshot = {'domain': domain, 'baseline_sha': state.get('baseline_sha'), 'sources': sources,
                'works': sorted(works, key=lambda row: row['id']), 'branches': branches,
                'newman_runs': fin['runs'], 'diagnoses': fin['diagnoses']}
    metadata = {'domain': domain, 'scope_sha256': digest(snapshot),
                'work_ids': sorted(row['id'] for row in works), 'branches': sorted(branches)}
    return {'scope': snapshot, 'html_file': html_path(domain), 'html_metadata': metadata}


class ExplanationHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: set[str] = set()
        self.visible: list[str] = []
        self.hidden = 0
        self.errors: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.add(tag)
        values = dict(attrs)
        if tag in {'script', 'style'}:
            self.hidden += 1
        if tag in {'iframe', 'object', 'embed', 'base'}:
            self.errors.append(f'explanation HTML cannot embed {tag}')
        if 'src' in values and not str(values['src']).startswith('data:'):
            self.errors.append('explanation HTML must embed its assets (no external src)')
        if tag == 'link' and values.get('rel') == 'stylesheet':
            self.errors.append('explanation HTML must inline its stylesheet')

    def handle_endtag(self, tag: str) -> None:
        if tag in {'script', 'style'}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.visible.append(data)


def inspect_html(root: Path, ctx: dict[str, Any]) -> str:
    text, sha = delivery.read_artifact(root, ctx['html_file'], 'ELI5 explanation')
    matches = HTML_META.findall(text)
    if len(matches) != 1:
        raise ValueError('explanation requires one devflow-explanation metadata comment')
    actual = strict_json(matches[0])
    errors = delivery.metadata_errors(actual, ctx['html_metadata'], 'explanation')
    parsed = ExplanationHTML(); parsed.feed(text); parsed.close()
    if not {'html', 'head', 'title', 'body'}.issubset(parsed.tags):
        errors.append('explanation must be a complete HTML document with title and body')
    visible = ' '.join(parsed.visible)
    if len(visible.strip()) < 100:
        errors.append('explanation requires substantive visible explanation content')
    for item_id in ctx['html_metadata']['work_ids']:
        if item_id not in visible:
            errors.append(f'explanation visible WORK coverage is missing: {item_id}')
    errors.extend(parsed.errors)
    if errors:
        raise ValueError('; '.join(errors))
    return sha


def resolve_skill(root: Path, supplied: str | None) -> tuple[Path, str]:
    """Use host discovery first (explicit path); standard and legacy paths are only fallbacks."""
    home = Path.home()
    candidates = [Path(supplied).expanduser()] if supplied else [
        root / '.agents/skills/eli5/SKILL.md', home / '.agents/skills/eli5/SKILL.md',
        Path(os.environ.get('CODEX_HOME', str(home / '.codex'))) / 'skills/eli5/SKILL.md',
        root / '.codex/skills/eli5/SKILL.md',
    ]
    for path in candidates:
        if not path.is_file():
            continue
        if path.stat().st_size > 1024 * 1024:
            raise ValueError('eli5 SKILL.md exceeds 1 MiB')
        data = path.read_bytes(); text = data.decode('utf-8-sig')
        parts = re.split(r'^---\s*$', text, maxsplit=2, flags=re.M)
        meta = yaml.safe_load(parts[1]) if len(parts) == 3 and not parts[0].strip() else None
        if not isinstance(meta, dict) or meta.get('name') != 'eli5':
            raise ValueError('selected SKILL.md must declare name: eli5')
        return path.resolve(), hashlib.sha256(data).hexdigest()
    raise ValueError('installed eli5 SKILL.md is unavailable; use host skill discovery and --skill-file <actual path>')


def record_explanation(root: Path, ctx: dict[str, Any], state: dict[str, Any], skill_file: str | None, invocation: str) -> None:
    skill, skill_hash = resolve_skill(root, skill_file)
    if not isinstance(invocation, str) or not invocation.strip():
        raise ValueError('explanation requires actual eli5 invocation evidence')
    sha = inspect_html(root, ctx)
    policy(state)['explanation'] = {'html_file': ctx['html_file'], 'html_sha256': sha,
                                   'scope_sha256': ctx['html_metadata']['scope_sha256'],
                                   'skill_name': 'eli5', 'skill_file': str(skill), 'skill_sha256': skill_hash,
                                   'invocation': invocation.strip()}
    policy(state).pop('receipt', None)


def structural_errors(state: dict[str, Any]) -> list[str]:
    if not active(state):
        return []
    try:
        fin = policy(state)
        ids = set()
        for run in fin['runs']:
            if not isinstance(run, dict) or not isinstance(run.get('id'), str) or not run['id'] or run['id'] in ids:
                raise ValueError('finalization run ids must be unique nonblank strings')
            ids.add(run['id'])
            if run.get('status') not in RUN_STATUSES:
                raise ValueError('finalization run status is invalid')
            for key in ('branch', 'source_sha', 'collection_sha256', 'summary_file', 'summary_sha256'):
                if not isinstance(run.get(key), str) or not run[key]:
                    raise ValueError(f'finalization run requires {key}')
        for field in ('explanation', 'receipt'):
            if fin.get(field) is not None and not isinstance(fin[field], dict):
                raise ValueError(f'finalization {field} must be a mapping or null')
        for run_id, value in fin['diagnoses'].items():
            if run_id not in ids or not isinstance(value, dict) or value.get('classification') not in CLASSIFICATIONS:
                raise ValueError('finalization diagnosis must reference an existing run and known classification')
            if not isinstance(value.get('reason'), str) or len(value['reason'].strip()) < 20:
                raise ValueError('finalization diagnosis needs evidence-based reason')
            if value['classification'] in {'code', 'collection'} and not isinstance(value.get('work_id'), str):
                raise ValueError('code/collection diagnosis requires a repair WORK id')
        return []
    except (ValueError, TypeError) as exc:
        return [str(exc)]


def repair_ids(state: dict[str, Any]) -> list[str]:
    return list(dict.fromkeys(d['work_id'] for d in policy(state)['diagnoses'].values()
                             if d.get('classification') in {'code', 'collection'} and d.get('work_id')))


def triage(state: dict[str, Any], docs: dict[Path, dict[str, Any]], run_id: str, classification: str,
           reason: str, item_id: str | None) -> None:
    fin = policy(state)
    run = next((value for value in fin['runs'] if value['id'] == run_id), None)
    if not run or run['status'] not in {'failed', 'blocked'}:
        raise ValueError('triage requires an existing unsuccessful Newman run')
    if classification not in CLASSIFICATIONS or not isinstance(reason, str) or len(reason.strip()) < 20:
        raise ValueError('triage needs a classification and evidence-based contract/reproduction reason')
    if classification in {'code', 'collection'}:
        index = work_index(docs); item = index.get(item_id or '')
        if not item or item.get('kind') != 'remediation' or item.get('status') not in {'ready', 'in_progress', 'done'}:
            raise ValueError('code/collection triage requires a real remediation WORK via --work-id')
        owner = next(doc for doc in docs.values() if item in doc.get('items', []))
        if str(owner.get('phase')) != 'integration':
            raise ValueError('finalization repair WORK must belong to integration')
        if 'NEWMAN-' + run_id not in (item.get('origin') or {}).get('findings', []):
            raise ValueError('repair WORK origin.findings must contain NEWMAN-' + run_id)
        if run['summary_file'] not in item.get('references', []):
            raise ValueError('repair WORK references must include the failing Newman summary path')
        if not (item.get('scope') or {}).get('allowed'):
            raise ValueError('repair WORK needs a bounded scope.allowed')
    elif item_id:
        raise ValueError('environment/unknown triage records no speculative code repair WORK')
    fin['diagnoses'][run_id] = {'classification': classification, 'reason': reason.strip(), 'work_id': item_id}
    fin.pop('receipt', None)


def registered_findings(state: dict[str, Any], item: dict[str, Any]) -> set[str]:
    """Authenticate Newman origins for this exact WORK without relaxing ordinary audit links."""
    if not active(state) or structural_errors(state):
        return set()
    fin = policy(state)
    result: set[str] = set()
    for run in fin['runs']:
        diagnosis = fin['diagnoses'].get(run['id'], {})
        if (run['status'] in {'failed', 'blocked'}
                and diagnosis.get('classification') in {'code', 'collection'}
                and diagnosis.get('work_id') == item.get('id')
                and item.get('kind') == 'remediation'
                and run['summary_file'] in item.get('references', [])):
            result.add('NEWMAN-' + run['id'])
    return result


def final_errors(root: Path, domain: str, state: dict[str, Any], docs: dict[Path, dict[str, Any]],
                 domain_path: Path, *, require_receipt: bool = False) -> list[str]:
    if not active(state):
        return []
    errors = structural_errors(state)
    if errors:
        return errors
    fin = policy(state); ctx = scope(root, domain, state, docs, domain_path); index = work_index(docs)
    for item_id, item in index.items():
        if item.get('status') not in TERMINAL:
            errors.append(f'whole-work finalization has open WORK: {item_id}')
    explanation = fin.get('explanation')
    if not isinstance(explanation, dict):
        errors.append('ELI5 explanation evidence is missing')
    else:
        try:
            sha = inspect_html(root, ctx)
            if explanation.get('html_file') != ctx['html_file'] or explanation.get('html_sha256') != sha:
                errors.append('ELI5 explanation content is stale; regenerate and record explain')
            if explanation.get('scope_sha256') != ctx['html_metadata']['scope_sha256']:
                errors.append('ELI5 explanation scope is stale after work/artifact/Newman changes')
            if explanation.get('skill_name') != 'eli5' or not delivery.HASH.fullmatch(str(explanation.get('skill_sha256', ''))):
                errors.append('ELI5 explanation requires installed-skill provenance')
            if not str(explanation.get('invocation') or '').strip():
                errors.append('ELI5 explanation invocation evidence is missing')
        except (ValueError, OSError) as exc:
            errors.append('ELI5 explanation stale or invalid: ' + str(exc))
    latest = {run['branch']: run for run in fin['runs']}
    branches = state['delivery'].get('branches', {})
    for branch, record in branches.items():
        # A completed receipt stays conditional on the files and extant branch tips it describes.
        try:
            try:
                tip = delivery.resolve_commit(root, 'refs/heads/' + branch)
            except ValueError:
                tip = record['head_sha']  # Deleted/merged branches retain immutable provenance.
            if tip != record['head_sha']:
                errors.append('delivery branch tip advanced beyond delivered WORK: ' + branch)
            for path_key, hash_key in [('pr_file', 'pr_sha256'), ('postman_file', 'postman_sha256')]:
                _, actual = delivery.read_artifact(root, record[path_key], path_key)
                if actual != record[hash_key]:
                    errors.append('delivery artifact changed after finalization: ' + record[path_key])
            _, template_hash = delivery.read_artifact(root, delivery.PR_TEMPLATE, 'PR template')
            if template_hash != record['template_sha256']:
                errors.append('PR template changed after finalization')
        except (ValueError, OSError, KeyError, TypeError) as exc:
            errors.append(str(exc))
        run = latest.get(branch)
        if not run:
            errors.append(f'Newman execution evidence missing for branch: {branch}'); continue
        if run['status'] not in {'passed', 'not_applicable'}:
            errors.append(f'Newman branch requires successful rerun: {branch}')
        if run['source_sha'] != record['head_sha'] or run['collection_sha256'] != record['postman_sha256']:
            errors.append(f'Newman execution is stale for source/collection: {branch}')
        if run['status'] == 'not_applicable' and record.get('api_endpoints'):
            errors.append(f'Newman N/A requires an empty no-HTTP collection: {branch}')
    for run in fin['runs']:
        try:
            text, sha = delivery.read_artifact(root, run['summary_file'], 'Newman sanitized summary')
            if sha != run['summary_sha256']:
                errors.append('Newman summary content hash changed: ' + run['id'])
            summary = strict_json(text)
            if not isinstance(summary, dict):
                raise ValueError('Newman sanitized summary must be a JSON object')
            for key in ('id', 'status', 'branch', 'source_sha', 'collection_sha256', 'exit_code', 'counts', 'server_sha', 'newman_version', 'raw_file', 'raw_sha256', 'reason_codes'):
                if summary.get(key) != run.get(key):
                    errors.append(f'Newman summary and STATE disagree on {key}: {run["id"]}')
        except (ValueError, OSError) as exc:
            errors.append(str(exc))
        if run.get('raw_sha256'):
            try:
                raw = delivery.inside(root, run.get('raw_file'))
                if not str(run['raw_file']).startswith('.devflow/private/newman/') or not raw.is_file() or raw.stat().st_size > 32 * 1024 * 1024:
                    raise ValueError('Newman raw report is missing or outside its private location')
                if hashlib.sha256(raw.read_bytes()).hexdigest() != run['raw_sha256']:
                    errors.append('Newman raw report hash changed: ' + run['id'])
            except (ValueError, OSError) as exc:
                errors.append(str(exc))
        elif run['status'] == 'passed':
            errors.append('Newman passed evidence requires its private raw report hash')
        if run['status'] not in {'failed', 'blocked'}:
            continue
        diagnosis = fin['diagnoses'].get(run['id'])
        if not diagnosis or diagnosis.get('classification') == 'unknown':
            errors.append('Newman failure requires evidence-based triage: ' + run['id']); continue
        subsequent = latest.get(run['branch'])
        if not subsequent or subsequent['id'] == run['id'] or subsequent['status'] not in {'passed', 'not_applicable'}:
            errors.append('triaged failure requires a later successful Newman run: ' + run['id'])
        if diagnosis['classification'] in {'code', 'collection'}:
            item = index.get(diagnosis.get('work_id'))
            if not item or item.get('status') != 'done':
                errors.append('Newman defect requires completed repair WORK: ' + run['id']); continue
            ev = item.get('evidence') or {}
            try:
                commit = delivery.resolve_commit(root, ev.get('commit'))
                if commit == run['source_sha'] or not delivery.git(root, 'diff', '--name-only', run['source_sha'], commit, '--'):
                    errors.append('Newman repair requires a real source/test commit: ' + run['id'])
                if not ev.get('commands'):
                    errors.append('Newman repair WORK requires executed regression evidence')
                if 'NEWMAN-' + run['id'] not in (item.get('origin') or {}).get('findings', []) or run['summary_file'] not in item.get('references', []):
                    errors.append('Newman repair WORK lost its failure traceability')
                if subsequent and subsequent['status'] == 'passed':
                    server = delivery.resolve_commit(root, subsequent.get('server_sha'))
                    if delivery.git(root, 'merge-base', commit, server) != commit:
                        errors.append('successful Newman server must include the repair commit')
            except ValueError as exc:
                errors.append(str(exc))
    if require_receipt:
        receipt = fin.get('receipt')
        if not isinstance(receipt, dict) or receipt.get('scope_sha256') != ctx['html_metadata']['scope_sha256'] or receipt.get('html_sha256') != (explanation or {}).get('html_sha256'):
            errors.append('whole-work finalization receipt missing or stale; run delivery finalize')
    return errors
