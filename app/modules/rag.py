"""
Step 2: Topic-aware RAG over the in-memory physics knowledge base.

The first stage is BM25-style keyword search. The second stage applies a small
domain-aware reranker so formulas whose use-case does not match the detected
topic are less likely to enter the LLM prompt.
"""
from typing import List, Tuple

from app.modules.knowledge_base import get_knowledge_base, KBEntry


TOPIC_KEYWORDS = {
    "coulomb_force": {
        "boost": [
            "coulomb",
            "force on test charge",
            "third charge",
            "superposition",
            "resultant",
            "angle theta",
            "perpendicular",
            "direction of coulomb force",
            "collinear geometry",
        ],
        "penalty": ["point where e = 0", "point where v = 0", "instrument error"],
    },
    "electric_field_zero": {
        "boost": ["point where e = 0", "electric field from point charge"],
        "penalty": ["instrument error", "energy stored"],
    },
    "electric_potential": {
        "boost": ["potential", "voltage", "point where v = 0"],
        "penalty": ["force on test charge", "instrument error"],
    },
    "capacitor": {
        "boost": ["capacitor", "capacitance", "dielectric", "parallel-plate", "energy stored in capacitor"],
        "penalty": ["point where e = 0", "point where v = 0", "instrument error"],
    },
    "ac_circuit": {
        "boost": ["rlc", "resonance", "reactance", "impedance", "x_l", "x_c"],
        "penalty": ["point where e = 0", "coulomb"],
    },
    "magnetism_induction": {
        "boost": ["solenoid", "magnetic", "inductor", "inductance", "faraday", "flux"],
        "penalty": ["point where e = 0", "instrument error"],
    },
    "measurement_error": {
        "boost": ["instrument error", "relative error", "absolute error", "least count", "error propagation"],
        "penalty": ["point where e = 0", "coulomb", "capacitor"],
    },
    "energy_oscillation": {
        "boost": ["energy stored", "lc", "oscillation", "inductor", "capacitor energy"],
        "penalty": ["point where e = 0", "instrument error"],
    },
}


def _topic_adjustment(entry: KBEntry, question: str, topic: str) -> float:
    """Return a small additive rerank score based on topic/use-case."""
    if topic == "general":
        return 0.0

    text = f"{entry.topic_prefix} {entry.topic_name} {entry.law_name} {entry.formula} {entry.description} {entry.notes}".lower()
    question_lower = question.lower()
    rules = TOPIC_KEYWORDS.get(topic, {})

    adjustment = 0.0

    for kw in rules.get("boost", []):
        if kw in text:
            adjustment += 3.0

    for kw in rules.get("penalty", []):
        if kw in text:
            adjustment -= 4.0

    # If the user explicitly asks for zero-field/zero-potential, allow those
    # entries even inside broader electrostatics questions.
    zero_field_intent = any(term in question_lower for term in ["e = 0", "field is zero", "field strength is zero"])
    zero_potential_intent = any(term in question_lower for term in ["v = 0", "potential is zero", "voltage is zero"])
    if "point where e = 0" in text and zero_field_intent:
        adjustment += 6.0
    if "point where v = 0" in text and zero_potential_intent:
        adjustment += 6.0

    # Third-charge force questions need vector force premises, not location
    # premises.
    third_charge_force = any(term in question_lower for term in ["q3", "third charge", "test charge"]) and "force" in question_lower
    if third_charge_force:
        if any(term in text for term in ["coulomb", "force on test charge", "superposition", "resultant"]):
            adjustment += 4.0
        if any(term in text for term in ["direction of coulomb force", "collinear geometry", "third charge"]):
            adjustment += 5.0
        if any(term in text for term in ["point where e = 0", "point where v = 0"]):
            adjustment -= 6.0

    return adjustment


def retrieve_premises(question: str, top_k: int = 3, topic: str = "general") -> Tuple[List[str], float]:
    """
    Search the knowledge base for relevant laws/formulas.

    Args:
        question: The physics problem text.
        top_k: Number of top premises to return.
        topic: Topic detected from the question text.

    Returns:
        Tuple of:
          - List of premise strings
          - Top normalized relevance score
    """
    kb = get_knowledge_base()
    candidate_k = max(top_k * 8, 20)
    results = kb.search(question, top_k=candidate_k)

    reranked = []
    for entry, bm25_score in results:
        final_score = bm25_score + _topic_adjustment(entry, question, topic)
        reranked.append((entry, bm25_score, final_score))

    reranked.sort(key=lambda x: x[2], reverse=True)

    premises = []
    top_score = 0.0

    for entry, bm25_score, final_score in reranked:
        if final_score > 0.0:
            premises.append(entry.premise_string)
            top_score = max(top_score, final_score)
        if len(premises) >= top_k:
            break

    if top_score > 0:
        top_score = min(1.0, top_score / (top_score + 5.0))

    return premises, top_score
