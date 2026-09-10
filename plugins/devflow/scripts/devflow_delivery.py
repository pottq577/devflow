"""Source-comment evidence and local per-branch delivery artifacts.

All functions inspect files/Git or project prospective metadata. The caller owns the existing
STATE/WORK transaction, so an artifact refusal cannot partially mark a WORK complete.
"""
from __future__ import annotations

import ast
import hashlib
import io
import re
import subprocess
import tokenize
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from devflow_postman import collection_errors, strict_json

PR_TEMPLATE = 'docs/PR/templates.md'
SOURCE_SUFFIXES = {'.java', '.kt', '.kts', '.py', '.pyi', '.js', '.jsx', '.ts', '.tsx', '.mjs', '.cjs',
                   '.go', '.rs', '.c', '.h', '.cpp', '.cc', '.hpp', '.cs', '.swift', '.php', '.rb',
                   '.sh', '.bash', '.zsh', '.sql', '.vue', '.svelte', '.scala', '.groovy', '.ex', '.exs'}
HASH = re.compile(r'[0-9a-f]{64}')
SHA = re.compile(r'[0-9a-f]{40}|[0-9a-f]{64}')
PR_METADATA = re.compile(r'<!--\s*devflow-delivery:\s*(\{.*?\})\s*-->', re.S)


def default_policy() -> dict[str, Any]:
    return {'version': 1, 'grandfathered_work_ids': [], 'branches': {}}


def active(state: dict[str, Any]) -> bool:
    return 'delivery' in state


def git(root: Path, *args: str) -> str:
    result = subprocess.run(['git', *args], cwd=root, text=True, capture_output=True, timeout=20)
    if result.returncode:
        raise ValueError(result.stderr.strip() or f'Git inspection failed: {args[0]}')
    return result.stdout.rstrip('\n')


def resolve_commit(root: Path, ref: Any) -> str:
    if not isinstance(ref, str) or not ref.strip():
        raise ValueError('delivery requires a nonblank source commit/ref')
    value = git(root, 'rev-parse', '--verify', '--end-of-options', ref + '^{commit}')
    if not SHA.fullmatch(value):
        raise ValueError('delivery source ref must resolve to one commit')
    return value


def current_branch(root: Path) -> str:
    branch = git(root, 'symbolic-ref', '--quiet', '--short', 'HEAD')
    if not branch:
        raise ValueError('delivery completion requires a named branch')
    return branch


def slug(value: str) -> str:
    safe = re.sub(r'[^a-z0-9-]+', '-', value.lower()).strip('-')[:64] or 'branch'
    return safe + '-' + hashlib.sha256(value.encode('utf-8')).hexdigest()[:10]


def artifact_paths(domain: str, branch: str) -> dict[str, str]:
    name = slug(branch)
    return {'pr_file': f'docs/PR/{slug(domain)}/{name}.md',
            'postman_file': f'docs/postman/{slug(domain)}/{name}.postman_collection.json'}


def inside(root: Path, value: Any) -> Path:
    if not isinstance(value, str) or not value.strip() or '\\' in value:
        raise ValueError('delivery path must be a nonblank repository-relative POSIX path')
    p = PurePosixPath(value)
    if p.is_absolute() or '..' in p.parts or str(p) != value:
        raise ValueError(f'delivery path must be canonical and repository-relative: {value}')
    target = root / value
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError(f'delivery path escapes the repository: {value}')
    return target


def read_artifact(root: Path, path: str, label: str) -> tuple[str, str]:
    target = inside(root, path)
    if not target.is_file():
        raise ValueError(f'{label} file missing: {path}')
    if target.stat().st_size > 8 * 1024 * 1024:
        raise ValueError(f'{label} exceeds the 8 MiB local artifact limit: {path}')
    data = target.read_bytes()
    return data.decode('utf-8-sig'), hashlib.sha256(data).hexdigest()


def source_changes(root: Path, start: str, head: str) -> list[str]:
    # NUL-separated names preserve spaces and non-ASCII paths without Git's display quoting.
    output = git(root, 'diff', '--no-ext-diff', '--name-only', '-z', '--diff-filter=ACMRT', start, head, '--')
    return [name for name in output.split('\0') if name and Path(name).suffix.lower() in SOURCE_SUFFIXES]


def comment_lines(source: str, suffix: str) -> set[int]:
    """Recognize lexical comment anchors; their domain usefulness remains an audit decision."""
    if suffix in {'.py', '.pyi'}:
        found: set[int] = set()
        try:
            for token in tokenize.generate_tokens(io.StringIO(source).readline):
                if token.type == tokenize.COMMENT and token.string.lstrip('# ').strip() and not token.string.startswith('#!') and not re.match(r'(?:TODO|FIXME|copyright|license)\b', token.string.lstrip('# '), re.I):
                    found.add(token.start[0])
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and ast.get_docstring(node):
                    expr = node.body[0]
                    found.update(range(expr.lineno, expr.end_lineno + 1))
        except (SyntaxError, tokenize.TokenError, IndentationError):
            return set()
        return found
    markers = ('#',) if suffix in {'.rb', '.sh', '.bash', '.zsh', '.ex', '.exs'} else ('--', '/*') if suffix == '.sql' else ('//', '/*', '*', '<!--')
    found = set()
    for num, line in enumerate(source.splitlines(), 1):
        text = line.strip()
        if text.startswith(markers) and not text.startswith(('#!', '*/')):
            body = re.sub(r'^[/*#<!\-\s]+|[/*>\-\s]+$', '', text).strip()
            if body and not re.fullmatch(r'(?:TODO|FIXME|copyright|license).*', body, re.I):
                found.add(num)
    return found


def comment_errors(root: Path, item: dict[str, Any]) -> list[str]:
    evidence = item.get('evidence') or {}
    errors: list[str] = []
    try:
        head = resolve_commit(root, evidence.get('commit'))
        start = resolve_commit(root, evidence.get('start_sha'))
        try:
            ancestor = git(root, 'merge-base', start, head)
        except ValueError:
            ancestor = None
        if ancestor != start:
            raise ValueError('comment start_sha must be an ancestor of the evidence commit')
        changed = set(source_changes(root, start, head))
    except (ValueError, subprocess.TimeoutExpired) as exc:
        return [f'{item.get("id")}: comment source provenance: {exc}']
    anchors = evidence.get('comments', [])
    if not isinstance(anchors, list):
        return [f'{item.get("id")}: evidence.comments must be a list']
    if not changed:
        note = evidence.get('comments_note')
        if not isinstance(note, str) or not note.strip():
            errors.append('comments_note must explain a documentation/config/deletion-only source change')
        return errors
    if not anchors:
        return ['changed executable source requires at least one meaningful evidence.comments anchor']
    for anchor in anchors:
        if not isinstance(anchor, dict):
            errors.append('comment anchor must be a mapping'); continue
        path, line, reason = anchor.get('path'), anchor.get('line'), anchor.get('reason')
        if not isinstance(path, str) or path not in changed:
            errors.append(f'comment anchor must identify changed source: {path}'); continue
        try:
            inside(root, path)
        except ValueError as exc:
            errors.append(str(exc)); continue
        if type(line) is not int or line < 1 or not isinstance(reason, str) or not reason.strip():
            errors.append('comment anchor requires a positive line and a nonblank reason'); continue
        source = git(root, 'show', f'{head}:{path}')
        if line not in comment_lines(source, Path(path).suffix.lower()):
            errors.append(f'comment anchor does not point to a substantive source comment/docstring: {path}:{line}')
    return errors


def metadata_errors(actual: Any, expected: dict[str, str], label: str) -> list[str]:
    if not isinstance(actual, dict):
        return [f'{label} delivery metadata must be an object']
    return [f'{label} metadata {key} must match {value}' for key, value in expected.items() if actual.get(key) != value]


def inspect_artifacts(root: Path, domain: str, branch: str, record: dict[str, Any], sections: Callable) -> dict[str, str]:
    expected_paths = artifact_paths(domain, branch)
    for key, value in expected_paths.items():
        if record.get(key) != value:
            raise ValueError(f'delivery {key} path must be {value}')
    expected = {key: record[key] for key in ('base_sha', 'head_sha')}
    expected['branch'] = branch
    template, template_hash = read_artifact(root, PR_TEMPLATE, 'PR template')
    pr, pr_hash = read_artifact(root, expected_paths['pr_file'], 'PR')
    postman, postman_hash = read_artifact(root, expected_paths['postman_file'], 'Postman')
    errors: list[str] = []
    matches = PR_METADATA.findall(pr)
    if len(matches) != 1:
        errors.append('PR requires exactly one <!-- devflow-delivery: {metadata} --> comment')
    else:
        errors.extend(metadata_errors(strict_json(matches[0]), expected, 'PR'))
    # The exact ordered headings are the consuming team's format contract, including repeats.
    template_headings = [(level, title) for level, title, _ in sections(template)]
    pr_headings = [(level, title) for level, title, _ in sections(pr)]
    if template_headings != pr_headings:
        errors.append('PR heading order/text must match docs/PR/templates.md')
    strip_comments = lambda text: re.sub(r'<!--.*?-->', '', text, flags=re.S).strip()
    visible = strip_comments(pr)
    if not visible or visible == strip_comments(template):
        errors.append('PR body must contain implemented changes and verification, beyond the input template')
    for _, title, body in sections(pr):
        content = strip_comments(body)
        if not re.sub(r'[\s#*\-\[\]>]+', '', content):
            errors.append(f'PR section needs content or an explained N/A: {title}')
    collection = strict_json(postman)
    info = collection.get('info') if isinstance(collection, dict) else None
    errors.extend(metadata_errors(info.get('_devflow') if isinstance(info, dict) else None, expected, 'Postman'))
    errors.extend(collection_errors(collection, record.get('api_endpoints'), record.get('api_note')))
    if errors:
        raise ValueError('; '.join(errors))
    return {'template_sha256': template_hash, 'pr_sha256': pr_hash, 'postman_sha256': postman_hash}


def prepare_completion(root: Path, domain: str, state: dict[str, Any], item: dict[str, Any], sections: Callable, base_ref: str | None = None) -> None:
    """Apply provenance to prospective objects only; the caller validates and writes them atomically."""
    if not active(state):
        return
    evidence = item.setdefault('evidence', {})
    head = resolve_commit(root, evidence.get('commit'))
    if head != resolve_commit(root, 'HEAD'):
        raise ValueError('delivery evidence.commit must identify current HEAD')
    branch = current_branch(root)
    # Uncommitted implementation must never be masked by valid evidence for an older HEAD.
    dirty = git(root, 'diff', '--no-ext-diff', '--name-only', '-z', 'HEAD', '--')
    untracked = git(root, 'ls-files', '--others', '--exclude-standard', '-z')
    pending = [p for p in (dirty + '\0' + untracked).split('\0') if p and Path(p).suffix.lower() in SOURCE_SUFFIXES]
    if pending:
        raise ValueError('uncommitted source changes require review/commit before delivery: ' + ', '.join(pending))
    policy = state['delivery']
    if not isinstance(policy, dict) or not isinstance(policy.get('branches'), dict):
        raise ValueError('delivery policy/branches must be mappings')
    supplied = evidence.get('delivery')
    if not isinstance(supplied, dict):
        raise ValueError('work done requires evidence.delivery with base_ref, PR/Postman paths and API assessment')
    previous = policy['branches'].get(branch) or {}
    ref = supplied.get('base_ref') or previous.get('base_ref') or base_ref
    if not isinstance(ref, str) or not ref.strip():
        raise ValueError('delivery base_ref requires the actual PR parent name')
    # Preserve an explicit branch baseline across cumulative updates, even if the parent advances.
    pinned = supplied.get('base_sha') or (previous.get('base_sha') if previous.get('base_ref') == ref else None)
    base = resolve_commit(root, pinned or ref)
    evidence['commit'] = head
    if not evidence.get('start_sha'):
        # Adoption during an in-progress WORK uses the domain's conservative source baseline.
        evidence['start_sha'] = state.get('baseline_sha')
    errors = comment_errors(root, item)
    if errors:
        raise ValueError('; '.join(errors))
    changes = git(root, 'diff', '--no-ext-diff', '--name-only', '-z', evidence['start_sha'], head, '--')
    evidence['changed_files'] = [name for name in changes.split('\0') if name]
    record = {key: supplied.get(key) for key in ('pr_file', 'postman_file', 'api_endpoints', 'api_note')}
    record.update(base_ref=ref, base_sha=base, head_sha=head)
    record.update(inspect_artifacts(root, domain, branch, record, sections))
    ids = list(previous.get('work_ids', []))
    if item['id'] not in ids:
        ids.append(item['id'])
    record['work_ids'] = ids
    evidence['delivery'] = dict(record, branch=branch)
    policy['branches'][branch] = record


def validation_errors(root: Path, domain: str, state: dict[str, Any], docs: dict[Path, dict[str, Any]], sections: Callable, *, final: bool = False) -> list[str]:
    if not active(state):
        return []
    policy = state.get('delivery')
    if not isinstance(policy, dict) or type(policy.get('version')) is not int or policy.get('version') != 1:
        return ['delivery must be a mapping with version: 1']
    grandfathered = policy.get('grandfathered_work_ids')
    branches = policy.get('branches')
    if not isinstance(grandfathered, list) or any(not isinstance(i, str) for i in grandfathered):
        return ['delivery.grandfathered_work_ids must be a list of WORK ids']
    if len(grandfathered) != len(set(grandfathered)):
        return ['delivery.grandfathered_work_ids must be unique']
    if not isinstance(branches, dict):
        return ['delivery.branches must be a mapping']
    index = {item['id']: item for doc in docs.values() for item in doc.get('items', []) if isinstance(item, dict) and 'id' in item}
    errors: list[str] = []
    for item_id in grandfathered:
        if item_id not in index or index[item_id].get('status') != 'done':
            errors.append(f'delivery grandfathered WORK must exist and remain done: {item_id}')
    expected_ids: dict[str, set[str]] = {}
    for item_id, item in index.items():
        if item.get('status') != 'done' or item_id in grandfathered:
            continue
        ev = item.get('evidence') or {}
        data = ev.get('delivery')
        if not isinstance(data, dict) or not isinstance(data.get('branch'), str):
            errors.append(f'{item_id}: done requires evidence.delivery provenance'); continue
        branch = data['branch']
        expected_ids.setdefault(branch, set()).add(item_id)
        if branch not in branches:
            errors.append(f'{item_id}: delivery branch record is missing: {branch}')
        if data.get('head_sha') != ev.get('commit'):
            errors.append(f'{item_id}: delivery head_sha and evidence.commit differ')
        errors.extend(f'{item_id}: {error}' for error in comment_errors(root, item))
    for branch, record in branches.items():
        try:
            if not isinstance(branch, str) or not branch or not isinstance(record, dict):
                raise ValueError('delivery branch records require nonblank names and mappings')
            for key in ('base_ref', 'base_sha', 'head_sha', 'pr_file', 'postman_file', 'template_sha256', 'pr_sha256', 'postman_sha256'):
                if not isinstance(record.get(key), str) or not record[key].strip():
                    raise ValueError(f'delivery branch {branch} requires {key}')
            for key in ('base_sha', 'head_sha'):
                if not SHA.fullmatch(record[key]) or resolve_commit(root, record[key]) != record[key]:
                    raise ValueError(f'delivery {key} must be a full existing source commit')
            ids = record.get('work_ids')
            if not isinstance(ids, list) or not ids or any(not isinstance(i, str) for i in ids) or len(ids) != len(set(ids)):
                raise ValueError(f'delivery branch {branch} requires unique work_ids')
            if set(ids) != expected_ids.get(branch, set()):
                raise ValueError(f'delivery branch {branch} work_ids disagree with done WORK evidence')
            if (index[ids[-1]].get('evidence') or {}).get('commit') != record['head_sha']:
                raise ValueError(f'delivery branch {branch} head_sha must match its latest recorded WORK')
            hashes = inspect_artifacts(root, domain, branch, record, sections)
            for key, value in hashes.items():
                if not HASH.fullmatch(record[key]) or record[key] != value:
                    errors.append(f'delivery {branch} stale {key}; regenerate artifacts and run delivery refresh')
            if final:
                ref = 'refs/heads/' + branch
                try:
                    tip = resolve_commit(root, ref)
                except ValueError:
                    # A deleted, already-merged local branch still has its pinned source provenance.
                    tip = record['head_sha']
                if tip != record['head_sha']:
                    errors.append(f'delivery branch tip advanced beyond delivered WORK: {branch}')
        except (ValueError, KeyError, TypeError, OSError, subprocess.TimeoutExpired) as exc:
            errors.append(f'delivery {branch}: {exc}')
    return errors


def refresh_artifacts(root: Path, domain: str, state: dict[str, Any], branch: str, sections: Callable) -> None:
    policy = state.get('delivery') or {}
    record = (policy.get('branches') or {}).get(branch)
    if not isinstance(record, dict):
        raise ValueError(f'delivery branch has no completed WORK record: {branch}')
    if resolve_commit(root, 'refs/heads/' + branch) != record.get('head_sha'):
        raise ValueError('delivery refresh requires the recorded branch tip; new source changes require WORK evidence')
    record.update(inspect_artifacts(root, domain, branch, record, sections))
