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

    def test_a_legacy_branch_without_the_structure_digest_still_validates(self) -> None:
        """A 0.10.2 record stays valid: the optional digest is absent, not forged."""
        self.prepare()
        state = self.read_state()
        recorded = state["delivery"]["branches"]["feature/sample"].pop(
            "postman_structure_sha256"
        )
        fixtures.dump(self.state_path, state)
        doc = self.read_work()
        doc["items"][0]["evidence"]["delivery"].pop("postman_structure_sha256")
        fixtures.dump(self.work_path, doc)
        state_bytes = self.state_path.read_bytes()
        work_bytes = self.work_path.read_bytes()
        for args in (
            ("delivery", "check", "sample"),
            ("validate", "sample"),
            ("delivery", "check", "sample", "--final"),
        ):
            result = self.cli(*args)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(state_bytes, self.state_path.read_bytes())
            self.assertEqual(work_bytes, self.work_path.read_bytes())
        self.assertNotIn(
            "postman_structure_sha256",
            self.read_state()["delivery"]["branches"]["feature/sample"],
        )
        self.finish_phase_audit()
        self.assertEqual(work_bytes, self.work_path.read_bytes())
        self.assertEqual(
            self.read_state()["delivery"]["branches"]["feature/sample"].get(
                "postman_structure_sha256"
            ),
            None,
        )
        refreshed = self.cli("delivery", "refresh", "sample", "--branch", "feature/sample")
        self.assertEqual(refreshed.returncode, 0, refreshed.stderr)
        self.assertEqual(
            self.read_state()["delivery"]["branches"]["feature/sample"][
                "postman_structure_sha256"
            ],
            recorded,
        )
        self.assertEqual(self.cli("validate", "sample").returncode, 0)

    def test_a_recorded_structure_digest_is_still_compared(self) -> None:
        """Absence is tolerated; a wrong recorded value and a tampered collection are not."""
        self.prepare()
        for forged_value in ("0" * 64, None, ""):
            state = self.read_state()
            state["delivery"]["branches"]["feature/sample"][
                "postman_structure_sha256"
            ] = forged_value
            fixtures.dump(self.state_path, state)
            forged = self.cli("delivery", "check", "sample")
            self.assertEqual(forged.returncode, 2, forged.stdout)
        self.assertEqual(self.cli("validate", "sample").returncode, 1)
        state = self.read_state()
        state["delivery"]["branches"]["feature/sample"].pop("postman_structure_sha256")
        fixtures.dump(self.state_path, state)
        self.assertEqual(self.cli("delivery", "check", "sample").returncode, 0)
        restored = self.cli("delivery", "refresh", "sample", "--branch", "feature/sample")
        self.assertEqual(restored.returncode, 0, restored.stderr)
        self.collection["item"][0]["request"]["header"] = [{"key": "X-Trace", "value": "1"}]
        self.postman.write_text(json.dumps(self.collection, indent=2))
        tampered = self.cli("delivery", "check", "sample")
        self.assertEqual(tampered.returncode, 2, tampered.stdout)
        self.assertIn("stale postman_sha256", tampered.stderr)

    def test_a_missing_required_artifact_hash_is_still_rejected(self) -> None:
        self.prepare()
        state = self.read_state()
        state["delivery"]["branches"]["feature/sample"].pop("template_sha256")
        fixtures.dump(self.state_path, state)
        result = self.cli("delivery", "check", "sample")
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("requires template_sha256", result.stderr)

    def test_legacy_structure_digest_absence_validates_on_stacked_branches(self) -> None:
        self.start_and_commit()
        self.write_artifacts()
        self.assertEqual(self.done().returncode, 0)
        document = self.read_work()
        document["items"].append(fixtures.v2_item("P01-I02"))
        fixtures.dump(self.work_path, document)
        self.git("switch", "-c", "feature/second")
        self.assertEqual(self.cli("work", "start", "sample", "P01-I02").returncode, 0)
        (self.root / self.source).write_text(
            "# Preserve retry identity across stacked branches.\ndef execute():\n    return 2\n"
        )
        self.git("add", self.source)
        self.git("commit", "-qm", "second branch")
        self.head = self.git("rev-parse", "HEAD")
        self.write_artifacts()
        self.assertEqual(self.done(item="P01-I02").returncode, 0)
        state = self.read_state()
        for record in state["delivery"]["branches"].values():
            record.pop("postman_structure_sha256")
        fixtures.dump(self.state_path, state)
        document = self.read_work()
        for item in document["items"]:
            (item.get("evidence") or {}).get("delivery", {}).pop(
                "postman_structure_sha256", None
            )
        fixtures.dump(self.work_path, document)
        state_bytes = self.state_path.read_bytes()
        work_bytes = self.work_path.read_bytes()
        for args in (
            ("delivery", "check", "sample"),
            ("validate", "sample"),
            ("delivery", "check", "sample", "--final"),
        ):
            result = self.cli(*args)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(state_bytes, self.state_path.read_bytes())
            self.assertEqual(work_bytes, self.work_path.read_bytes())


if __name__ == "__main__":
    unittest.main(verbosity=2)
