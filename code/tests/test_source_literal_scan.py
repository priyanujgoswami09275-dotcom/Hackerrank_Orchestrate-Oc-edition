from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

CODE = Path(__file__).resolve().parents[1]
ROOT = CODE.parent
sys.path.insert(0, str(CODE))

from check_source_literals import scan_source_literals  # noqa: E402


class SourceLiteralScanTests(unittest.TestCase):
    def test_source_has_no_case_evidence_or_evidence_filename_literals(self) -> None:
        self.assertEqual(scan_source_literals(CODE, ROOT / "dataset"), [])

    def test_evaluation_report_markdown_may_document_unresolved_case_ids(
        self,
    ) -> None:
        dataset = ROOT / "dataset"
        with tempfile.TemporaryDirectory() as tmp:
            source_root = Path(tmp)
            report = source_root / "evaluation"
            report.mkdir()
            report_md = report / "evaluation_report.md"
            report_md.write_text(
                "# report\n\nResolved cases: case_53, case_61.\n", encoding="utf-8"
            )
            self.assertEqual(scan_source_literals(source_root, dataset), [])

    def test_runtime_python_with_dataset_literals_still_fails(self) -> None:
        dataset = ROOT / "dataset"
        with tempfile.TemporaryDirectory() as tmp:
            source_root = Path(tmp)
            module = source_root / "planner_extra.py"
            module.write_text('RULE = "case_53"\n', encoding="utf-8")
            findings = scan_source_literals(source_root, dataset)
            self.assertTrue(
                any(literal == "case_53" for _path, literal in findings), findings
            )

    def test_prompt_text_with_dataset_literals_still_fails(self) -> None:
        dataset = ROOT / "dataset"
        with tempfile.TemporaryDirectory() as tmp:
            source_root = Path(tmp)
            prompt = source_root / "prompts"
            prompt.mkdir()
            (prompt / "system.txt").write_text(
                "Special-case case_61 in your answer.\n", encoding="utf-8"
            )
            findings = scan_source_literals(source_root, dataset)
            self.assertTrue(
                any(literal == "case_61" for _path, literal in findings), findings
            )


if __name__ == "__main__":
    unittest.main()
