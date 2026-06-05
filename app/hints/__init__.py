"""
Hint Engine Registry — dispatches to topic-specific hint generators.

Each hint file exposes an `analyze(question: str) -> list[str]` function.
The registry merges the shared unit-conversion hints with topic-specific hints
and returns a single list injected into the reasoner prompt.
"""
from typing import List


def get_hints(question: str, topic: str) -> List[str]:
    """
    Collect all applicable hints for a question.

    Returns a flat list of hint strings (unit hints first, then topic hints).
    """
    hints: List[str] = []

    # ── Shared: unit conversion (always runs) ──
    from app.hints.unit_conversion_hint import analyze as unit_analyze
    hints.extend(unit_analyze(question))

    # ── Topic-specific ──
    _TOPIC_ANALYZERS = {
        "coulomb_force":       "app.hints.hint_coulomb_force_LD",
        "electric_field_zero": "app.hints.hint_coulomb_force_LD",   # same physics
        "electric_potential":  "app.hints.hint_electric_field_DT",
        "capacitor":           "app.hints.hint_capacitor_TD",
        "ac_circuit":          "app.hints.hint_ac_circuit_CH",
        "magnetism_induction": "app.hints.hint_magnetism_DDT",
        "measurement_error":   "app.hints.hint_measurement_error_THCB",
        "energy_oscillation":  "app.hints.hint_energy_oscillation_NL",
    }

    module_name = _TOPIC_ANALYZERS.get(topic)
    if module_name:
        import importlib
        try:
            mod = importlib.import_module(module_name)
            hints.extend(mod.analyze(question))
        except Exception as exc:  # pragma: no cover
            print(f"[Hints] Warning: {module_name} failed: {exc}")

    # ── CHLT override: always inject if topic looks like resonance ──
    if topic == "ac_circuit":
        q = question.lower()
        resonance_kw = ["resonance", "cộng hưởng", "is it", "does it", "yes", "no"]
        if any(kw in q for kw in resonance_kw):
            from app.hints.hint_ac_resonance_CHLT import analyze as chlt_analyze
            hints.extend(chlt_analyze(question))

    return list(dict.fromkeys(hints))  # deduplicate, preserve order
