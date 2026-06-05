"""
Lightweight topic router for physics questions.

This router intentionally uses question text, not dataset IDs such as LD001 or
TD401, so it also works for real user questions.
"""
from typing import Literal


Topic = Literal[
    "coulomb_force",
    "electric_field_zero",
    "electric_potential",
    "capacitor",
    "ac_circuit",
    "magnetism_induction",
    "measurement_error",
    "energy_oscillation",
    "general",
]


def detect_topic(question: str) -> Topic:
    """Classify a question into a coarse physics topic/intent."""
    q = question.lower()

    zero_field_terms = [
        "e = 0",
        "electric field is zero",
        "net electric field is zero",
        "field strength is zero",
        "where is the electric field zero",
        "point where",
    ]
    if any(term in q for term in zero_field_terms) and ("field" in q or " e " in f" {q} "):
        return "electric_field_zero"

    coulomb_terms = ["charge", "charges", "q1", "q2", "q3", "test charge", "coulomb"]
    force_terms = ["force", "acting on", "resultant", "magnitude"]
    if any(term in q for term in coulomb_terms) and any(term in q for term in force_terms):
        return "coulomb_force"

    if any(term in q for term in ["error", "uncertainty", "least count", "relative error", "absolute error", "percentage error"]):
        return "measurement_error"

    if any(term in q for term in ["rlc", "resonance", "resonant", "resonate", "alternating", "ac circuit", "impedance", "reactance"]):
        return "ac_circuit"

    if any(term in q for term in ["lc oscillation", "oscillation", "capacitor energy", "inductor energy", "electromagnetic energy"]):
        return "energy_oscillation"

    if any(term in q for term in ["solenoid", "magnetic", "inductance", "inductor", "flux", "faraday"]):
        return "magnetism_induction"

    if any(term in q for term in ["voltage", "potential", "electric potential", " v = 0", "equipotential"]):
        if "capacitor" not in q and "plates" not in q:
            return "electric_potential"

    if any(term in q for term in ["capacitor", "capacitance", "plates", "dielectric", "microf", "uf", "pf"]):
        return "capacitor"

    return "general"
