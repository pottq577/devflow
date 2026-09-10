#!/usr/bin/env python3
"""Foreground finalization tests using real Git provenance and isolated runner fixtures."""
from __future__ import annotations
import copy
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_delivery import DeliveryTests, fixtures


class FinalizationTests(DeliveryTests):
    def cli(self, *args):
        with patch("argparse.ArgumentParser.exit", side_effect=ValueError("unsupported CLI command")):
            return fixtures.invoke_runtime(self.root, self.runtime, *args)

    # Reuse fixture methods; the loader below selects only tests defined in this subclass.
    def completed(self, *, empty=False):
        self.start_and_commit(); self.write_artifacts(empty=empty)
        result = self.done(); self.assertEqual(result.returncode, 0, result.stderr)

    def context(self):
        result = self.cli('delivery', 'context', 'sample')
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def skill(self):
        path = self.root / '.agents/skills/eli5/SKILL.md'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('---\nname: eli5\ndescription: Explain repository work as HTML.\n---\nRead full work context.\n')
        return path

    def html(self, context=None):
        context = context or self.context()
        path = self.root / context['html_file']
        path.parent.mkdir(parents=True, exist_ok=True)
        meta = context['html_metadata']
        path.write_text('<!doctype html><html><head><title>Implementation explanation</title></head><body>'
                        '<!-- devflow-explanation: ' + json.dumps(meta) + ' -->'
                        '<h1>Whole work explanation</h1>'
                        + '<p>' + ' '.join(meta['work_ids']) + '</p>'
                        + '<p>Purpose, end-to-end flow, implementation changes, decisions, verification '
                        'and known limits are explained with source references.</p></body></html>')
        return path

    def explain(self):
        self.html()
        return self.cli('delivery', 'explain', 'sample', '--skill-file', str(self.skill()),
                        '--invocation', '$eli5 with complete PLAN, WORK, branch snapshots and verification results')

    def fake_newman(self, *, failure=False, zero=False, skip=False, invalid=False):
        path = self.root / 'runner-bin/newman'
        path.parent.mkdir(exist_ok=True)
        n = 0 if zero else 1
        assertions = [] if zero else [{'assertion': 'Status', 'skipped': skip}]
        if failure and assertions:
            assertions[0]['error'] = {'name': 'AssertionError', 'message': 'secret-do-not-publish'}
        report = {'run': {'stats': {'requests': {'total': n, 'failed': 0},
                                  'assertions': {'total': n, 'failed': int(failure), 'pending': int(skip)}},
                          'failures': [{'error': {'name': 'AssertionError', 'message': 'secret-do-not-publish'}}] if failure else [],
                          'executions': [] if zero else [{'item': {'name': 'Get sample'}, 'response': {'code': 200},
                                                        'assertions': assertions}]}}
        report_text = '{bad' if invalid else json.dumps(report)
        path.write_text('#!' + sys.executable + ' -S\nimport sys, pathlib\n'
                        'if "--version" in sys.argv:\n print("6.2.1"); sys.exit(0)\n'
                        'pathlib.Path(sys.argv[sys.argv.index("--reporter-json-export")+1]).write_text(' + repr(report_text) + ')\n'
                        'print("secret-do-not-publish")\n'
                        'sys.exit(' + str(1 if failure else 0) + ')\n')
        path.chmod(0o755)
        return path

    def run_newman(self, *extra, **kwargs):
        runner = self.fake_newman(**kwargs)
        return self.cli('delivery', 'newman', 'sample', '--branch', 'feature/sample',
                        '--newman-bin', str(runner), '--base-url', 'http://127.0.0.1:18080',
                        '--server-sha', self.head, '--safety-note', 'Disposable local server, synthetic fixtures, no live integrations.', *extra)

    def test_new_init_and_adoption_enable_finalization(self):
        self.enable()
        self.assertEqual(self.read_state()['delivery'].get('finalization', {}).get('version'), 1)
        before = self.work_path.read_bytes()
        self.enable(); self.assertEqual(self.work_path.read_bytes(), before)

    def test_v070_adoption_preserves_original_grandfathered_set(self):
        self.enable()
        state = self.read_state(); state['delivery'].pop('finalization', None)
        state['delivery']['grandfathered_work_ids'] = []
        fixtures.dump(self.state_path, state)
        self.enable()
        self.assertEqual(self.read_state()['delivery']['grandfathered_work_ids'], [])
        self.assertIn('finalization', self.read_state()['delivery'])

    def test_context_covers_all_work_and_branches_not_head_only(self):
        self.completed()
        doc = self.read_work(); doc['items'].append(fixtures.v2_item('P01-I02'))
        doc['items'][-1]['status'] = 'cancelled'
        fixtures.dump(self.work_path, doc)
        ctx = self.context()
        self.assertEqual(ctx['html_metadata']['work_ids'], ['P01-I01', 'P01-I02'])
        self.assertEqual(ctx['html_metadata']['branches'], ['feature/sample'])
        self.assertIn('cancelled', json.dumps(ctx))
        self.assertNotIn('feature-sample', ctx['html_file'])

    def test_explanation_requires_installed_eli5(self):
        self.completed(); self.html()
        result = self.cli('delivery', 'explain', 'sample', '--skill-file', str(self.root / 'missing/SKILL.md'), '--invocation', '$eli5')
        self.assertEqual(result.returncode, 2)
        self.assertIn('eli5', result.stderr.lower())

    def test_explanation_records_scope_and_skill_content_hash(self):
        self.completed(); result = self.explain()
        self.assertEqual(result.returncode, 0, result.stderr)
        record = self.read_state()['delivery']['finalization']['explanation']
        self.assertEqual(len(record['skill_sha256']), 64)
        self.assertEqual(len(record['scope_sha256']), 64)

    def test_explanation_rejects_partial_work_metadata(self):
        self.completed(); ctx = self.context(); ctx['html_metadata']['work_ids'] = []
        self.html(ctx)
        result = self.cli('delivery', 'explain', 'sample', '--skill-file', str(self.skill()), '--invocation', '$eli5')
        self.assertEqual(result.returncode, 2)
        self.assertIn('work_ids', result.stderr)

    def test_real_invocation_receipt_and_private_report(self):
        self.completed(); result = self.run_newman()
        self.assertEqual(result.returncode, 0, result.stderr)
        run = self.read_state()['delivery']['finalization']['runs'][-1]
        self.assertEqual(run['status'], 'passed')
        summary = (self.root / run['summary_file']).read_text()
        self.assertNotIn('secret-do-not-publish', summary)
        self.assertNotIn('secret-do-not-publish', result.stdout)
        raw = self.root / run['raw_file']; self.assertEqual(raw.stat().st_mode & 0o777, 0o600)
        self.assertTrue(self.git('check-ignore', str(raw)))

    def test_newman_assertion_failure_persists_evidence_and_returns_nonzero(self):
        self.completed(); result = self.run_newman(failure=True)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(self.read_state()['delivery']['finalization']['runs'][-1]['status'], 'failed')

    def test_zero_requests_cannot_pass_nonempty_collection(self):
        self.completed(); result = self.run_newman(zero=True)
        self.assertNotEqual(result.returncode, 0)

    def test_skipped_assertions_cannot_pass(self):
        self.completed(); result = self.run_newman(skip=True)
        self.assertNotEqual(result.returncode, 0)

    def test_malformed_newman_report_cannot_pass(self):
        self.completed(); result = self.run_newman(invalid=True)
        self.assertNotEqual(result.returncode, 0)

    def test_remote_target_requires_explicit_test_host_authorization(self):
        self.completed(); result = self.run_newman('--base-url', 'https://api.example.com')
        self.assertEqual(result.returncode, 2)
        self.assertIn('host', result.stderr.lower())

    def test_server_commit_must_cover_collection_source(self):
        self.completed(); result = self.run_newman('--server-sha', self.base)
        self.assertEqual(result.returncode, 2)
        self.assertIn('source', result.stderr.lower())

    def test_no_http_collection_has_explicit_not_applicable_status(self):
        self.completed(empty=True)
        result = self.run_newman(zero=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.read_state()['delivery']['finalization']['runs'][-1]['status'], 'not_applicable')

    def test_finalization_requires_html_and_newman(self):
        self.completed()
        result = self.cli('delivery', 'finalize', 'sample')
        self.assertEqual(result.returncode, 2)
        self.assertIn('explanation', result.stderr.lower())
        self.assertIn('newman', result.stderr.lower())

    def test_finalization_succeeds_with_fresh_explanation_and_executed_run(self):
        self.completed(); self.assertEqual(self.run_newman().returncode, 0)
        self.assertEqual(self.explain().returncode, 0)
        result = self.cli('delivery', 'finalize', 'sample')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('receipt', self.read_state()['delivery']['finalization'])

    def test_newman_run_invalidates_earlier_explanation(self):
        self.completed(); self.assertEqual(self.explain().returncode, 0)
        self.assertEqual(self.run_newman().returncode, 0)
        result = self.cli('delivery', 'finalize', 'sample')
        self.assertEqual(result.returncode, 2)
        self.assertIn('stale', result.stderr.lower())

    def test_complete_action_is_gated_by_whole_work_finalization(self):
        self.completed()
        state = self.read_state(); state['phases']['01']['status'] = 'verified'; state['integration']['status'] = 'pending'
        fixtures.dump(self.state_path, state)
        result = self.cli('status', 'sample', '--json')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['next_action']['command'], 'finalize')
        rendered = self.cli('render', 'finalize', 'sample')
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        self.assertIn('$eli5', rendered.stdout)
        self.assertIn('P01-I01', rendered.stdout)

    def test_failed_run_requires_explicit_diagnosis_even_after_pass(self):
        self.completed(); self.run_newman(failure=True); self.run_newman(); self.explain()
        result = self.cli('delivery', 'finalize', 'sample')
        self.assertEqual(result.returncode, 2)
        self.assertIn('triage', result.stderr.lower())

    def test_environment_diagnosis_requires_evidence_but_no_code_commit(self):
        self.completed(); self.run_newman(failure=True)
        run = self.read_state()['delivery']['finalization']['runs'][-1]
        result = self.cli('delivery', 'triage', 'sample', '--run-id', run['id'], '--classification', 'environment',
                          '--reason', 'The test process used the wrong database; service build and API contract agree.')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.run_newman(); self.explain()
        result = self.cli('delivery', 'finalize', 'sample')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_code_diagnosis_requires_traceable_repair_work(self):
        self.completed(); self.run_newman(failure=True)
        run = self.read_state()['delivery']['finalization']['runs'][-1]
        result = self.cli('delivery', 'triage', 'sample', '--run-id', run['id'], '--classification', 'code',
                          '--reason', 'Controller violates the approved retry contract and the focused test reproduces it.')
        self.assertEqual(result.returncode, 2)
        self.assertIn('WORK', result.stderr)

    def test_raw_newman_report_tamper_is_detected(self):
        self.completed(); self.run_newman(); self.explain()
        run = self.read_state()['delivery']['finalization']['runs'][-1]
        (self.root / run['raw_file']).write_text('{}')
        result = self.cli('delivery', 'finalize', 'sample')
        self.assertEqual(result.returncode, 2)
        self.assertIn('raw', result.stderr.lower())

    def test_final_status_detects_advanced_branch_tip(self):
        self.completed(); self.run_newman(); self.explain()
        self.assertEqual(self.cli('delivery', 'finalize', 'sample').returncode, 0)
        state = self.read_state(); state['phases']['01']['status'] = 'verified'
        fixtures.dump(self.state_path, state)
        (self.root / self.source).write_text('# Preserve idempotency while extending the result.\ndef execute():\n    return 5\n')
        self.git('add', self.source); self.git('commit', '-qm', 'unrecorded new source')
        result = self.cli('status', 'sample', '--json')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['next_action']['command'], 'finalize')

    def test_mutating_requests_require_test_write_opt_in(self):
        self.start_and_commit(); self.write_artifacts(endpoints=['POST /api/sample'])
        self.collection['item'][0]['request']['method'] = 'POST'
        self.postman.write_text(json.dumps(self.collection))
        self.assertEqual(self.done().returncode, 0)
        result = self.run_newman()
        self.assertEqual(result.returncode, 2)
        self.assertIn('allow-writes', result.stderr)
        self.assertEqual(self.run_newman('--allow-writes').returncode, 0)

    def test_background_requests_are_rejected_by_bounded_profile(self):
        self.start_and_commit(); self.write_artifacts()
        self.collection['item'][0]['event'][0]['script']['exec'].append('pm.sendRequest("https://external.invalid");')
        self.postman.write_text(json.dumps(self.collection))
        self.assertEqual(self.done().returncode, 0)
        result = self.run_newman()
        self.assertEqual(result.returncode, 2)
        self.assertIn('bounded', result.stderr.lower())

    def test_local_environment_is_private_and_removed_after_run(self):
        self.completed()
        env = self.root / 'private-env.json'
        env.write_text(json.dumps({'values': [{'key': 'accessToken', 'value': 'private-actual-token'}]}))
        result = self.run_newman('--environment', str(env))
        self.assertEqual(result.returncode, 0, result.stderr)
        run = self.read_state()['delivery']['finalization']['runs'][-1]
        self.assertFalse((self.root / run['raw_file']).with_name('environment.json').exists())
        self.assertNotIn('private-actual-token', json.dumps(run))

    def test_invalid_timeout_rejected_before_execution(self):
        self.completed(); result = self.run_newman('--timeout', '0')
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.read_state()['delivery']['finalization']['runs'], [])

    def test_unknown_classification_preserves_final_block(self):
        self.completed(); self.run_newman(failure=True)
        run = self.read_state()['delivery']['finalization']['runs'][-1]
        self.assertEqual(self.cli('delivery', 'triage', 'sample', '--run-id', run['id'], '--classification', 'unknown',
                                 '--reason', 'Server and collection contracts require additional evidence to distinguish.').returncode, 0)
        self.run_newman(); self.explain()
        self.assertEqual(self.cli('delivery', 'finalize', 'sample').returncode, 2)

    def test_repair_work_commit_and_rerun_close_failure(self):
        self.completed(); self.run_newman(failure=True)
        failure = self.read_state()['delivery']['finalization']['runs'][-1]
        self.finish_phase_audit()
        repair = fixtures.v2_item('F-I01'); repair['kind'] = 'remediation'
        repair['origin']['findings'] = ['NEWMAN-' + failure['id']]
        repair['references'] = [failure['summary_file']]
        repair['scope']['allowed'] = ['src/service.py']
        repair['dependencies'] = ['P01-I01']
        repair_path = self.d / 'work/integration.yaml'
        fixtures.dump(repair_path, {'version': 2, 'phase': 'integration', 'items': [repair]})
        result = self.cli('delivery', 'triage', 'sample', '--run-id', failure['id'], '--classification', 'code',
                          '--reason', 'Approved retry result is two; regression reproduces the implementation returning one.', '--work-id', 'F-I01')
        self.assertEqual(result.returncode, 0, result.stderr)
        status = self.cli('status', 'sample', '--json')
        self.assertEqual(json.loads(status.stdout)['next_action']['work_item'], 'F-I01')
        self.assertEqual(self.cli('work', 'start', 'sample', 'F-I01').returncode, 0)
        (self.root / self.source).write_text('# Preserve the retry identity while returning the approved result.\ndef execute():\n    return 2\n')
        self.git('add', self.source); self.git('commit', '-qm', 'repair retry contract')
        self.head = self.git('rev-parse', 'HEAD')
        original = self.work_path.read_bytes()
        self.write_artifacts(); new_ev = self.read_work()['items'][-1]['evidence']
        self.work_path.write_bytes(original)
        repair_doc = fixtures.yaml.safe_load(repair_path.read_text())
        repair_doc['items'][0]['evidence'].update(comments=new_ev['comments'], delivery=new_ev['delivery'])
        fixtures.dump(repair_path, repair_doc)
        result = self.done(item='F-I01'); self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.run_newman().returncode, 0)
        self.assertEqual(self.explain().returncode, 0)
        result = self.cli('delivery', 'finalize', 'sample')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('F-I01', self.context()['html_metadata']['work_ids'])
        fixtures.write_audit(self.d / 'audits/integration.md', fixtures.audit_metadata(self.d))
        result = self.cli('audit', 'apply', 'sample', '--scope', 'integration', '--mode', 'initial')
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.cli('validate', 'sample')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_html_external_resources_are_rejected(self):
        self.completed(); path = self.html()
        path.write_text(path.read_text().replace('</head>', '<script src="https://external.invalid/x.js"></script></head>'))
        result = self.cli('delivery', 'explain', 'sample', '--skill-file', str(self.skill()), '--invocation', '$eli5 whole-work')
        self.assertEqual(result.returncode, 2)


    def test_finalized_delivery_still_requires_and_completes_independent_audit(self):
        self.completed(); self.finish_phase_audit()
        self.assertEqual(self.read_state()['next_action']['command'], 'finalize')
        packet = self.cli('render', 'finalize', 'sample')
        self.assertEqual(packet.returncode, 0, packet.stderr)
        for token in ('finalization.md', 'P01-I01', 'feature/sample', 'eli5', 'Newman'):
            self.assertIn(token, packet.stdout)
        self.assertEqual(self.run_newman().returncode, 0)
        self.assertEqual(self.explain().returncode, 0)
        self.assertEqual(self.cli('delivery', 'finalize', 'sample').returncode, 0)
        self.assertEqual(self.read_state()['next_action']['command'], 'audit')
        fixtures.write_audit(self.d / 'audits/integration.md', fixtures.audit_metadata(self.d))
        result = self.cli('audit', 'apply', 'sample', '--scope', 'integration', '--mode', 'initial')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.read_state()['project_status'], 'complete')
        result = self.cli('validate', 'sample')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_newman_uses_private_collection_snapshot(self):
        self.completed(); runner = self.fake_newman()
        text = runner.read_text()
        text = text.replace('import sys, pathlib', 'import sys, pathlib\n')
        text = text.replace('pathlib.Path(sys.argv[', 'assert pathlib.Path(sys.argv[2]).parent.name != "sample"\nassert pathlib.Path(sys.argv[2]).name == "collection.json"\npathlib.Path(sys.argv[')
        runner.write_text(text)
        result = self.cli('delivery', 'newman', 'sample', '--branch', 'feature/sample',
                          '--newman-bin', str(runner), '--base-url', 'http://localhost:8080',
                          '--server-sha', self.head, '--safety-note', 'Verified synthetic fixtures and isolated local server.')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_private_symlink_is_rejected_before_file_creation(self):
        self.completed()
        folder = self.root / 'other-private'; folder.mkdir()
        private = self.root / '.devflow/private'; private.symlink_to(folder, target_is_directory=True)
        result = self.run_newman()
        self.assertEqual(result.returncode, 2)
        self.assertIn('symlink', result.stderr)
        self.assertEqual(list(folder.iterdir()), [])

    def test_second_branch_missing_run_blocks_whole_work(self):
        self.completed(); self.run_newman()
        doc = self.read_work(); doc['items'].append(fixtures.v2_item('P01-I02')); fixtures.dump(self.work_path, doc)
        self.git('switch', '-c', 'feature/second')
        self.assertEqual(self.cli('work', 'start', 'sample', 'P01-I02').returncode, 0)
        (self.root / self.source).write_text('# Keep the second branch retry boundary consistent.\ndef execute():\n    return 3\n')
        self.git('add', self.source); self.git('commit', '-qm', 'implement second branch')
        self.head = self.git('rev-parse', 'HEAD'); self.write_artifacts()
        self.assertEqual(self.done(item='P01-I02').returncode, 0)
        ctx = self.context()
        self.assertEqual(ctx['html_metadata']['branches'], ['feature/sample', 'feature/second'])
        self.assertEqual(ctx['html_metadata']['work_ids'], ['P01-I01', 'P01-I02'])
        self.assertEqual(self.explain().returncode, 0)
        result = self.cli('delivery', 'finalize', 'sample')
        self.assertEqual(result.returncode, 2)
        self.assertIn('feature/second', result.stderr)

    def test_malformed_explanation_state_is_a_validation_error(self):
        self.completed(); state = self.read_state()
        state['delivery']['finalization']['explanation'] = 'malformed'
        fixtures.dump(self.state_path, state)
        result = self.cli('status', 'sample')
        self.assertEqual(result.returncode, 2)
        self.assertIn('mapping', result.stderr)

    def test_registered_newman_repair_cannot_bypass_required_plan_review(self):
        self.completed(); self.run_newman(failure=True); self.finish_phase_audit()
        failed = self.read_state()['delivery']['finalization']['runs'][-1]
        repair = fixtures.v2_item('F-I01'); repair['kind'] = 'remediation'
        repair['origin']['findings'] = ['NEWMAN-' + failed['id']]
        repair['references'] = [failed['summary_file']]
        repair['scope']['allowed'] = ['src/service.py']
        fixtures.dump(self.d / 'work/integration.yaml', {'version':2,'phase':'integration','items':[repair]})
        result = self.cli('delivery','triage','sample','--run-id',failed['id'],'--classification','code',
                          '--reason','Accepted API contract and failing unit reproduction confirm the source defect.', '--work-id','F-I01')
        self.assertEqual(result.returncode,0,result.stderr)
        state = self.read_state(); state['plan_review']['required'] = True; state['plan_review']['status'] = 'pending'
        fixtures.dump(self.state_path,state)
        result = self.cli('status','sample','--json'); self.assertEqual(result.returncode,0,result.stderr)
        action = json.loads(result.stdout)['next_action']
        self.assertEqual((action['command'],action['scope']),('audit','plan'))


if __name__ == '__main__':
    names = [name for name in FinalizationTests.__dict__ if name.startswith('test_')]
    result = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(FinalizationTests(name) for name in names))
    raise SystemExit(not result.wasSuccessful())
