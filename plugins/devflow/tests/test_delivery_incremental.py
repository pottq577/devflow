#!/usr/bin/env python3
"""Cumulative PR/Postman refresh: provenance always moves, request structure only on API change."""

from __future__ import annotations

import json
import unittest

import test_delivery
import test_devflow as fixtures


class IncrementalDeliveryTests(test_delivery.DeliveryFixtureMixin, unittest.TestCase):
    def prepare(self):
        self.start_and_commit()
        self.write_artifacts()
        self.assertEqual(self.done().returncode, 0)
        return self.read_work()

    def add_second_work(self, *, endpoints, name="Post sample", url="{{baseUrl}}/api/post"):
        doc = self.read_work()
        doc["items"].append(fixtures.v2_item("P01-I02"))
        fixtures.dump(self.work_path, doc)
        self.assertEqual(
            self.cli("work", "start", "sample", "P01-I02").returncode, 0
        )
        (self.root / self.source).write_text(
            "# Keep retries inside one transaction so duplicate submissions share a result.\n"
            "def execute():\n    return 2\n"
        )
        self.git("add", self.source)
        self.git("commit", "-qm", "second change")
        self.head = self.git("rev-parse", "HEAD")
        self.write_artifacts(endpoints=endpoints)
        if name:
            self.collection["item"].append(
                {
                    "name": name,
                    "request": {"method": "POST", "url": url, "header": []},
                    "event": [
                        {
                            "listen": "test",
                            "script": {
                                "type": "text/javascript",
                                "exec": ['pm.test("Status", () => pm.response.to.have.status(200));'],
                            },
                        }
                    ],
                }
            )
            self.metadata = {
                "branch": self.metadata["branch"],
                "base_sha": self.base,
                "head_sha": self.head,
            }
            self.collection["info"]["_devflow"] = self.metadata
        self.postman.write_text(json.dumps(self.collection, indent=2))
        result = self.done(item="P01-I02")
        return result

    def test_unchanged_api_surface_keeps_structure_and_moves_provenance(self) -> None:
        self.prepare()
        record = self.read_state()["delivery"]["branches"]["feature/sample"]
        structure = record["postman_structure_sha256"]
        head = record["head_sha"]
        result = self.add_second_work(endpoints=["GET /api/sample"], name=None)
        self.assertEqual(result.returncode, 0, result.stderr)
        updated = self.read_state()["delivery"]["branches"]["feature/sample"]
        self.assertEqual(updated["postman_structure_sha256"], structure)
        self.assertNotEqual(updated["head_sha"], head)
        self.assertNotEqual(updated["pr_sha256"], record["pr_sha256"])
        self.assertEqual(updated["work_ids"], ["P01-I01", "P01-I02"])
        self.assertEqual(self.cli("validate", "sample").returncode, 0)

    def test_changed_api_surface_must_be_covered_by_a_request(self) -> None:
        self.prepare()
        result = self.add_second_work(endpoints=["GET /api/sample", "POST /api/post"], name=None)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("declared endpoint coverage is missing: POST /api/post", result.stderr)

    def test_rewritten_collection_without_a_declared_change_is_refused(self) -> None:
        self.prepare()
        result = self.add_second_work(endpoints=["GET /api/sample"], name="Post sample")
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("api_endpoints stayed the", result.stderr)
        self.assertEqual(
            self.read_state()["delivery"]["branches"]["feature/sample"]["work_ids"],
            ["P01-I01"],
        )

    def test_declared_endpoint_change_with_refreshed_requests_passes(self) -> None:
        self.prepare()
        result = self.add_second_work(
            endpoints=["GET /api/sample", "POST /api/post"]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        record = self.read_state()["delivery"]["branches"]["feature/sample"]
        self.assertNotEqual(
            record["postman_structure_sha256"],
            self.read_work()["items"][0].get("evidence", {}).get("postman_structure_sha256", ""),
        )
        self.assertEqual(self.cli("validate", "sample").returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)