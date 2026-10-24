from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

CODE = Path(__file__).resolve().parents[1]
ROOT = CODE.parent
sys.path.insert(0, str(CODE))

from pramaantrace.loader import (  # noqa: E402
    extract_identifiers,
    load_media_evidence,
    load_dataset,
    normalize_sql_file,
    _tesseract_ocr,
    _vision_ocr,
)
from pramaantrace.store import (  # noqa: E402
    CapturedText,
    NormalizedRecord,
    RecordStore,
    parse_timestamp,
)


class RecordStoreTests(unittest.TestCase):
    def test_media_captured_after_cutoff_is_not_opened(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = RecordStore()
            # The file is intentionally absent. A future capture must be
            # rejected from its manifest timestamp before any file access.
            count, processed, skipped, backends = load_media_evidence(
                dataset=root,
                manifest=[
                    {
                        "file_id": "fixture-media",
                        "file_path": "evidence/future-image.png",
                        "captured_at": "2026-05-03T00:00:00Z",
                    }
                ],
                request_rows=[{"audit_at": "2026-05-02T00:00:00Z"}],
                store=store,
                cache_dir=root / "cache",
            )
            self.assertEqual(
                (count, processed, skipped, backends),
                (0, 0, (), ()),
            )
            self.assertFalse((root / "cache").exists())
            self.assertIsNone(
                store.read_text(
                    audit_at="2026-05-02T00:00:00Z",
                    capture_id="fixture-media",
                )
            )

    def test_media_text_cache_avoids_a_second_ocr_call(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = root / "dataset"
            media = dataset / "evidence" / "fixture.png"
            media.parent.mkdir(parents=True)
            media.write_bytes(b"fixture bytes")
            entry = {
                "file_id": "fixture-media",
                "file_path": "evidence/fixture.png",
                "captured_at": "2026-05-01T00:00:00Z",
            }
            request = {"audit_at": "2026-05-02T00:00:00Z"}
            output = {
                str(media.resolve()): {
                    "text": "fixture-media text",
                    "lines": [],
                }
            }
            cache = root / "external-cache"
            with patch(
                "pramaantrace.loader._vision_ocr",
                return_value=(output, "fixture OCR"),
            ) as ocr:
                first_store = RecordStore()
                first = load_media_evidence(
                    dataset=dataset,
                    manifest=[entry],
                    request_rows=[request],
                    store=first_store,
                    cache_dir=cache,
                )
                self.assertEqual(first[3], ("fixture OCR",))
                ocr.assert_called_once()
                ocr.reset_mock()

                second_store = RecordStore()
                second = load_media_evidence(
                    dataset=dataset,
                    manifest=[entry],
                    request_rows=[request],
                    store=second_store,
                    cache_dir=cache,
                )
                self.assertEqual(second[3], ("fixture OCR",))
                ocr.assert_not_called()
                self.assertEqual(
                    second_store.read_text(
                        audit_at=request["audit_at"],
                        capture_id="fixture-media",
                    ).text,
                    "fixture-media text",
                )

    def test_tesseract_fallback_renders_scanned_pdf_pages(self) -> None:
        from PIL import Image

        class FakeBitmap:
            def to_pil(self):
                return Image.new("RGB", (8, 8))

        class FakePage:
            def render(self, *, scale):
                self.scale = scale
                return FakeBitmap()

        fake_tesseract = types.ModuleType("pytesseract")
        fake_tesseract.get_tesseract_version = lambda: "fixture"
        fake_tesseract.image_to_string = lambda image: "portable OCR text"
        fake_pdfium = types.ModuleType("pypdfium2")
        fake_pdfium.PdfDocument = lambda path: [FakePage()]

        with tempfile.TemporaryDirectory() as directory:
            pdf = Path(directory) / "fixture.pdf"
            pdf.write_bytes(b"fixture pdf bytes")
            with patch.dict(
                sys.modules,
                {"pytesseract": fake_tesseract, "pypdfium2": fake_pdfium},
            ):
                result, backend = _tesseract_ocr([pdf])

        self.assertEqual(backend, "Tesseract")
        self.assertEqual(
            result[str(pdf.resolve())]["text"],
            "portable OCR text",
        )

    def test_selectable_pdf_text_is_not_reported_as_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = root / "dataset"
            pdf = dataset / "evidence" / "fixture.pdf"
            pdf.parent.mkdir(parents=True)
            pdf.write_bytes(b"fixture pdf bytes")
            store = RecordStore()
            with (
                patch("pramaantrace.loader._pdf_text", return_value="selectable text"),
                patch("pramaantrace.loader._vision_ocr") as ocr,
            ):
                result = load_media_evidence(
                    dataset=dataset,
                    manifest=[
                        {
                            "file_id": "fixture-pdf",
                            "file_path": "evidence/fixture.pdf",
                            "captured_at": "2026-05-01T00:00:00Z",
                        }
                    ],
                    request_rows=[{"audit_at": "2026-05-02T00:00:00Z"}],
                    store=store,
                    cache_dir=root / "external-cache",
                )

        self.assertEqual(result, (0, 1, (), ("pypdf",)))
        ocr.assert_not_called()
        self.assertEqual(
            store.read_text(
                audit_at="2026-05-02T00:00:00Z",
                capture_id="fixture-pdf",
            ).text,
            "selectable text",
        )

    def test_missing_vision_falls_back_to_tesseract_backend(self) -> None:
        assets = [Path("fixture.png")]
        expected = (
            {str(assets[0].resolve()): {"text": "fallback", "lines": []}},
            "Tesseract",
        )
        with (
            patch("pramaantrace.loader.sys.platform", "darwin"),
            patch("pramaantrace.loader.shutil_which", return_value=None),
            patch("pramaantrace.loader._tesseract_ocr", return_value=expected) as fallback,
        ):
            result = _vision_ocr(assets)

        self.assertEqual(result, expected)
        fallback.assert_called_once_with(assets)

    def test_media_cache_can_be_disabled_for_determinism_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = root / "dataset"
            media = dataset / "evidence" / "fixture.png"
            media.parent.mkdir(parents=True)
            media.write_bytes(b"fixture bytes")
            entry = {
                "file_id": "fixture-media",
                "file_path": "evidence/fixture.png",
                "captured_at": "2026-05-01T00:00:00Z",
            }
            output = {
                str(media.resolve()): {
                    "text": "stable OCR text",
                    "lines": [],
                }
            }
            cache = root / "external-cache"
            with (
                patch.dict("os.environ", {"PRAMAANTRACE_DISABLE_MEDIA_CACHE": "1"}),
                patch(
                    "pramaantrace.loader._vision_ocr",
                    return_value=(output, "fixture OCR"),
                ) as ocr,
            ):
                for _ in range(2):
                    load_media_evidence(
                        dataset=dataset,
                        manifest=[entry],
                        request_rows=[{"audit_at": "2026-05-02T00:00:00Z"}],
                        store=RecordStore(),
                        cache_dir=cache,
                    )

        self.assertEqual(ocr.call_count, 2)
        self.assertFalse(cache.exists())

    def test_media_cache_ignores_legacy_unversioned_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = root / "dataset"
            media = dataset / "evidence" / "fixture.png"
            media.parent.mkdir(parents=True)
            media.write_bytes(b"fixture bytes")
            cache = root / "external-cache"
            cache.mkdir()
            digest = hashlib.sha256(media.read_bytes()).hexdigest()
            (cache / f"{digest}.json").write_text(
                json.dumps(
                    {
                        "sha256": digest,
                        "backend": "old extractor",
                        "text": "stale extraction",
                        "lines": [],
                    }
                ),
                encoding="utf-8",
            )
            output = {
                str(media.resolve()): {
                    "text": "current extraction",
                    "lines": [],
                }
            }
            store = RecordStore()
            with patch(
                "pramaantrace.loader._vision_ocr",
                return_value=(output, "fixture OCR"),
            ) as ocr:
                load_media_evidence(
                    dataset=dataset,
                    manifest=[
                        {
                            "file_id": "fixture-media",
                            "file_path": "evidence/fixture.png",
                            "captured_at": "2026-05-01T00:00:00Z",
                        }
                    ],
                    request_rows=[{"audit_at": "2026-05-02T00:00:00Z"}],
                    store=store,
                    cache_dir=cache,
                )

            ocr.assert_called_once()
            self.assertEqual(
                store.read_text(
                    audit_at="2026-05-02T00:00:00Z",
                    capture_id="fixture-media",
                ).text,
                "current extraction",
            )

    def test_null_sentinels_are_not_indexed_as_identifiers(self) -> None:
        identifiers = extract_identifiers(
            {
                "email": "null",
                "customer_reference": "NULL",
                "user_id": "fixture_user",
            }
        )
        self.assertEqual(identifiers, {"user_ids": ("fixture_user",)})

    def test_every_record_query_applies_audit_cutoff(self) -> None:
        store = RecordStore()
        for capture_id, captured_at in (
            ("fixture-before", "2026-05-01T00:00:00Z"),
            ("fixture-after", "2026-05-03T00:00:00Z"),
        ):
            store.add_record(
                NormalizedRecord(
                    capture_id=capture_id,
                    captured_at=captured_at,
                    topology="fixture",
                    system_id="fixture_service",
                    resource_id="fixture_record",
                    category="FIXTURE",
                )
            )

        visible = store.query(
            audit_at="2026-05-02T00:00:00Z",
            system_id="fixture_service",
        )
        self.assertEqual([record.capture_id for record in visible], ["fixture-before"])
        self.assertEqual(store.record_count(audit_at="2026-05-02T00:00:00Z"), 1)

    def test_text_reads_are_gated_too(self) -> None:
        store = RecordStore()
        store.add_text(
            CapturedText(
                capture_id="fixture-document",
                captured_at="2026-05-03T00:00:00Z",
                file_path="fixture.txt",
                text="fixture",
            )
        )
        self.assertIsNone(
            store.read_text(
                audit_at="2026-05-02T00:00:00Z",
                capture_id="fixture-document",
            )
        )
        self.assertIsNotNone(
            store.read_text(
                audit_at="2026-05-03T00:00:00Z",
                capture_id="fixture-document",
            )
        )

    def test_sql_loader_fails_loudly_for_unmapped_table(self) -> None:
        store = RecordStore()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unmapped.sql"
            path.write_text(
                "CREATE TABLE unexpected_table (resource_id TEXT);",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "unmapped SQL table"):
                normalize_sql_file(
                    store,
                    evidence_id="fixture-capture",
                    captured_at="2026-05-01T00:00:00Z",
                    path=path,
                )


class DatasetLoaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle = load_dataset(ROOT)

    def test_loads_structured_and_cutoff_eligible_media_artifacts(self) -> None:
        self.assertEqual(self.bundle.evidence_file_count, 94)
        self.assertEqual(self.bundle.loaded_evidence_count, 79)
        self.assertEqual(self.bundle.skipped_multimodal, ())
        self.assertEqual(self.bundle.media_processed_count, 15)
        self.assertGreater(self.bundle.media_record_count, 0)
        self.assertIn("Apple Vision", self.bundle.media_backends)
        self.assertIn("pypdf", self.bundle.media_backends)
        media_entries = [
            row
            for row in self.bundle.tables["evidence_files.csv"]
            if Path(row["file_path"]).suffix.casefold()
            in {".png", ".pdf", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"}
        ]
        self.assertEqual(len(media_entries), 15)
        self.assertTrue(
            all(
                self.bundle.store.read_text(
                    audit_at="2026-10-24T00:00:00Z",
                    capture_id=row["file_id"],
                )
                is not None
                for row in media_entries
            )
        )
        self.assertEqual(
            len(self.bundle.tables["deletion_requests.csv"]),
            518,
        )
        self.assertEqual(
            len(self.bundle.tables["user_identities.csv"]),
            850,
        )
        self.assertGreater(
            self.bundle.store.record_count(audit_at="2026-10-24T00:00:00Z"),
            0,
        )

    def test_latest_cutoff_never_returns_a_capture_from_the_future(self) -> None:
        cutoff = "2026-09-01T00:00:00Z"
        visible = self.bundle.store.query(audit_at=cutoff)
        self.assertTrue(
            all(parse_timestamp(record.captured_at) <= parse_timestamp(cutoff) for record in visible)
        )

    def test_empty_inventory_collection_is_preserved_as_a_gated_scope(self) -> None:
        scopes = self.bundle.store.query_scopes(
            audit_at="2026-09-07T00:00:00Z",
            system_id="account_service",
            category="USER_PROFILE",
        )
        self.assertTrue(scopes)
        latest_scope = scopes[-1]
        records = self.bundle.store.query(
            audit_at="2026-09-07T00:00:00Z",
            capture_id=latest_scope.capture_id,
            system_id="account_service",
            category="USER_PROFILE",
        )
        self.assertEqual(records, [])


if __name__ == "__main__":
    unittest.main()
