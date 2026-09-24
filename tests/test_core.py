import unittest

from building_code_demo.core import Clause, search


class SearchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clauses = [
            Clause("6.6.1", "阳台临空部位应设置防护栏杆，栏杆高度应符合要求。", 16, 16),
            Clause("5.6.5", "公共厕所隔间内开门时，通道净宽应符合要求。", 15, 15),
            Clause("4.3.6", "建筑基地内机动车道路应符合规定。", 13, 13),
        ]

    def test_topic_query_finds_relevant_clause(self) -> None:
        hits = search(self.clauses, "阳台栏杆高度")
        self.assertEqual(hits[0].clause.number, "6.6.1")

    def test_exact_clause_number_wins(self) -> None:
        hits = search(self.clauses, "请查 5.6.5 条")
        self.assertEqual(hits[0].clause.number, "5.6.5")

    def test_missing_clause_is_not_replaced_by_nearby_one(self) -> None:
        self.assertEqual(search(self.clauses, "6.6.9 条"), [])


if __name__ == "__main__":
    unittest.main()
