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
import signal
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlsplit

import devflow_delivery as delivery
import devflow_finalization as finalization
from devflow_postman import strict_json


SKIP_OR_EXTRA_REQUEST = re.compile(r'\b(?:pm\s*\.\s*sendRequest|pm\s*\.\s*execution\s*\.\s*(?:skipRequest|runRequest|setNextRequest)|postman\s*\.\s*setNextRequest)\s*\(')
BASE_MUTATION = re.compile(r'\bpm\s*\.\s*(?:environment|variables|collectionVariables|globals)\s*\.\s*(?:set|unset|clear)\s*\([^)]*[\'"]baseUrl[\'"]')
READINESS_POLL_INTERVAL = 0.2
SERVER_TERM_TIMEOUT = 5
SERVER_KILL_TIMEOUT = 2


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
    api_failure = False
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
            if not isinstance(assertion, dict):
                reasons.append('invalid_assertion')
            elif assertion.get('skipped'):
                reasons.append('skipped_assertions')
            elif assertion.get('error'):
                api_failure = True
                reasons.append('assertion_failure')
    if exit_code != 0:
        reasons.append('nonzero_exit')
    if run.get('failures') or counts['request_failures'] or counts['assertion_failures']:
        api_failure = True
        reasons.append('run_failures')
    structural = {'invalid_stats', 'missing_executions', 'request_coverage_mismatch', 'missing_assertions',
                  'missing_response', 'request_without_assertion', 'invalid_assertion', 'skipped_assertions'}
    if structural.intersection(reasons):
        return 'blocked', counts, sorted(set(reasons))
    if api_failure:
        return 'failed', counts, sorted(set(reasons))
    if exit_code != 0:
        return 'blocked', counts, ['newman_tool_failed']
    return 'passed', counts, []


def lifecycle(status: str = 'not_run') -> dict[str, Any]:
    return {'command_sha256': None, 'readiness_url': None, 'events': [],
            'startup': {'status': status, 'exit_code': None},
            'readiness': {'status': status, 'http_status': None, 'attempts': 0},
            'owned_process_alive_before_newman': None,
            'newman': {'status': status, 'exit_code': None},
            'cleanup': {'status': status, 'term_sent': False, 'kill_sent': False,
                        'stopped': status == 'not_applicable', 'exit_code': None},
            'log_file': None, 'log_sha256': None}


def add_event(record: dict[str, Any], name: str) -> None:
    record['events'].append({'name': name, 'at': dt.datetime.now(dt.timezone.utc).isoformat()})


def parse_server_command(value: str | None) -> list[str]:
    if not isinstance(value, str) or not value.strip():
        raise ValueError('server command is required')
    try:
        command = strict_json(value)
    except ValueError as exc:
        raise ValueError('server command must be a JSON argv array') from exc
    if not isinstance(command, list) or not command or any(
            not isinstance(part, str) or not part.strip() or '\x00' in part for part in command):
        raise ValueError('server command must be a nonempty JSON argv array of safe strings')
    return command


def process_group_alive(process: subprocess.Popen[Any]) -> bool:
    try:
        os.killpg(process.pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def cleanup_server(process: subprocess.Popen[Any], record: dict[str, Any]) -> bool:
    cleanup = record['cleanup']
    add_event(record, 'server_stop_requested')
    try:
        if process.poll() is None or process_group_alive(process):
            try:
                os.killpg(process.pid, signal.SIGTERM)
                cleanup['term_sent'] = True
            except ProcessLookupError:
                pass
        try:
            process.wait(timeout=SERVER_TERM_TIMEOUT)
        except subprocess.TimeoutExpired:
            pass
        if process.poll() is None or process_group_alive(process):
            try:
                os.killpg(process.pid, signal.SIGKILL)
                cleanup['kill_sent'] = True
            except ProcessLookupError:
                pass
            process.wait(timeout=SERVER_KILL_TIMEOUT)
        cleanup['exit_code'] = process.returncode
        cleanup['stopped'] = process.poll() is not None and not process_group_alive(process)
    except (OSError, subprocess.TimeoutExpired):
        cleanup['exit_code'] = process.returncode
        cleanup['stopped'] = process.poll() is not None and not process_group_alive(process)
    cleanup['status'] = 'passed' if cleanup['stopped'] else 'failed'
    if cleanup['stopped']:
        add_event(record, 'server_stopped')
    return cleanup['status'] == 'passed'


def wait_readiness(process: subprocess.Popen[Any], url: str, timeout: int,
                   record: dict[str, Any]) -> bool:
    readiness = record['readiness']
    deadline = time.monotonic() + timeout
    while True:
        readiness['attempts'] += 1
        if process.poll() is not None or not process_group_alive(process):
            readiness['status'] = 'failed'
            return False
        try:
            request = Request(url, method='GET')
            with urlopen(request, timeout=min(5, timeout)) as response:
                readiness['http_status'] = response.status
            if 200 <= readiness['http_status'] <= 299:
                if process.poll() is None and process_group_alive(process):
                    readiness['status'] = 'passed'
                    add_event(record, 'readiness_passed')
                    return True
                readiness['status'] = 'failed'
                return False
        except HTTPError as exc:
            readiness['http_status'] = exc.code
        except (OSError, URLError, TimeoutError):
            pass
        if time.monotonic() >= deadline:
            readiness['status'] = 'failed'
            return False
        time.sleep(min(READINESS_POLL_INTERVAL, max(0.0, deadline - time.monotonic())))


def file_hash(path: Path) -> str | None:
    if not path.is_file() or path.stat().st_size > 32 * 1024 * 1024:
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def persist_result(root: Path, domain: str, state: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    relative = f'docs/postman/{delivery.slug(domain)}/newman/{result["id"]}.summary.json'
    target = delivery.inside(root, relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    target.write_text(payload, encoding='utf-8')
    result.update(summary_file=relative, summary_sha256=hashlib.sha256(payload.encode()).hexdigest())
    finalization.policy(state)['runs'].append(result)
    finalization.policy(state).pop('receipt', None)
    return result


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
              'exit_code': 0, 'status': 'not_applicable', 'counts': {'expected_requests': 0,
                  'requests': 0, 'request_failures': 0, 'assertions': 0, 'assertion_failures': 0, 'skipped_assertions': 0},
              'reason_codes': ['no_http_surface'], 'server_sha': None, 'newman_version': None,
              'raw_file': None, 'raw_sha256': None, 'server_lifecycle': lifecycle(), 'no_http_evidence': None}

    def preflight_block(reason: str) -> dict[str, Any]:
        result['status'] = 'blocked'
        result['exit_code'] = 2
        result['reason_codes'] = [reason]
        return persist_result(root, domain, state, result)

    if not requests:
        declared = list(record.get('api_endpoints') or [])
        result['server_lifecycle'] = lifecycle('not_applicable')
        result['no_http_evidence'] = {'source_sha': record['head_sha'], 'collection_sha256': record['postman_sha256'],
                                      'request_count': 0, 'declared_api_endpoints': declared,
                                      'api_note': record.get('api_note')}
        if declared:
            result['status'] = 'blocked'
            result['exit_code'] = 2
            result['reason_codes'] = ['http_surface_assessment_mismatch']
        return persist_result(root, domain, state, result)
    if not 1 <= args.timeout <= 3600 or not 1 <= args.request_timeout <= args.timeout:
        return preflight_block('newman_tool_config_invalid')

    try:
        base_url = check_target(args.base_url, args.allow_host, args.safety_note)
        server_sha = delivery.resolve_commit(root, args.server_sha)
    except ValueError:
        return preflight_block('environment_setup_failed')
    if delivery.git(root, 'merge-base', record['head_sha'], server_sha) != record['head_sha']:
        return preflight_block('server_source_invalid')
    if server_sha != delivery.resolve_commit(root, 'HEAD'):
        return preflight_block('server_source_invalid')
    dirty = delivery.git(root, 'diff', '--name-only', '-z', 'HEAD', '--')
    untracked = delivery.git(root, 'ls-files', '--others', '--exclude-standard', '-z')
    if any(Path(p).suffix.lower() in delivery.SOURCE_SUFFIXES for p in (dirty + '\0' + untracked).split('\0') if p):
        return preflight_block('server_source_invalid')
    if any(item['request']['method'].upper() not in {'GET', 'HEAD', 'OPTIONS'} for item in requests) and not args.allow_writes:
        return preflight_block('write_scenarios_require_allow_writes')
    for source in scripts(collection):
        if SKIP_OR_EXTRA_REQUEST.search(source) or BASE_MUTATION.search(source):
            return preflight_block('bounded_profile_rejected')

    private = prepare_private_dir(root, run_id)
    raw_file = private / 'report.json'; output_file = private / 'output.log'
    snapshot_file = private / 'collection.json'
    env_file = private / 'environment.json'
    server_log = private / 'server.log'
    write_private(server_log, '')
    lifecycle_record = result['server_lifecycle']
    lifecycle_record['readiness_url'] = None
    lifecycle_record['log_file'] = str(server_log.relative_to(root))
    result.update(server_sha=server_sha, safety_note=args.safety_note.strip(), raw_file=str(raw_file.relative_to(root)),
                  counts={'expected_requests': len(requests), 'requests': 0, 'request_failures': 0,
                          'assertions': 0, 'assertion_failures': 0, 'skipped_assertions': 0})
    result['reason_codes'] = []

    def mark_blocked(reason: str) -> None:
        result['status'] = 'blocked'
        result['exit_code'] = 2
        result['reason_codes'] = sorted(set(result['reason_codes'] + [reason]))

    def block(reason: str) -> dict[str, Any]:
        mark_blocked(reason)
        lifecycle_record['log_sha256'] = file_hash(server_log)
        env_file.unlink(missing_ok=True)
        return persist_result(root, domain, state, result)

    try:
        server_argv = parse_server_command(args.server_command)
    except ValueError:
        reason = 'server_command_required' if not args.server_command else 'server_command_invalid'
        return block(reason)
    if type(args.readiness_timeout) is not int or not 1 <= args.readiness_timeout <= 600:
        return block('readiness_config_invalid')
    try:
        readiness_url = check_target(args.readiness_url, args.allow_host, args.safety_note)
    except ValueError:
        return block('environment_setup_failed')
    lifecycle_record['command_sha256'] = hashlib.sha256(
        json.dumps(server_argv, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
    lifecycle_record['readiness_url'] = readiness_url
    try:
        env = environment_values(args.environment, base_url)
        write_private(env_file, json.dumps(env))
        write_private(snapshot_file, text)
    except (OSError, ValueError):
        return block('environment_setup_failed')
    server_process: subprocess.Popen[Any] | None = None
    cleanup_ok = True
    try:
        try:
            with server_log.open('ab') as output:
                server_process = subprocess.Popen(server_argv, cwd=root, stdout=output, stderr=subprocess.STDOUT,
                                                   start_new_session=True)
            lifecycle_record['startup']['status'] = 'passed'
            add_event(lifecycle_record, 'server_started')
        except OSError:
            lifecycle_record['startup']['status'] = 'failed'
            mark_blocked('server_start_failed')
        if server_process is not None:
            if not wait_readiness(server_process, readiness_url, args.readiness_timeout, lifecycle_record):
                reason = 'owned_server_exited' if server_process.poll() is not None else 'readiness_failed'
                mark_blocked(reason)
            elif server_process.poll() is not None or not process_group_alive(server_process):
                lifecycle_record['owned_process_alive_before_newman'] = False
                mark_blocked('owned_server_exited')
            else:
                lifecycle_record['owned_process_alive_before_newman'] = True
                executable = shutil.which(args.newman_bin or 'newman')
                if not executable:
                    lifecycle_record['newman']['status'] = 'blocked'
                    mark_blocked('newman_tool_unavailable')
                else:
                    try:
                        version = subprocess.run([executable, '--version'], cwd=root, capture_output=True, text=True, timeout=10)
                    except (OSError, subprocess.TimeoutExpired):
                        version = None
                    if version is None or version.returncode != 0 or not re.fullmatch(
                            r'\d+\.\d+\.\d+(?:[-+][\w.-]+)?', version.stdout.strip()):
                        lifecycle_record['newman']['status'] = 'blocked'
                        mark_blocked('newman_tool_failed')
                    else:
                        result['newman_version'] = version.stdout.strip()
                        if server_process.poll() is not None or not process_group_alive(server_process):
                            lifecycle_record['owned_process_alive_before_newman'] = False
                            mark_blocked('owned_server_exited')
                        else:
                            command = [executable, 'run', str(snapshot_file),
                                       '--environment', str(env_file), '--reporters', 'json', '--reporter-json-export', str(raw_file),
                                       '--timeout', str(args.timeout * 1000), '--timeout-request', str(args.request_timeout * 1000),
                                       '--timeout-script', '5000', '--ignore-redirects', '--no-insecure-file-read',
                                       '--working-dir', str(private)]
                            # Credentials travel in a 0600 environment file, never as visible CLI arguments.
                            add_event(lifecycle_record, 'newman_started')
                            try:
                                with output_file.open('xb') as output:
                                    output_file.chmod(0o600)
                                    process = subprocess.run(command, cwd=root, stdout=output, stderr=subprocess.STDOUT,
                                                             timeout=args.timeout + 10)
                                    result['exit_code'] = process.returncode
                                add_event(lifecycle_record, 'newman_finished')
                                report: Any = None
                                if raw_file.is_file():
                                    raw_file.chmod(0o600)
                                    if raw_file.stat().st_size <= 32 * 1024 * 1024:
                                        data = raw_file.read_bytes(); result['raw_sha256'] = hashlib.sha256(data).hexdigest()
                                        report = strict_json(data.decode('utf-8-sig'))
                                result['status'], result['counts'], result['reason_codes'] = summarize(
                                    report, len(requests), result['exit_code'])
                                lifecycle_record['newman']['status'] = result['status']
                                lifecycle_record['newman']['exit_code'] = result['exit_code']
                            except subprocess.TimeoutExpired:
                                lifecycle_record['newman']['status'] = 'blocked'
                                lifecycle_record['newman']['exit_code'] = 124
                                result['exit_code'] = 124
                                mark_blocked('newman_tool_failed')
                            except (ValueError, OSError):
                                lifecycle_record['newman']['status'] = 'blocked'
                                mark_blocked('newman_tool_failed')
    finally:
        if server_process is not None:
            try:
                cleanup_ok = cleanup_server(server_process, lifecycle_record)
            except (OSError, subprocess.TimeoutExpired):
                lifecycle_record['cleanup']['status'] = 'failed'
                cleanup_ok = False
            if not cleanup_ok:
                result['status'] = 'blocked'
                result['exit_code'] = 2
                result['reason_codes'] = sorted(set(result['reason_codes'] + ['cleanup_failed']))
        for path in (raw_file, output_file, server_log):
            if path.is_file():
                path.chmod(0o600)
        lifecycle_record['log_sha256'] = file_hash(server_log)
        env_file.unlink(missing_ok=True)
    _, current_collection_hash = delivery.read_artifact(root, record['postman_file'], 'Postman')
    if delivery.resolve_commit(root, 'HEAD') != server_sha or current_collection_hash != record['postman_sha256']:
        result['status'] = 'blocked'
        result['exit_code'] = 2
        result['reason_codes'] = sorted(set(result['reason_codes'] + ['source_or_collection_changed_during_run']))
    return persist_result(root, domain, state, result)
