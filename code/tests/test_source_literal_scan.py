from __future__ import annotations

import sys
import unittest
from pathlib import Path

CODE = Path(__file__).resolve().parents[1]
ROOT = CODE.parent
sys.path.insert(0, str(CODE))

from check_source_literals import scan_source_literals  # noqa: E402


class SourceLiteralScanTests(unittest.TestCase):
    def test_source_has_no_case_evidence_or_evidence_filename_literals(self) -> None:
        self.assertEqual(scan_source_literals(CODE, ROOT / "dataset"), [])


if __name__ == "__main__":
    unittest.main()
