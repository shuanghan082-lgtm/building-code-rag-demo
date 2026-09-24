import json
from pathlib import Path
import tempfile
import unittest

from building_code_demo.core import Clause
from building_code_demo.scan_catalog import FULL_SCAN_SHA256, ScanCatalog
from building_code_demo.service import DemoService


class ScanCatalogTests(unittest.TestCase):
    def setUp(self):
        self.payload = {
            "status": "unverified_ocr_observations",
            "source": {"sha256": FULL_SCAN_SHA256, "pdf_pages": 24},
            "pages": [
                {
                    "pdf_page": page,
                    "candidate_clause_numbers": ["6.6.1"] if page == 23 else [],
                    "passes": {"raw_2x": {"rows": [{"text": "阳台栏杆"}] if page == 23 else []}},
                }
                for page in range(1, 25)
            ],
        }

    def test_locates_original_page_without_returning_ocr_body(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "scan.ocr.json"
            path.write_text(json.dumps(self.payload), encoding="utf-8")
            catalog = ScanCatalog.load(path)
            self.assertEqual(catalog.search("阳台栏杆")[0].page.pdf_page, 23)
            self.assertEqual(catalog.search("6.6.1")[0].page.pdf_page, 23)
            self.assertEqual(catalog.search("6.6.9"), [])
            result = catalog.hit_dict(catalog.search("阳台栏杆")[0])
            self.assertEqual(result["status"], "unverified_ocr_page_locator_only")
            self.assertNotIn("text", result)

    def test_rejects_incomplete_or_wrong_source(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "scan.ocr.json"
            self.payload["pages"].pop()
            path.write_text(json.dumps(self.payload), encoding="utf-8")
            with self.assertRaises(ValueError):
                ScanCatalog.load(path)

    def test_web_scan_endpoint_never_uses_answer_model(self):
        try:
            import httpx  # noqa: F401
            from fastapi.testclient import TestClient
        except ImportError:
            self.skipTest("optional web test dependencies are not installed")
        from building_code_demo.webapp import create_app

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "scan.ocr.json"
            path.write_text(json.dumps(self.payload), encoding="utf-8")
            catalog = ScanCatalog.load(path)
        service = DemoService([Clause("6.6.1", "阳台栏杆", 16, 16)], [16], "test", "lexical", scan_catalog=catalog)
        client = TestClient(create_app(service))
        self.assertTrue(client.get("/api/info").json()["scan_locator_available"])
        result = client.post("/api/scan", json={"question": "阳台栏杆"})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["hits"][0]["pdf_page"], 23)
        self.assertNotIn("answer", result.json())


if __name__ == "__main__":
    unittest.main()
