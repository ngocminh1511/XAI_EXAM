import unittest

from app.hints import get_topic_hints, get_unit_hints
from app.prompts.reasoner_prompt import build_reasoner_prompt


class HintEngineTests(unittest.TestCase):
    def test_unit_conversion_hints_cover_common_units(self):
        question = "Find energy 30 mJ for C = 100 μF, r = 8 cm, f = 2 kHz, q = 5 nC."

        hints = get_unit_hints(question)
        text = "\n".join(hints)

        self.assertIn("μF", text)
        self.assertIn("cm", text)
        self.assertIn("mJ", text)
        self.assertIn("kHz", text)
        self.assertIn("nC", text)

    def test_topic_hints_cover_ld_geometry_patterns(self):
        equilateral = get_topic_hints(
            "Three charges are placed at the vertices of an equilateral triangle.",
            "coulomb_force",
        )
        right_triangle = get_topic_hints(
            "Triangle ABC is right-angled at A with AB = 3 cm and BC = 5 cm.",
            "coulomb_force",
        )
        bisector = get_topic_hints(
            "Two charges are 8 cm apart. Point M is on the perpendicular bisector 3 cm from AB.",
            "coulomb_force",
        )

        self.assertTrue(any("equilateral" in hint.lower() for hint in equilateral))
        self.assertTrue(any("right-angled" in hint.lower() for hint in right_triangle))
        self.assertTrue(any("perpendicular bisector" in hint.lower() for hint in bisector))

    def test_topic_hints_cover_capacitor_source_state(self):
        disconnected = get_topic_hints(
            "A charged capacitor is then disconnected from the source and the distance is doubled.",
            "capacitor",
        )
        connected = get_topic_hints(
            "A capacitor remains connected to the source while the plate distance is doubled.",
            "capacitor",
        )

        self.assertTrue(any("DISCONNECTED" in hint for hint in disconnected))
        self.assertTrue(any("CONNECTED" in hint for hint in connected))

    def test_topic_hints_cover_chlt_yes_no_resonance(self):
        hints = get_topic_hints(
            "Is the RLC circuit at resonance when f = 50 Hz?",
            "ac_circuit",
        )

        self.assertTrue(any("YES/NO" in hint for hint in hints))
        self.assertTrue(any("'Yes' or 'No'" in hint for hint in hints))

    def test_topic_hints_cover_measurement_error(self):
        hints = get_topic_hints(
            "Find the random error and percentage error for multiple measurements with least count.",
            "measurement_error",
        )
        text = "\n".join(hints)

        self.assertIn("LCNS", text)
        self.assertIn("MAXIMUM deviation", text)
        self.assertIn("Percentage error", text)

    def test_topic_hints_cover_dt_ddt_nl(self):
        dt = get_topic_hints(
            "Find the electric potential at M due to two point charges.",
            "electric_potential",
        )
        ddt = get_topic_hints(
            "How does the magnetic field of a solenoid change when current is doubled?",
            "magnetism_induction",
        )
        nl = get_topic_hints(
            "In an LC oscillation, when capacitor energy and inductor energy are equal.",
            "energy_oscillation",
        )

        self.assertTrue(any("POTENTIAL IS SCALAR" in hint for hint in dt))
        self.assertTrue(any("QUALITATIVE ANSWER" in hint for hint in ddt))
        self.assertTrue(any("W_C = W_L" in hint for hint in nl))

    def test_reasoner_prompt_separates_unit_and_topic_hints(self):
        prompt = build_reasoner_prompt(
            question="Find energy for C = 100 μF in an LC circuit.",
            premises=["Energy stored: W = 1/2*C*U^2"],
            topic="energy_oscillation",
            question_type="quantitative",
            unit_hints=["Unit: 1 μF = 1e-06 F"],
            geometry_hints=["LC ENERGY CONSERVATION: W_total = constant"],
        )

        self.assertIn("Unit conversion facts", prompt)
        self.assertIn("Topic/geometry hints", prompt)
        self.assertLess(
            prompt.index("Unit: 1 μF = 1e-06 F"),
            prompt.index("LC ENERGY CONSERVATION"),
        )


if __name__ == "__main__":
    unittest.main()
