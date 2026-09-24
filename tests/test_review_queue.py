import unittest

from building_code_demo.review_queue import build_rows


class ReviewQueueTests(unittest.TestCase):
    def test_candidates_stay_pending_even_when_all_passes_recognize_number(self) -> None:
        observations = {
            "status": "unverified_ocr_observations",
            "source": {"sha256": "example"},
            "pages": [{
                "pdf_page": 14,
                "candidate_clause_numbers": ["5.2.1", "5.2.2"],
                "passes": {
                    "one": {"candidate_clause_numbers": ["5.2.2"]},
                    "two": {"candidate_clause_numbers": ["5.2.1", "5.2.2"]},
                },
            }],
        }
        rows = build_rows(observations)
        self.assertEqual([row["candidate_clause_number"] for row in rows], ["5.2.1", "5.2.2"])
        self.assertEqual([row["number_check_needed"] for row in rows], ["yes", "no"])
        self.assertTrue(all(row["review_status"] == "pending" for row in rows))
        self.assertTrue(all(row["body_checked"] == "no" for row in rows))

    def test_rejects_missing_source_fingerprint(self) -> None:
        with self.assertRaises(ValueError):
            build_rows({"status": "unverified_ocr_observations", "source": {}, "pages": []})


if __name__ == "__main__":
    unittest.main()
