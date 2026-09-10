"""One foreground Newman run with bounded execution and private raw diagnostics.

A successful process exit alone is insufficient: every collection request must actually execute,
return a response and exercise non-skipped assertions. Raw payloads stay outside shared artifacts.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import ipaddress
import json
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import devflow_delivery as delivery
import devflow_finalization as finalization
from devflow_postman import strict_json


SKIP_OR_EXTRA_REQUEST = re.compile(r'\b(?:pm\s*\.\s*sendRequest|pm\s*\.\s*execution\s*\.\s*(?:skipRequest|runRequest|setNextRequest)|postman\s*\.\s*setNextRequest)\s*\(')
BASE_MUTATION = re.compile(r'\bpm\s*\.\s*(?:environment|variables|collectionVariables|globals)\s*\.\s*(?:set|unset|clear)\s*\([^)]*[\'"]baseUrl[\'"]')


def leaves(collection: dict[str, Any]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    def visit(node: dict[str, Any]) -> None:
        for item in node.get('item', []):
            if 'request' in item:
                found.append(item)
            else:
                visit(item)
    visit(collection)
    return found


def scripts(collection: dict[str, Any]) -> list[str]:
    result: list[str] = []
    def visit(node: dict[str, Any]) -> None:
        for event in node.get('event', []):
            body = event.get('script', {}).get('exec', [])
            result.append(body if isinstance(body, str) else '\n'.join(body))
        for item in node.get('item', []):
            visit(item)
    visit(collection)
    return result


def check_target(url: str | None, allow_hosts: list[str], safety_note: str | None) -> str:
    if not isinstance(safety_note, str) or len(safety_note.strip()) < 20:
        raise ValueError('Newman requires --safety-note documenting test data, build identity and isolated integrations')
    if not isinstance(url, str) or not url.strip():
        raise ValueError('Newman requires --base-url for the verified local/test environment')
    parsed = urlsplit(url)
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError('Newman target port is invalid') from exc
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Newman target must be an HTTP(S) URL without credentials, query or fragment')
    host = parsed.hostname.lower()
    try:
        local = ipaddress.ip_address(host).is_loopback
    except ValueError:
        local = host == 'localhost'
    if not local and host not in allow_hosts:
        raise ValueError('remote test host requires explicit --allow-host with the exact approved hostname')
    return url.rstrip('/')


def prepare_private_dir(root: Path, run_id: str) -> Path:
    relative = f'.devflow/private/newman/{run_id}'
    target = delivery.inside(root, relative)
    for part in (root / '.devflow', root / '.devflow/private', root / '.devflow/private/newman', target):
        if part.is_symlink():
            raise ValueError('private Newman paths must use real directories, not symlinks')
    if delivery.git(root, 'ls-files', '--', '.devflow/private'):
        raise ValueError('private Newman directory contains tracked files; keep raw diagnostics local')
    exclude_name = delivery.git(root, 'rev-parse', '--git-path', 'info/exclude')
    exclude = Path(exclude_name) if Path(exclude_name).is_absolute() else root / exclude_name
    exclude.parent.mkdir(parents=True, exist_ok=True)
    text = exclude.read_text() if exclude.exists() else ''
    if '/.devflow/private/' not in text.splitlines():
        with exclude.open('a') as stream:
            stream.write('\n/.devflow/private/\n')
    target.mkdir(parents=True, exist_ok=False)
    for folder in [root / '.devflow/private', root / '.devflow/private/newman', target]:
        folder.chmod(0o700)
    return target


def write_private(path: Path, data: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        stream.write(data)


def environment_values(path: str | None, base_url: str) -> dict[str, Any]:
    values: dict[str, Any] = {}
    if path:
        source = Path(path).expanduser()
        if not source.is_file() or source.stat().st_size > 8 * 1024 * 1024:
            raise ValueError('Newman environment must be a local JSON file below 8 MiB')
        env = strict_json(source.read_text(encoding='utf-8-sig'))
        if not isinstance(env, dict) or not isinstance(env.get('values'), list):
            raise ValueError('Postman environment requires a values list')
        for value in env['values']:
            if not isinstance(value, dict) or not isinstance(value.get('key'), str):
                raise ValueError('Postman environment variable entry is invalid')
            if value.get('enabled') is False:
                continue
            if value['key'] in values:
                raise ValueError('Postman environment has duplicate enabled variable keys')
            values[value['key']] = value.get('value', '')
    values['baseUrl'] = base_url
    return {'name': 'DevFlow private test environment', 'values': [
        {'key': key, 'value': value, 'enabled': True} for key, value in values.items()]}


def summarize(report: Any, expected: int, exit_code: int) -> tuple[str, dict[str, int], list[str]]:
    counts = {'expected_requests': expected, 'requests': 0, 'request_failures': 0,
              'assertions': 0, 'assertion_failures': 0, 'skipped_assertions': 0}
    reasons: list[str] = []
    if not isinstance(report, dict) or not isinstance(report.get('run'), dict):
        return 'blocked', counts, ['report_unavailable']
    run = report['run']; stats = run.get('stats', {})
    for destination, category, metric in [('requests', 'requests', 'total'), ('request_failures', 'requests', 'failed'),
                                         ('assertions', 'assertions', 'total'), ('assertion_failures', 'assertions', 'failed'),
                                         ('skipped_assertions', 'assertions', 'pending')]:
        group = stats.get(category, {}) if isinstance(stats, dict) else {}
        value = group.get(metric, 0) if isinstance(group, dict) else None
        if type(value) is not int or value < 0:
            reasons.append('invalid_stats')
        else:
            counts[destination] = value
    executions = run.get('executions')
    if not isinstance(executions, list):
        executions = []; reasons.append('missing_executions')
    if counts['requests'] != expected or len(executions) != expected:
        reasons.append('request_coverage_mismatch')
    if expected and counts['assertions'] < expected:
        reasons.append('missing_assertions')
    for execution in executions:
        if not isinstance(execution, dict):
            reasons.append('invalid_execution'); continue
        response = execution.get('response')
        if not isinstance(response, dict) or type(response.get('code')) is not int:
            reasons.append('missing_response')
        assertions = execution.get('assertions')
        if not isinstance(assertions, list) or not assertions:
            reasons.append('request_without_assertion'); continue
        for assertion in assertions:
            if not isinstance(assertion, dict) or assertion.get('skipped') or assertion.get('error'):
                reasons.append('unsuccessful_assertion')
    if exit_code != 0:
        reasons.append('nonzero_exit')
    if run.get('failures') or counts['request_failures'] or counts['assertion_failures'] or counts['skipped_assertions']:
        reasons.append('run_failures')
    return ('failed' if reasons else 'passed'), counts, sorted(set(reasons))


def execute(root: Path, domain: str, state: dict[str, Any], args: Any, sections: Any) -> dict[str, Any]:
    finalization.policy(state)
    branch = args.branch
    record = state['delivery'].get('branches', {}).get(branch)
    if not isinstance(record, dict):
        raise ValueError('Newman requires a recorded delivery branch')
    hashes = delivery.inspect_artifacts(root, domain, branch, record, sections)
    if any(record.get(key) != value for key, value in hashes.items()):
        raise ValueError('branch artifacts are stale; use delivery refresh before Newman')
    text, _ = delivery.read_artifact(root, record['postman_file'], 'Postman')
    collection = strict_json(text); requests = leaves(collection)
    run_id = uuid.uuid4().hex
    timestamp = dt.datetime.now(dt.timezone.utc).isoformat()
    result = {'id': run_id, 'branch': branch, 'source_sha': record['head_sha'],
              'collection_sha256': record['postman_sha256'], 'recorded_at': timestamp,
              'exit_code': None, 'status': 'not_applicable', 'counts': {'expected_requests': 0,
                  'requests': 0, 'request_failures': 0, 'assertions': 0, 'assertion_failures': 0, 'skipped_assertions': 0},
              'reason_codes': ['no_http_surface'], 'server_sha': None, 'newman_version': None,
              'raw_file': None, 'raw_sha256': None}
    if requests:
        base_url = check_target(args.base_url, args.allow_host, args.safety_note)
        server_sha = delivery.resolve_commit(root, args.server_sha)
        if delivery.git(root, 'merge-base', record['head_sha'], server_sha) != record['head_sha']:
            raise ValueError('Newman server source must contain the collection source commit')
        if server_sha != delivery.resolve_commit(root, 'HEAD'):
            raise ValueError('Newman server source must match the verified current workspace HEAD')
        dirty = delivery.git(root, 'diff', '--name-only', '-z', 'HEAD', '--')
        untracked = delivery.git(root, 'ls-files', '--others', '--exclude-standard', '-z')
        if any(Path(p).suffix.lower() in delivery.SOURCE_SUFFIXES for p in (dirty + '\0' + untracked).split('\0') if p):
            raise ValueError('Newman requires committed source/tests matching the server build')
        if any(item['request']['method'].upper() not in {'GET', 'HEAD', 'OPTIONS'} for item in requests) and not args.allow_writes:
            raise ValueError('write scenarios require --allow-writes after test fixture/integration isolation review')
        for source in scripts(collection):
            if SKIP_OR_EXTRA_REQUEST.search(source) or BASE_MUTATION.search(source):
                raise ValueError('Newman bounded profile requires explicit ordered requests and immutable baseUrl; remove extra/skip/loop requests')
        env = environment_values(args.environment, base_url)
        private = prepare_private_dir(root, run_id)
        env_file = private / 'environment.json'; write_private(env_file, json.dumps(env))
        raw_file = private / 'report.json'; output_file = private / 'output.log'
        snapshot_file = private / 'collection.json'; write_private(snapshot_file, text)
        result.update(server_sha=server_sha, safety_note=args.safety_note.strip(), raw_file=str(raw_file.relative_to(root)))
        executable = shutil.which(args.newman_bin or 'newman')
        exit_code = 127; report: Any = None
        try:
            if executable:
                version = subprocess.run([executable, '--version'], cwd=root, capture_output=True, text=True, timeout=10)
                if version.returncode == 0 and re.fullmatch(r'\d+\.\d+\.\d+(?:[-+][\w.-]+)?', version.stdout.strip()):
                    result['newman_version'] = version.stdout.strip()
                command = [executable, 'run', str(snapshot_file),
                           '--environment', str(env_file), '--reporters', 'json', '--reporter-json-export', str(raw_file),
                           '--timeout', str(args.timeout * 1000), '--timeout-request', str(args.request_timeout * 1000),
                           '--timeout-script', '5000', '--ignore-redirects', '--no-insecure-file-read',
                           '--working-dir', str(private)]
                # Credentials travel in a 0600 environment file, never as visible CLI arguments.
                with output_file.open('xb') as output:
                    output_file.chmod(0o600)
                    process = subprocess.run(command, cwd=root, stdout=output, stderr=subprocess.STDOUT,
                                             timeout=args.timeout + 10)
                    exit_code = process.returncode
                if raw_file.is_file():
                    raw_file.chmod(0o600)
                    if raw_file.stat().st_size <= 32 * 1024 * 1024:
                        data = raw_file.read_bytes(); result['raw_sha256'] = hashlib.sha256(data).hexdigest()
                        report = strict_json(data.decode('utf-8-sig'))
            result['status'], result['counts'], result['reason_codes'] = summarize(report, len(requests), exit_code)
        except subprocess.TimeoutExpired:
            exit_code = 124
            result['status'], result['counts'], result['reason_codes'] = summarize(None, len(requests), exit_code)
            result['reason_codes'] = ['timeout']
        except (ValueError, OSError):
            result['status'], result['counts'], result['reason_codes'] = summarize(None, len(requests), exit_code)
        finally:
            # Newman reports can contain the resolved environment; protect all raw output even on failure.
            for path in (raw_file, output_file):
                if path.is_file():
                    path.chmod(0o600)
            env_file.unlink(missing_ok=True)
        result['exit_code'] = exit_code
        _, current_collection_hash = delivery.read_artifact(root, record['postman_file'], 'Postman')
        if delivery.resolve_commit(root, 'HEAD') != server_sha or current_collection_hash != record['postman_sha256']:
            result['status'] = 'blocked'
            result['reason_codes'] = sorted(set(result['reason_codes'] + ['source_or_collection_changed_during_run']))
        if result['status'] == 'passed' and not result['newman_version']:
            result['status'] = 'blocked'
            result['reason_codes'] = ['runner_identity_unavailable']
    relative = f'docs/postman/{delivery.slug(domain)}/newman/{run_id}.summary.json'
    target = delivery.inside(root, relative); target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    target.write_text(payload, encoding='utf-8')
    result.update(summary_file=relative, summary_sha256=hashlib.sha256(payload.encode()).hexdigest())
    finalization.policy(state)['runs'].append(result)
    finalization.policy(state).pop('receipt', None)
    return result
