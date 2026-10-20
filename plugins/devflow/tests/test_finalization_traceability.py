#!/usr/bin/env python3
"""Final ELI5 requirement provenance, completion gates and legacy compatibility."""
from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import test_requirements as requirement_fixture
import devflow_explanation_requirements as eli_requirements
import devflow_report as report


class ELI5RequirementTraceabilityTests(unittest.TestCase):
    def setUp(self):
        # Reuse P04's real git/source/PLAN/WORK/phase-audit fixture without
        # inventing a second model of what "verified" means.
        self.fixture = requirement_fixture.RequirementsTests(methodName="test_fully_evidenced_is_implemented_aligned_verified")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.d = self.fixture.d
        self.root = self.fixture.root
        self.fixture.state["traceability_version"] = 1

    def docs(self):
        grouped = {}
        for work_id, (path, item) in self.fixture.index.items():
            grouped.setdefault(path, []).append({"id": work_id, **item})
        return {path: {"phase": "01", "items": items} for path, items in grouped.items()}

    def derive(self):
        return eli_requirements.derive(self.root, self.d, self.fixture.state, self.docs())

    def test_eligible_scope_matches_p05_snapshot_exactly(self):
        view = self.derive()
        self.assertEqual(view["blockers"], [])
        self.assertEqual(view["snapshot_sha256"], hashlib.sha256(
            report.render_json(self.fixture.snap()).encode("utf-8")
        ).hexdigest())
        self.assertEqual([row["id"] for row in view["requirements"]], ["REQ-001", "RULE-002"])
        self.assertEqual(view["summary"]["implemented"], 2)
        self.assertEqual(view["requirements"][0]["verification"], "passed")

    def test_repeatable_without_writing_artifacts(self):
        original = (self.d / "PRD.md").read_bytes()
        a, b = self.derive(), self.derive()
        self.assertEqual(a, b)
        self.assertEqual((self.d / "PRD.md").read_bytes(), original)
        self.assertFalse((self.d / "REQUIREMENTS_STATUS.json").exists())

    def test_legacy_domains_do_not_gain_new_eli5_contract(self):
        self.fixture.state.pop("traceability_version")
        self.assertIsNone(self.derive())
        self.fixture.state["traceability_version"] = 0
        self.assertIsNone(self.derive())

    def test_provisional_policy_blocks_product_completion_only(self):
        self.fixture.policy_event("assume")
        self.fixture.index["P01-I02"][1]["origin"]["policy_assumptions"] = ["DEC-P01"]
        view = self.derive()
        self.assertEqual(view["requirements"][1]["implementation"], "implemented")
        self.assertEqual(view["requirements"][1]["verification"], "passed")
        self.assertTrue(any("RULE-002: policy decision=provisional" in p for p in view["blockers"]))

    def test_approved_deviation_is_not_mistaken_for_alignment(self):
        self.fixture.policy_event("assume")
        self.fixture.index["P01-I02"][1]["origin"]["policy_assumptions"] = ["DEC-P01"]
        self.fixture.set_compare("P01-I02", "RULE-002", "policy_deviation", "L4-L5")
        self.fixture.policy_event("approve")
        view = self.derive()
        self.assertFalse(any("policy decision=" in e for e in view["blockers"]))
        self.assertEqual(view["requirements"][1]["difference"], "policy_deviation")
        self.assertEqual(view["requirements"][1]["decision"], "approved")

    def test_policy_rejection_blocks(self):
        self.fixture.policy_event("assume")
        self.fixture.index["P01-I02"][1]["origin"]["policy_assumptions"] = ["DEC-P01"]
        self.fixture.policy_event("reject", approved_policy="Use original", corrective_work=["P02-I01"], matches_assumption=False)
        self.assertTrue(any("RULE-002: policy decision=rejected" in x for x in self.derive()["blockers"]))

    def test_missing_comparison_is_not_approved_alignment(self):
        self.fixture.index["P01-I01"][1]["origin"].pop("original_comparison")
        self.assertIn("REQ-001: original comparison has no verified evidence", self.derive()["blockers"])

    def test_unfinished_and_unverified_work_block(self):
        self.fixture.index["P01-I01"][1]["status"] = "ready"
        view = self.derive()
        self.assertIn("REQ-001: implementation=not_implemented", view["blockers"])
        self.assertIn("REQ-001: verification=not_run", view["blockers"])

    def test_stale_source_code_blocks(self):
        (self.root / "service.py").write_text("def create(): return 999\n", encoding="utf-8")
        view = self.derive()
        self.assertIn("REQ-001: verification=stale", view["blockers"])
        self.assertIn("REQ-001: original comparison has no verified evidence", view["blockers"])

    def test_source_snapshot_tampering_is_blocking(self):
        (self.d / "sources/v1/original.md").write_text("changed", encoding="utf-8")
        view = self.derive()
        self.assertTrue(any("captured sources are invalid" in x for x in view["blockers"]))

    def test_missing_source_directory_is_blocking(self):
        import shutil
        shutil.rmtree(self.d / "sources")
        self.assertTrue(any("captured original/context" in x for x in self.derive()["blockers"]))

    def test_gap_in_plan_cannot_be_complete(self):
        (self.d / "PLAN.md").unlink()
        view = self.derive()
        self.assertTrue(any("traceability gap: prd_without_plan" in x for x in view["blockers"]))

    def test_audit_evidence_hash_changes_even_if_verdict_does_not(self):
        before = self.derive()
        audit = self.d / "audits/phase-01.md"
        audit.write_text(audit.read_text() + "\nObserved additional safety evidence.\n", encoding="utf-8")
        after = self.derive()
        self.assertEqual(before["snapshot_sha256"], after["snapshot_sha256"])
        self.assertNotEqual(before["sha256"], after["sha256"])
        self.assertEqual(after["blockers"], [])

    def test_integration_audit_not_pinned_before_it_exists(self):
        before = self.derive()["sha256"]
        audit = self.d / "audits/integration.md"
        audit.write_text("integration pass will be applied after finalization", encoding="utf-8")
        self.fixture.state["integration"] = {"status": "verified", "audit_file": "audits/integration.md"}
        self.assertEqual(self.derive()["sha256"], before)

    def test_missing_required_audit_is_detected(self):
        (self.d / "audits/phase-01.md").unlink()
        view = self.derive()
        self.assertTrue(any("audit evidence missing" in x for x in view["blockers"]))
        self.assertTrue(any("verification=" in x for x in view["blockers"]))

    def test_high_risk_without_work_review_is_not_passed(self):
        item = self.fixture.index["P01-I01"][1]
        item["risk"] = {"level": "high"}
        item["review"] = {"status": "skipped", "required": False}
        self.assertIn("REQ-001: verification=pending_review", self.derive()["blockers"])

    def test_audit_path_traversal_is_never_read(self):
        self.fixture.state["phases"]["01"]["audit_file"] = "../../outside.md"
        view = self.derive()
        self.assertTrue(any("audit evidence missing or unsafe" in x for x in view["blockers"]))


    def html_table(self, view=None, *, show_rows=True):
        import html
        view = view or self.derive()
        rows = []
        if show_rows:
            for record in view["requirements"]:
                attrs = " ".join(
                    f'data-{key}="{html.escape(str(record[key]), quote=True)}"'
                    for key in ("implementation", "difference", "decision", "verification")
                )
                rows.append(
                    f'<tr data-requirement-id="{record["id"]}" {attrs}>'
                    f'<td>{record["id"]}</td><td>{record["implementation"]}</td></tr>'
                )
        return (
            '<html><body><section id="devflow-requirements" '
            f'data-snapshot-sha256="{view["snapshot_sha256"]}" '
            f'data-evidence-sha256="{view["sha256"]}"><table>'
            + "".join(rows) + '</table></section></body></html>'
        )

    def test_eli5_table_matches_exact_four_axis_statuses(self):
        view = self.derive()
        self.assertEqual(eli_requirements.html_errors(self.html_table(view), view), [])

    def test_eli5_rejects_missing_row(self):
        view = self.derive()
        self.assertTrue(any("row is missing" in e for e in
                            eli_requirements.html_errors(self.html_table(view, show_rows=False), view)))

    def test_eli5_rejects_wrong_axis_even_when_metadata_hash_matches(self):
        view = self.derive()
        html = self.html_table(view).replace('data-verification="passed"', 'data-verification="unknown"', 1)
        self.assertTrue(any("verification disagrees" in e for e in
                            eli_requirements.html_errors(html, view)))

    def test_eli5_rejects_old_report_snapshot_hash(self):
        view = self.derive()
        html = self.html_table(view).replace(view["snapshot_sha256"], "a" * 64)
        self.assertTrue(any("P05 JSON" in e for e in eli_requirements.html_errors(html, view)))

    def test_eli5_rejects_stale_audit_hash(self):
        view = self.derive()
        html = self.html_table(view).replace(view["sha256"], "b" * 64)
        self.assertTrue(any("audit/source evidence hash is stale" in e for e in
                            eli_requirements.html_errors(html, view)))

    def test_eli5_rejects_duplicate_rows(self):
        view = self.derive()
        html = self.html_table(view)
        row = html.split('<tr data-requirement-id="REQ-001"')[1].split('</tr>')[0]
        duplicate = '<tr data-requirement-id="REQ-001"' + row + '</tr>'
        html = html.replace('</table>', duplicate + '</table>')
        self.assertTrue(any("duplicate requirement row" in e for e in
                            eli_requirements.html_errors(html, view)))

    def test_eli5_rejects_hidden_or_unlabeled_requirements(self):
        view = self.derive()
        html = self.html_table(view).replace('<td>REQ-001</td>', '<td>Hidden ID</td>')
        self.assertTrue(any("visibly labeled" in e for e in eli_requirements.html_errors(html, view)))

    def test_eli5_hidden_script_text_is_not_visible_evidence(self):
        view = self.derive()
        html = self.html_table(view).replace(
            '<td>REQ-001</td>', '<td><script>REQ-001</script>Not labeled</td>'
        )
        self.assertTrue(any("visibly labeled" in e for e in eli_requirements.html_errors(html, view)))

    def test_eli5_rejects_missing_section_or_extra_unmapped_id(self):
        view = self.derive()
        self.assertTrue(any("one visible" in e for e in
                            eli_requirements.html_errors('<html><body>REQ-001</body></html>', view)))
        html = self.html_table(view).replace('data-requirement-id="REQ-001"',
                                             'data-requirement-id="REQ-999"')
        self.assertTrue(any("unexpected requirement row" in e for e in
                            eli_requirements.html_errors(html, view)))


class FinalizationRuntimeIntegrationTests(unittest.TestCase):
    """Exercise actual finalization.scope/HTML/receipt when the full plugin is present."""

    def setUp(self):
        try:
            import devflow_finalization as runtime
        except ModuleNotFoundError:
            self.skipTest("full DevFlow runtime is not mounted in sparse fixture")
        self.runtime = runtime
        self.fixture = requirement_fixture.RequirementsTests(
            methodName="test_fully_evidenced_is_implemented_aligned_verified"
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.d = self.fixture.d
        self.fixture.state.update({
            "traceability_version": 1,
            "baseline_sha": self.fixture.base,
            "delivery": {"version": 1, "branches": {},
                         "finalization": runtime.default_policy()},
        })

    def docs(self):
        items = [
            {"id": work_id, **item}
            for work_id, (_, item) in self.fixture.index.items()
        ]
        return {self.d / "work/phase-01.yaml": {"phase": "01", "items": items}}

    def ctx(self):
        return self.runtime.scope(self.root, "example", self.fixture.state, self.docs(), self.d)

    def html(self, ctx):
        import html as h
        view = ctx["requirements_evidence"]
        table_rows = []
        for row in view["requirements"]:
            attrs = " ".join(
                f'data-{axis}="{h.escape(row[axis], quote=True)}"'
                for axis in eli_requirements.AXES
            )
            table_rows.append(
                f'<tr data-requirement-id="{row["id"]}" {attrs}>'
                f'<td>{row["id"]}</td><td>{row["implementation"]}</td></tr>'
            )
        return (
            '<!doctype html><html><head><title>Implementation</title></head><body>'
            '<!-- devflow-explanation: ' + json.dumps(ctx["html_metadata"]) + ' -->'
            '<p>This is a whole-work explanation with actual commits and acceptance '
            'criteria evidenced by tests and audits for P01-I01 and P01-I02. '
            'Implementation and scope are reproducible from the source artifacts.</p>'
            f'<section id="devflow-requirements" data-snapshot-sha256="{view["snapshot_sha256"]}" '
            f'data-evidence-sha256="{view["sha256"]}">'
            '<h2>Requirements</h2><table>' + "".join(table_rows) + '</table></section>'
            '</body></html>'
        )

    def write_html(self, content):
        ctx = self.ctx()
        path = self.root / ctx["html_file"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_scope_binds_canonical_snapshot_and_metadata(self):
        ctx = self.ctx()
        self.assertEqual(ctx["html_metadata"]["requirements_sha256"],
                         ctx["requirements_evidence"]["sha256"])
        self.assertEqual(ctx["html_metadata"]["requirements_count"], 2)
        self.assertEqual(self.runtime.render_scope(ctx)["requirements_evidence"]["blockers"], [])
        compact = self.runtime.render_scope(ctx, include_requirement_rows=False)["requirements_evidence"]
        self.assertNotIn("requirements", compact)
        self.assertEqual(compact["sha256"], ctx["requirements_evidence"]["sha256"])

    def test_html_requires_all_reciprocal_requirement_rows(self):
        ctx = self.ctx()
        self.write_html(self.html(ctx))
        self.runtime.inspect_html(self.root, ctx)
        invalid = self.html(ctx).replace('data-decision="not_required"',
                                         'data-decision="approved"', 1)
        self.write_html(invalid)
        with self.assertRaisesRegex(ValueError, "disagrees with P04"):
            self.runtime.inspect_html(self.root, ctx)

    def test_changed_phase_audit_invalidates_recorded_html(self):
        ctx = self.ctx()
        self.write_html(self.html(ctx))
        self.runtime.inspect_html(self.root, ctx)
        audit = self.d / "audits/phase-01.md"
        audit.write_text(audit.read_text() + "\nNew evidence.\n", encoding="utf-8")
        refreshed = self.ctx()
        self.assertNotEqual(ctx["html_metadata"]["scope_sha256"],
                            refreshed["html_metadata"]["scope_sha256"])
        with self.assertRaises(ValueError):
            self.runtime.inspect_html(self.root, refreshed)

    def test_unapproved_policy_blocks_finalization_before_eli5(self):
        self.fixture.policy_event("assume")
        self.fixture.index["P01-I02"][1]["origin"]["policy_assumptions"] = ["DEC-P01"]
        problems = self.runtime.final_errors(
            self.root, "example", self.fixture.state, self.docs(), self.d,
            require_explanation=False,
        )
        self.assertTrue(any("requirement final gate" in p for p in problems))

    def test_legacy_scope_and_html_stay_backward_compatible(self):
        self.fixture.state.pop("traceability_version")
        ctx = self.ctx()
        self.assertNotIn("requirements_sha256", ctx["html_metadata"])
        self.assertNotIn("requirements_evidence", ctx)
        self.write_html(
            '<!doctype html><html><head><title>Implementation</title></head><body>'
            '<!-- devflow-explanation: ' + json.dumps(ctx["html_metadata"]) + ' -->'
            '<h1>Complete implementation</h1><p>This verified whole-work explanation '
            'includes P01-I01 and P01-I02 and the tests, commits, and scope evidence '
            'for both work items across the entire verified domain.</p></body></html>'
        )
        self.runtime.inspect_html(self.root, ctx)


if __name__ == "__main__":
    unittest.main(verbosity=2)
