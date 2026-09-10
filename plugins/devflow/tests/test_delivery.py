#!/usr/bin/env python3
"""Delivery regression tests: real Git objects, local artifacts, and CLI state transitions."""
from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('devflow_fixtures', HERE / 'test_devflow.py')
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.root = fixtures.new_repo()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.runtime = fixtures.load_runtime_module()
        self.assertEqual(self.cli('init', 'sample').returncode, 0)
        self.d = self.root / 'docs/domains/sample'
        fixtures.fill_delivery_contract(self.d)
        self.base = self.git('rev-parse', 'HEAD')
        self.git('branch', 'delivery-base', self.base)
        self.git('switch', '-c', 'feature/sample')
        self.work_path = self.d / 'work/phase-01.yaml'
        self.state_path = self.d / 'STATE.yaml'
        self.template = self.root / 'docs/PR/templates.md'
        self.template.parent.mkdir(parents=True, exist_ok=True)
        self.template.write_text('# Summary\n\n<!-- Describe changes. -->\n\n## Verification\n\n<!-- Commands and results. -->\n')
        state = fixtures.state({'01': fixtures.phase('executing', '01')})
        state['baseline_sha'] = self.base
        state['target_sha'] = self.base
        fixtures.dump(self.state_path, state)
        fixtures.dump(self.work_path, fixtures.work_v2('01', fixtures.v2_item('P01-I01')))

    def cli(self, *args):
        return fixtures.invoke_runtime(self.root, self.runtime, *args)

    def git(self, *args):
        result = subprocess.run(['git', *args], cwd=self.root, text=True, capture_output=True)
        if result.returncode:
            raise AssertionError(result.stderr)
        return result.stdout.strip()

    def read_state(self):
        return yaml.safe_load(self.state_path.read_text())

    def read_work(self):
        return yaml.safe_load(self.work_path.read_text())

    def enable(self):
        result = self.cli('delivery', 'enable', 'sample')
        self.assertEqual(result.returncode, 0, result.stderr)

    def start_and_commit(self, *, comment=True, filename='src/service.py'):
        self.enable()
        started = self.cli('work', 'start', 'sample', 'P01-I01')
        self.assertEqual(started.returncode, 0, started.stderr)
        source = self.root / filename
        source.parent.mkdir(parents=True, exist_ok=True)
        content = '# Keep retries inside one transaction so duplicate submissions share a result.\n' if comment else ''
        source.write_text(content + 'def execute():\n    return 1\n')
        self.git('add', filename)
        self.git('commit', '-qm', 'implement sample')
        self.head = self.git('rev-parse', 'HEAD')
        self.source = filename

    def paths(self, branch=None):
        args = ['delivery', 'paths', 'sample']
        if branch:
            args += ['--branch', branch]
        result = self.cli(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def write_artifacts(self, *, endpoints=None, empty=False):
        paths = self.paths()
        self.pr = self.root / paths['pr_file']
        self.postman = self.root / paths['postman_file']
        self.pr.parent.mkdir(parents=True, exist_ok=True)
        self.postman.parent.mkdir(parents=True, exist_ok=True)
        self.metadata = {'branch': self.git('branch', '--show-current'), 'base_sha': self.base, 'head_sha': self.head}
        self.pr.write_text('<!-- devflow-delivery: ' + json.dumps(self.metadata) + ' -->\n'
                           '# Summary\n\nImplements the sample boundary and preserves retry semantics.\n\n'
                           '## Verification\n\nUnit checks executed; API execution is pending local credentials.\n')
        self.collection = {
            'info': {'name': 'Sample', 'schema': 'https://schema.getpostman.com/json/collection/v2.1.0/collection.json',
                     'description': 'Local test collection. Configure credentials before manual execution.', '_devflow': self.metadata},
            'variable': [{'key': 'baseUrl', 'value': 'http://localhost:8080'}, {'key': 'accessToken', 'value': ''}],
            'auth': {'type': 'bearer', 'bearer': [{'key': 'token', 'value': '{{accessToken}}', 'type': 'string'}]},
            'item': [] if empty else [{'name': 'Get sample', 'request': {'method': 'GET', 'url': '{{baseUrl}}/api/sample', 'header': []},
                      'event': [{'listen': 'test', 'script': {'type': 'text/javascript',
                                'exec': ['pm.test("Status", () => pm.response.to.have.status(200));']}}]}],
        }
        self.postman.write_text(json.dumps(self.collection, indent=2))
        doc = self.read_work()
        entry = doc['items'][-1]
        entry['evidence']['comments'] = [{'path': self.source, 'line': 1, 'reason': 'Explain the idempotency boundary for duplicate submissions.'}]
        entry['evidence']['delivery'] = {
            'base_ref': 'delivery-base', 'pr_file': paths['pr_file'], 'postman_file': paths['postman_file'],
            'api_endpoints': ([] if empty else ['GET /api/sample']) if endpoints is None else endpoints,
            'api_note': 'No HTTP surface is affected; this WORK changes a private scheduling helper.' if empty else 'Covers the changed sample endpoint.',
        }
        fixtures.dump(self.work_path, doc)

    def done(self, item='P01-I01', head=None):
        return self.cli('work', 'done', 'sample', item, '--commit', head or self.head, '--command', 'unit checks -> passed')

    def assert_refused_atomically(self, expected):
        before = (self.state_path.read_bytes(), self.work_path.read_bytes())
        result = self.done()
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn(expected.lower(), result.stderr.lower())
        self.assertEqual(before, (self.state_path.read_bytes(), self.work_path.read_bytes()))

    def test_new_domains_enable_delivery_policy(self):
        result = self.cli('init', 'new-domain')
        self.assertEqual(result.returncode, 0, result.stderr)
        state = yaml.safe_load((self.root / 'docs/domains/new-domain/STATE.yaml').read_text())
        self.assertEqual(state.get('delivery', {}).get('version'), 1)

    def test_enable_is_idempotent_and_preserves_done_work(self):
        doc = self.read_work()
        doc['items'][0]['status'] = 'done'
        doc['items'][0]['evidence']['commands'] = ['checks -> passed']
        fixtures.dump(self.work_path, doc)
        before = self.work_path.read_bytes()
        self.enable()
        self.assertEqual(self.read_state()['delivery']['grandfathered_work_ids'], ['P01-I01'])
        state_bytes = self.state_path.read_bytes()
        self.enable()
        self.assertEqual(before, self.work_path.read_bytes())
        self.assertEqual(state_bytes, self.state_path.read_bytes())

    def test_commentless_source_cannot_complete(self):
        self.start_and_commit(comment=False)
        self.write_artifacts()
        self.assert_refused_atomically('comment')

    def test_missing_pr_cannot_complete(self):
        self.start_and_commit(); self.write_artifacts(); self.pr.unlink()
        self.assert_refused_atomically('PR')

    def test_missing_postman_cannot_complete(self):
        self.start_and_commit(); self.write_artifacts(); self.postman.unlink()
        self.assert_refused_atomically('Postman')

    def test_completion_records_branch_artifacts_and_comment_provenance(self):
        self.start_and_commit(); self.write_artifacts()
        result = self.done()
        self.assertEqual(result.returncode, 0, result.stderr)
        state = self.read_state()
        record = state['delivery']['branches']['feature/sample']
        self.assertEqual(record['head_sha'], self.head)
        self.assertEqual(record['work_ids'], ['P01-I01'])
        self.assertEqual(len(record['pr_sha256']), 64)
        self.assertEqual(self.read_work()['items'][0]['evidence']['start_sha'], self.base)
        self.assertEqual(self.cli('validate', 'sample').returncode, 0)

    def test_wrong_commit_is_rejected(self):
        self.start_and_commit(); self.write_artifacts()
        result = self.done(head=self.base)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn('HEAD', result.stderr)

    def test_template_is_preserved_and_its_headings_are_required(self):
        self.start_and_commit(); self.write_artifacts()
        original = self.template.read_bytes()
        self.pr.write_text(self.pr.read_text().replace('## Verification', '## Other'))
        self.assert_refused_atomically('heading')
        self.assertEqual(self.template.read_bytes(), original)

    def test_stale_pr_metadata_is_rejected(self):
        self.start_and_commit(); self.write_artifacts()
        self.pr.write_text(self.pr.read_text().replace(self.head, self.base))
        self.assert_refused_atomically('head_sha')

    def test_stale_postman_metadata_is_rejected(self):
        self.start_and_commit(); self.write_artifacts()
        self.collection['info']['_devflow'] = dict(self.metadata, head_sha=self.base)
        self.postman.write_text(json.dumps(self.collection))
        self.assert_refused_atomically('head_sha')

    def test_empty_collection_requires_explicit_api_assessment(self):
        self.start_and_commit(); self.write_artifacts(empty=True)
        doc = self.read_work(); doc['items'][0]['evidence']['delivery']['api_note'] = ''
        fixtures.dump(self.work_path, doc)
        self.assert_refused_atomically('api_note')

    def test_non_http_change_still_produces_importable_empty_collection(self):
        self.start_and_commit(); self.write_artifacts(empty=True)
        result = self.done()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_collection_rejects_missing_declared_endpoint(self):
        self.start_and_commit(); self.write_artifacts(endpoints=['POST /api/missing'])
        self.assert_refused_atomically('endpoint')

    def test_collection_rejects_real_credential_defaults(self):
        self.start_and_commit(); self.write_artifacts()
        self.collection['variable'][1]['value'] = 'real-access-token'
        self.postman.write_text(json.dumps(self.collection))
        self.assert_refused_atomically('credential')

    def test_collection_rejects_malformed_nested_items(self):
        self.start_and_commit(); self.write_artifacts()
        self.collection['item'] = [{'name': 'Bad folder', 'item': 'not an array'}]
        self.postman.write_text(json.dumps(self.collection))
        self.assert_refused_atomically('item')

    def test_collection_rejects_unresolved_variables(self):
        self.start_and_commit(); self.write_artifacts()
        self.collection['item'][0]['request']['url'] = '{{baseUrl}}/api/{{unknown}}'
        self.postman.write_text(json.dumps(self.collection))
        self.assert_refused_atomically('variable')

    def test_collection_requires_assertion_scripts_for_requests(self):
        self.start_and_commit(); self.write_artifacts()
        self.collection['item'][0]['event'] = []
        self.postman.write_text(json.dumps(self.collection))
        self.assert_refused_atomically('test')

    def test_source_anchor_cannot_point_outside_changed_source(self):
        self.start_and_commit(); self.write_artifacts()
        doc = self.read_work(); doc['items'][0]['evidence']['comments'][0]['path'] = 'seed.txt'
        fixtures.dump(self.work_path, doc)
        self.assert_refused_atomically('source')

    def test_artifact_path_traversal_is_rejected(self):
        self.start_and_commit(); self.write_artifacts()
        doc = self.read_work(); doc['items'][0]['evidence']['delivery']['pr_file'] = '../../outside.md'
        fixtures.dump(self.work_path, doc)
        self.assert_refused_atomically('path')

    def test_artifact_symlink_escape_is_rejected(self):
        self.start_and_commit(); self.write_artifacts()
        outside = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, outside, True)
        target = outside / 'body.md'; target.write_bytes(self.pr.read_bytes())
        self.pr.unlink(); self.pr.symlink_to(target)
        self.assert_refused_atomically('path')

    def test_branch_slugs_do_not_collide(self):
        a = self.paths('feature/a-b'); b = self.paths('feature-a/b'); c = self.paths('Feature/a-b')
        self.assertEqual(len({a['pr_file'], b['pr_file'], c['pr_file']}), 3)
        self.assertTrue(all('..' not in p['pr_file'] for p in [a, b, c]))

    def test_ignored_docs_can_complete_without_git_history(self):
        self.start_and_commit(); self.write_artifacts()
        (self.root / '.git/info/exclude').write_text('docs/\n')
        result = self.done()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git('ls-files', 'docs'), '')

    def test_artifact_tampering_is_detected_and_refreshable(self):
        self.start_and_commit(); self.write_artifacts()
        self.assertEqual(self.done().returncode, 0)
        self.pr.write_text(self.pr.read_text() + '\nAdditional checked explanation.\n')
        self.assertEqual(self.cli('delivery', 'check', 'sample').returncode, 2)
        result = self.cli('delivery', 'refresh', 'sample', '--branch', 'feature/sample')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.cli('delivery', 'check', 'sample').returncode, 0)

    def test_final_check_rejects_branch_tip_advance(self):
        self.start_and_commit(); self.write_artifacts(); self.assertEqual(self.done().returncode, 0)
        self.git('commit', '--allow-empty', '-qm', 'advance after handoff')
        result = self.cli('delivery', 'check', 'sample', '--final')
        self.assertEqual(result.returncode, 2)
        self.assertIn('tip', result.stderr.lower())

    def test_refresh_cannot_authenticate_uncovered_new_source_commit(self):
        self.start_and_commit(); self.write_artifacts(); self.assertEqual(self.done().returncode, 0)
        self.git('commit', '--allow-empty', '-qm', 'new uncovered head')
        self.assertEqual(self.cli('delivery', 'refresh', 'sample', '--branch', 'feature/sample').returncode, 2)

    def test_second_work_updates_one_cumulative_branch_record(self):
        self.start_and_commit(); self.write_artifacts(); self.assertEqual(self.done().returncode, 0)
        doc = self.read_work(); doc['items'].append(fixtures.v2_item('P01-I02'))
        fixtures.dump(self.work_path, doc)
        result = self.cli('work', 'start', 'sample', 'P01-I02')
        self.assertEqual(result.returncode, 0, result.stderr)
        (self.root / self.source).write_text('# Keep retries inside one transaction so duplicate submissions share a result.\ndef execute():\n    return 2\n')
        self.git('add', self.source); self.git('commit', '-qm', 'second change')
        self.head = self.git('rev-parse', 'HEAD')
        self.write_artifacts()
        result = self.done(item='P01-I02')
        self.assertEqual(result.returncode, 0, result.stderr)
        record = self.read_state()['delivery']['branches']['feature/sample']
        self.assertEqual(record['work_ids'], ['P01-I01', 'P01-I02'])
        self.assertEqual(self.cli('validate', 'sample').returncode, 0)

    def test_render_contains_actual_pr_template_and_delivery_policy(self):
        self.enable()
        result = self.cli('render', 'run', 'sample')
        self.assertEqual(result.returncode, 0, result.stderr)
        for value in ['delivery-artifacts.md', '# Summary', 'docs/PR/templates.md', 'Postman', 'comments']:
            self.assertIn(value, result.stdout)


    def test_uncommitted_source_is_not_hidden_by_committed_evidence(self):
        self.start_and_commit(); self.write_artifacts()
        (self.root / self.source).write_text('def execute():\n    return 999\n')
        self.assert_refused_atomically('uncommitted')

    def test_collection_rejects_form_credential_literals(self):
        self.start_and_commit(); self.write_artifacts()
        self.collection['item'][0]['request']['body'] = {
            'mode': 'urlencoded', 'urlencoded': [{'key': 'password', 'value': 'sensitive-literal'}]}
        self.postman.write_text(json.dumps(self.collection))
        self.assert_refused_atomically('credential')

    def test_collection_rejects_sibling_variable_leak(self):
        self.start_and_commit(); self.write_artifacts()
        request = self.collection['item'][0]
        request['request']['header'] = [{'key': 'X-Company', 'value': '{{companyId}}'}]
        self.collection['item'] = [
            {'name': 'Sibling', 'variable': [{'key': 'companyId', 'value': '1'}], 'item': []}, request]
        self.postman.write_text(json.dumps(self.collection))
        self.assert_refused_atomically('variable')

    def test_python_placeholder_comment_is_not_evidence(self):
        self.start_and_commit()
        (self.root / self.source).write_text('# TODO\ndef execute():\n    return 1\n')
        self.git('add', self.source); self.git('commit', '-qm', 'placeholder')
        self.head = self.git('rev-parse', 'HEAD'); self.write_artifacts()
        self.assert_refused_atomically('comment')

    def test_source_start_sha_must_be_an_ancestor(self):
        self.start_and_commit(); self.write_artifacts()
        self.git('checkout', '--orphan', 'unrelated')
        self.git('commit', '--allow-empty', '-qm', 'unrelated history')
        unrelated = self.git('rev-parse', 'HEAD')
        self.git('switch', 'feature/sample')
        doc = self.read_work(); doc['items'][0]['evidence']['start_sha'] = unrelated
        fixtures.dump(self.work_path, doc)
        self.assert_refused_atomically('ancestor')

    def test_pinned_base_remains_usable_after_parent_branch_is_deleted(self):
        self.start_and_commit(); self.write_artifacts()
        doc = self.read_work(); doc['items'][0]['evidence']['delivery']['base_sha'] = self.base
        fixtures.dump(self.work_path, doc)
        self.git('branch', '-D', 'delivery-base')
        result = self.done()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_two_branches_have_independent_cumulative_artifacts(self):
        self.start_and_commit(); self.write_artifacts(); self.assertEqual(self.done().returncode, 0)
        doc = self.read_work(); doc['items'].append(fixtures.v2_item('P01-I02'))
        fixtures.dump(self.work_path, doc)
        self.git('switch', '-c', 'feature/second')
        self.assertEqual(self.cli('work', 'start', 'sample', 'P01-I02').returncode, 0)
        (self.root / self.source).write_text('# Preserve transaction-scoped retry identity across both branches.\ndef execute():\n    return 2\n')
        self.git('add', self.source); self.git('commit', '-qm', 'second branch')
        self.head = self.git('rev-parse', 'HEAD'); self.write_artifacts()
        result = self.done(item='P01-I02')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.read_state()['delivery']['branches']), 2)
        self.assertEqual(self.cli('delivery', 'check', 'sample', '--final').returncode, 0)

    def test_documentation_only_work_records_explained_comment_exception(self):
        self.start_and_commit(filename='notes.md'); self.write_artifacts(empty=True)
        doc = self.read_work(); ev = doc['items'][0]['evidence']
        ev['comments'] = []; ev['comments_note'] = 'Only the operational notes changed; no executable source changed.'
        fixtures.dump(self.work_path, doc)
        result = self.done(); self.assertEqual(result.returncode, 0, result.stderr)

    def test_duplicate_json_keys_are_rejected(self):
        self.start_and_commit(); self.write_artifacts()
        self.postman.write_text('{"info":{},"info":{}}')
        self.assert_refused_atomically('duplicate')


    def test_paths_for_other_branch_resolve_that_branch_head(self):
        self.start_and_commit()
        paths = self.paths('delivery-base')
        self.assertEqual(paths['head_sha'], self.base)
        self.assertNotEqual(paths['head_sha'], self.head)

    def test_uncreated_branch_path_preview_has_no_claimed_head(self):
        paths = self.paths('feature/planned')
        self.assertIsNone(paths['head_sha'])

    def test_raw_json_credential_placeholders_remain_valid(self):
        self.start_and_commit(); self.write_artifacts()
        self.collection['variable'].append({'key': 'password', 'value': ''})
        self.collection['item'][0]['request']['body'] = {
            'mode': 'raw', 'raw': '{"password":"{{password}}","name":"synthetic"}',
            'options': {'raw': {'language': 'json'}}}
        self.postman.write_text(json.dumps(self.collection))
        result = self.done(); self.assertEqual(result.returncode, 0, result.stderr)

    def test_local_folder_variable_resolves_for_its_child(self):
        self.start_and_commit(); self.write_artifacts()
        request = self.collection['item'][0]
        request['request']['header'] = [{'key':'X-Company', 'value':'{{companyId}}'}]
        self.collection['item'] = [{'name':'Scoped', 'variable':[{'key':'companyId','value':'synthetic'}], 'item':[request]}]
        self.postman.write_text(json.dumps(self.collection))
        result = self.done(); self.assertEqual(result.returncode, 0, result.stderr)


    def test_in_progress_migration_preserves_work_and_resumes_from_baseline(self):
        doc = self.read_work(); doc['items'][0]['status'] = 'in_progress'
        fixtures.dump(self.work_path, doc)
        before = self.work_path.read_bytes(); self.enable()
        self.assertEqual(self.work_path.read_bytes(), before)
        self.source = 'src/service.py'; path = self.root / self.source
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('# Keep the completion baseline conservative when adopting active work.\ndef execute():\n    return 1\n')
        self.git('add', self.source); self.git('commit', '-qm', 'resume migrated work')
        self.head = self.git('rev-parse', 'HEAD'); self.write_artifacts()
        result = self.done(); self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.read_work()['items'][0]['evidence']['start_sha'], self.base)

    def test_run_instructions_cover_resume_and_start_sha_preservation(self):
        plugin = HERE.parent
        for file in ['skills/run/SKILL.md', 'core/prompts/run.md']:
            text = (plugin / file).read_text()
            self.assertIn('in_progress', text)
            self.assertIn('start_sha', text)


    def finish_phase_audit(self):
        result = self.cli('phase', 'ref', 'sample', '01', '--base', 'delivery-base', '--head', 'feature/sample')
        self.assertEqual(result.returncode, 0, result.stderr)
        fixtures.write_audit(self.d / 'audits/phase-01.md', fixtures.audit_metadata(self.d, scope='phase'))
        result = self.cli('audit', 'apply', 'sample', '--scope', 'phase', '--phase', '01', '--mode', 'initial')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_enabled_delivery_completes_full_audit_lifecycle(self):
        # Preserve this 0.7 compatibility scenario; 0.8 finalization has its own full audit test.
        doc = self.read_work(); item = doc['items'][0]
        item['risk'] = {'level':'high','axes':['correctness']}
        item['premise_checks'] = ['Verify the recorded source baseline is current.']
        fixtures.dump(self.work_path, doc)
        self.start_and_commit(); self.write_artifacts()
        self.assertEqual(self.done().returncode, 0)
        self.assertEqual(self.read_state()['next_action']['scope'], 'work')
        fixtures.write_audit(self.d / 'audits/work/P01-I01.md', fixtures.audit_metadata(self.d, scope='work'))
        result = self.cli('audit', 'apply', 'sample', '--scope', 'work', '--task', 'P01-I01', '--mode', 'initial')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.finish_phase_audit()
        state = self.read_state(); state['delivery'].pop('finalization', None)
        fixtures.dump(self.state_path, state)
        fixtures.write_audit(self.d / 'audits/integration.md', fixtures.audit_metadata(self.d))
        result = self.cli('audit', 'apply', 'sample', '--scope', 'integration', '--mode', 'initial')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.read_state()['project_status'], 'complete')
        self.assertEqual(self.cli('validate', 'sample').returncode, 0)

    def test_integration_audit_cannot_bypass_final_delivery_gate(self):
        self.start_and_commit(); self.write_artifacts(); self.assertEqual(self.done().returncode, 0)
        self.finish_phase_audit()
        self.git('commit', '--allow-empty', '-qm', 'source advanced after handoff')
        self.assertEqual(self.cli('status', 'sample').returncode, 0)
        fixtures.write_audit(self.d / 'audits/integration.md', fixtures.audit_metadata(self.d))
        before = self.state_path.read_bytes()
        result = self.cli('audit', 'apply', 'sample', '--scope', 'integration', '--mode', 'initial')
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('finalize', result.stderr)
        self.assertEqual(before, self.state_path.read_bytes())
        check = self.cli('delivery', 'check', 'sample', '--final')
        self.assertEqual(check.returncode, 2)
        self.assertIn('tip', check.stderr)


    def test_executable_wrapper_runs_from_consuming_repository(self):
        wrapper = HERE.parent / 'bin/devflow'
        self.assertTrue(wrapper.stat().st_mode & 0o111, 'bin/devflow must preserve executable permission')
        result = subprocess.run([str(wrapper), '--help'], cwd=self.root, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('delivery', result.stdout)


if __name__ == '__main__':
    unittest.main(verbosity=2)
