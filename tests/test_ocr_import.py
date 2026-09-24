import unittest

from building_code_demo.ocr_import import CLAUSE_START, page_selection


class OCRImportTests(unittest.TestCase):
    def test_page_selection_rejects_invalid_page(self) -> None:
        self.assertEqual(page_selection("14,12,14", 24), [12, 14])
        with self.assertRaises(ValueError):
            page_selection("0", 24)
        with self.assertRaises(ValueError):
            page_selection("25", 24)

    def test_candidate_clause_number_must_start_a_line(self) -> None:
        self.assertEqual(CLAUSE_START.match("6.6.1 阳台").group(1), "6.6.1")
        self.assertIsNone(CLAUSE_START.match("见 6.6.1 条"))


if __name__ == "__main__":
    unittest.main()
