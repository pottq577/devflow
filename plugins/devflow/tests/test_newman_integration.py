#!/usr/bin/env python3
"""Optional real-Newman smoke tests against a disposable loopback HTTP server.

No package installation or external service is performed. A missing Newman reports explicit skips.
"""
from __future__ import annotations
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import shutil
import sys
from pathlib import Path
from threading import Thread
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_delivery import DeliveryTests

NEWMAN = shutil.which('newman')

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        payload=b'{"result":"ok"}'
        self.send_response(200); self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(payload))); self.end_headers()
        self.wfile.write(payload)
    def log_message(self, *args):
        pass

@unittest.skipUnless(NEWMAN, 'Real Newman executable is not installed; fixture tests are separate.')
class RealNewmanTests(DeliveryTests):
    def setup_collection(self, expected=200):
        self.start_and_commit(); self.write_artifacts()
        self.collection['item'][0]['event'][0]['script']['exec']=[
            f'pm.test("Status contract", function () {{ pm.response.to.have.status({expected}); }});']
        self.postman.write_text(json.dumps(self.collection))
        result=self.done(); self.assertEqual(result.returncode,0,result.stderr)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=Thread(target=self.server.serve_forever,daemon=True);thread.start()
        def cleanup():
            self.server.shutdown();self.server.server_close();thread.join(timeout=5)
        self.addCleanup(cleanup)
        self.url=f'http://127.0.0.1:{self.server.server_port}'

    def run_real(self):
        return self.cli('delivery','newman','sample','--branch','feature/sample',
                        '--newman-bin',NEWMAN,'--base-url',self.url,'--server-sha',self.head,
                        '--safety-note','Disposable loopback HTTP fixture; synthetic data and zero external integrations.',
                        '--timeout','30','--request-timeout','2')

    def test_real_requests_and_assertions_pass(self):
        self.setup_collection();result=self.run_real()
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        run=self.read_state()['delivery']['finalization']['runs'][-1]
        self.assertEqual(run['counts']['requests'],1)
        self.assertGreaterEqual(run['counts']['assertions'],1)
        self.assertEqual(run['status'],'passed')

    def test_real_wrong_expectation_fails(self):
        self.setup_collection(expected=201);result=self.run_real()
        self.assertEqual(result.returncode,1,result.stdout+result.stderr)
        self.assertEqual(self.read_state()['delivery']['finalization']['runs'][-1]['status'],'failed')

    def test_real_connection_failure_cannot_pass(self):
        self.setup_collection();self.server.shutdown();self.server.server_close()
        result=self.run_real()
        self.assertNotEqual(result.returncode,0)
        self.assertNotEqual(self.read_state()['delivery']['finalization']['runs'][-1]['status'],'passed')

if __name__ == '__main__':
    names=[name for name in RealNewmanTests.__dict__ if name.startswith('test_')]
    result=unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(RealNewmanTests(n) for n in names))
    raise SystemExit(not result.wasSuccessful())
