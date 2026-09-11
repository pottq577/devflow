#!/usr/bin/env python3
"""Optional real-Newman smoke tests against a disposable loopback HTTP server.

No package installation or external service is performed. A missing Newman reports explicit skips.
"""
from __future__ import annotations
import json
import shutil
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_delivery import DeliveryTests

NEWMAN = shutil.which('newman')

@unittest.skipUnless(NEWMAN, 'Real Newman executable is not installed; fixture tests are separate.')
class RealNewmanTests(DeliveryTests):
    def setup_collection(self, expected=200, server_mode='normal'):
        self.start_and_commit(); self.write_artifacts()
        self.collection['item'][0]['event'][0]['script']['exec']=[
            f'pm.test("Status contract", function () {{ pm.response.to.have.status({expected}); }});']
        self.postman.write_text(json.dumps(self.collection))
        result=self.done(); self.assertEqual(result.returncode,0,result.stderr)
        self.server_script = self.root / 'owned-http.txt'
        self.server_script.write_text(
            'from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer\n'
            'import sys, threading\n'
            'mode = sys.argv[2]\n'
            'class Handler(BaseHTTPRequestHandler):\n'
            '    def do_GET(self):\n'
            '        payload = b\'{"result":"ok"}\'\n'
            '        self.send_response(200)\n'
            '        self.send_header("Content-Type", "application/json")\n'
            '        self.send_header("Content-Length", str(len(payload)))\n'
            '        self.end_headers()\n'
            '        self.wfile.write(payload)\n'
            '        if mode == "exit-after-health":\n'
            '            threading.Thread(target=server.shutdown, daemon=True).start()\n'
            '    def log_message(self, *args):\n'
            '        pass\n'
            'server = ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), Handler)\n'
            'server.serve_forever()\n')
        self.server_mode = server_mode
        self.server_command = [sys.executable, str(self.server_script), '18081', server_mode]
        self.url='http://127.0.0.1:18081'

    def run_real(self):
        return self.cli('delivery','newman','sample','--branch','feature/sample',
                        '--newman-bin',NEWMAN,'--base-url',self.url,'--server-sha',self.head,
                        '--server-command',json.dumps(self.server_command),
                        '--readiness-url',self.url + '/health',
                        '--safety-note','Disposable loopback HTTP fixture; synthetic data and zero external integrations.',
                        '--timeout','30','--request-timeout','2')

    def skip_if_sandbox_bind_blocked(self, result):
        run = self.read_state()['delivery']['finalization']['runs'][-1]
        if run['status'] == 'blocked' and 'owned_server_exited' in run['reason_codes']:
            log = self.root / run['server_lifecycle']['log_file']
            if log.is_file() and any(token in log.read_text(errors='replace')
                                     for token in ('Permission denied', 'Operation not permitted')):
                self.skipTest('sandbox denied the owned subprocess HTTP bind; lifecycle fixture is otherwise runnable')
        return result

    def test_real_requests_and_assertions_pass(self):
        self.setup_collection();result=self.skip_if_sandbox_bind_blocked(self.run_real())
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        run=self.read_state()['delivery']['finalization']['runs'][-1]
        self.assertEqual(run['counts']['requests'],1)
        self.assertGreaterEqual(run['counts']['assertions'],1)
        self.assertEqual(run['status'],'passed')

    def test_real_wrong_expectation_fails(self):
        self.setup_collection(expected=201);result=self.skip_if_sandbox_bind_blocked(self.run_real())
        self.assertEqual(result.returncode,1,result.stdout+result.stderr)
        self.assertEqual(self.read_state()['delivery']['finalization']['runs'][-1]['status'],'failed')

    def test_real_connection_failure_cannot_pass(self):
        self.setup_collection(server_mode='exit-after-health')
        result=self.run_real()
        self.assertNotEqual(result.returncode,0)
        self.assertNotEqual(self.read_state()['delivery']['finalization']['runs'][-1]['status'],'passed')

if __name__ == '__main__':
    names=[name for name in RealNewmanTests.__dict__ if name.startswith('test_')]
    result=unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(RealNewmanTests(n) for n in names))
    raise SystemExit(not result.wasSuccessful())
