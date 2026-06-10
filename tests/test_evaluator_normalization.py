import unittest

from evaluate_pipeline import compare_prediction, parse_numeric


class EvaluatorNormalizationTests(unittest.TestCase):
    def test_scientific_notation_variants_match(self):
        result = compare_prediction("6.3*10^6 V/m", "6300000", "V/m", 5e-3, 1e-9)
        self.assertTrue(result[4])

    def test_textbook_power_notation_matches(self):
        self.assertEqual(parse_numeric("45.10^{5}"), 4_500_000)

    def test_unit_converted_length_matches(self):
        result = compare_prediction("0.48 m", "48", "cm", 5e-3, 1e-9)
        self.assertTrue(result[4])

    def test_symbolic_equivalent_field_matches(self):
        result = compare_prediction(
            "2*k*|q|*h / (a^2 + h^2)^(3/2) V/m",
            r"/frac{2k \abs{q} h}{(a^2 + h^2)^1.5}",
            "V/m",
            5e-3,
            1e-9,
        )
        self.assertTrue(result[4])

    def test_non_equivalent_symbolic_does_not_match(self):
        result = compare_prediction("a*sqrt(2) m", r"a/ \sqrt{2}", "m", 5e-3, 1e-9)
        self.assertFalse(result[4])

    def test_multi_answer_uses_gold_unit_candidate(self):
        result = compare_prediction("1.125 x 10^5 V/m; 0.168 N", "0.168", "N", 5e-3, 1e-9)
        self.assertTrue(result[4])

    def test_rounding_tolerance_matches_textbook_answer(self):
        result = compare_prediction("0.00503 T", "0.005", "T", 1e-2, 1e-9)
        self.assertTrue(result[4])

    def test_capacitance_unit_conversion_matches(self):
        result = compare_prediction("0.1 mF", "100", "μF", 1e-2, 1e-9)
        self.assertTrue(result[4])

    def test_labeled_numeric_gold_matches(self):
        result = compare_prediction("48 W", "P = 48.0", "W", 1e-2, 1e-9)
        self.assertTrue(result[4])

    def test_qualitative_zero_sentence_matches(self):
        result = compare_prediction(
            "The magnetic field outside an ideal solenoid is considered to be zero.",
            "Approximately zero",
            "—",
            1e-2,
            1e-9,
        )
        self.assertTrue(result[4])

    def test_multi_segment_labeled_numbers_match(self):
        result = compare_prediction(
            "I_D1 = 1; I_D2 = 1; I_total = 2 A; A; A",
            "I_D₁ = 1.0; I_D₂ = 1.0; I_total = 2.0",
            "A; A; A",
            1e-2,
            1e-9,
        )
        self.assertTrue(result[4])


if __name__ == "__main__":
    unittest.main()
