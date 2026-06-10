import csv
import unittest
from pathlib import Path

from app.modules.deterministic_solver import solve_deterministic
from evaluate_pipeline import compare_prediction


DATASET = Path("dataset_2/Physics_Problems_Text_Only.csv")


class DeterministicSolverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with DATASET.open("r", encoding="utf-8-sig", newline="") as f:
            cls.rows = {row["id"]: row for row in csv.DictReader(f)}

    def assert_solver_matches(self, sample_id: str):
        row = self.rows[sample_id]
        result = solve_deterministic(row["question"])
        self.assertIsNotNone(result, sample_id)
        final = f"{result.answer} {result.unit}".strip()
        comparison = compare_prediction(final, row["answer"], row["unit"], 1e-2, 1e-9)
        self.assertTrue(comparison[4], f"{sample_id}: {final} != {row['answer']} {row['unit']}")

    def test_dt_regression_cases(self):
        for sample_id in [
            "DT002",
            "DT003",
            "DT004",
            "DT005",
            "DT006",
            "DT007",
            "DT008",
            "DT019",
            "DT020",
            "DT025",
            "DT029",
            "DT033",
            "DT035",
        ]:
            with self.subTest(sample_id=sample_id):
                self.assert_solver_matches(sample_id)

    def test_low_topic_formula_regression_cases(self):
        for sample_id in [
            "TD001",
            "TD002",
            "TD003",
            "TD004",
            "TD005",
            "TD007",
            "TD008",
            "TD009",
            "TD011",
            "TD015",
            "TD016",
            "TD017",
            "TD018",
            "THCB003",
            "THCB008",
            "THCB066",
            "THCB068",
            "THCB070",
            "THCB072",
            "THCB075",
            "DDT131",
            "DDT134",
            "DDT139",
            "DDT143",
            "DDT146",
            "DDT149",
            "LD001",
            "LD004",
            "LD005",
            "LD006",
            "LD007",
            "LD010",
            "LD012",
            "LD014",
            "LD018",
            "LD024",
            "LD025",
            "LD026",
            "LD030",
            "LD031",
            "LD032",
            "LD033",
            "LD034",
            "LD035",
            "LD037",
            "LD038",
            "DDT157",
            "DDT158",
            "DDT203",
            "DDT204",
            "DDT209",
        ]:
            with self.subTest(sample_id=sample_id):
                self.assert_solver_matches(sample_id)


if __name__ == "__main__":
    unittest.main()
