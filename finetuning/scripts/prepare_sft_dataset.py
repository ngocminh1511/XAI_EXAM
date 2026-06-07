"""
Prepare stratified SFT JSONL files for Phase 5 LoRA fine-tuning.

The split is performed independently inside each dataset topic prefix so every
topic appears in train/val/test. The output format is intentionally plain JSONL
with a `text` field so it can be consumed by HuggingFace Trainer, TRL, or
Unsloth examples without a custom dataset class.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.hints import get_topic_hints, get_unit_hints
from app.modules.knowledge_base import InMemoryKB
from app.modules.query_router import route_question
from app.modules.rag import TOPIC_PREFIX_BOOST, _topic_adjustment
from app.modules.topic_router import detect_topic
from app.prompts.reasoner_prompt import REASONER_SYSTEM_PROMPT


DEFAULT_DATASET = ROOT / "dataset_2" / "Physics_Problems_Text_Only.csv"
DEFAULT_OUTPUT_DIR = ROOT / "finetuning" / "data" / "processed"

TOPIC_PREFIXES = ["CHLT", "THCB", "DDT", "LD", "CH", "NL", "TD", "DT"]
TOPIC_NAMES = {
    "LD": "coulomb_force",
    "CH": "ac_circuit",
    "NL": "energy_oscillation",
    "TD": "capacitor",
    "DDT": "magnetism_induction",
    "THCB": "measurement_error",
    "DT": "electric_potential",
    "CHLT": "ac_resonance",
}


SYSTEM_PROMPT = REASONER_SYSTEM_PROMPT

_KB: InMemoryKB | None = None


def detect_topic_prefix(sample_id: str) -> str:
    sample_id = (sample_id or "").upper()
    for prefix in TOPIC_PREFIXES:
        if sample_id.startswith(prefix):
            return prefix
    match = re.match(r"[A-Z]+", sample_id)
    return match.group(0) if match else "UNK"


def normalize_unit(unit: str) -> str:
    unit = (unit or "").strip()
    unit = unit.replace("—", "-")
    unit = unit.replace("Âµ", "μ").replace("µ", "μ")
    return unit


def is_numeric_answer(answer: str) -> bool:
    answer = (answer or "").strip().replace(",", "")
    return bool(re.match(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$", answer, re.IGNORECASE))


def answer_type(answer: str) -> str:
    if is_numeric_answer(answer):
        return "quantitative"
    if any(token in (answer or "") for token in ["\\", "sqrt", "frac", "^", "×", "x 10"]):
        return "symbolic"
    return "qualitative"


def python_literal(value: str) -> str:
    if is_numeric_answer(value):
        return value.strip()
    return json.dumps((value or "").strip(), ensure_ascii=False)


def _get_kb() -> InMemoryKB:
    """Use deterministic in-memory retrieval for SFT data generation."""
    global _KB
    if _KB is None:
        _KB = InMemoryKB()
        _KB.load_from_json(ROOT / "dataset_2" / "physics_knowledge_base.json")
    return _KB


def retrieve_sft_premises(question: str, topic: str, top_k: int = 3, distractor_k: int = 1) -> tuple[list[str], list[str]]:
    """Return topic-relevant premises plus RAFT-style distractors."""
    kb = _get_kb()
    candidate_k = max(30, top_k * 8)
    scored = []
    for entry, score in kb.search(question, top_k=candidate_k):
        final_score = score + _topic_adjustment(entry, question, topic)
        scored.append((entry, final_score))
    scored.sort(key=lambda item: item[1], reverse=True)

    relevant = [entry.premise_string for entry, score in scored if score > 0][:top_k]

    allowed_prefixes = TOPIC_PREFIX_BOOST.get(topic, set())
    distractors = []
    for entry, _ in scored:
        if entry.topic_prefix.upper() not in allowed_prefixes and entry.premise_string not in relevant:
            distractors.append(entry.premise_string)
        if len(distractors) >= distractor_k:
            break
    return relevant, distractors


_NUMBER = r"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:\s*(?:×|x)\s*10\^?[+-]?\d+|(?:e[+-]?\d+)?)?)"


def _num_to_python(value: str) -> str:
    value = value.strip().replace(",", "")
    value = value.replace("×", "x")
    value = re.sub(r"\s*x\s*10\s*\^?\s*([+-]?\d+)", r"e\1", value, flags=re.IGNORECASE)
    return value.replace(" ", "")


def _find_value(question: str, names: list[str], units: list[str]) -> tuple[str, str] | None:
    unit_pattern = "|".join(re.escape(unit) for unit in units)
    for name in names:
        pattern = rf"\b{re.escape(name)}\s*=\s*{_NUMBER}\s*({unit_pattern})\b"
        m = re.search(pattern, question, flags=re.IGNORECASE)
        if m:
            return _num_to_python(m.group(1)), m.group(2)
    pattern = rf"{_NUMBER}\s*({unit_pattern})\b"
    m = re.search(pattern, question, flags=re.IGNORECASE)
    if m:
        return _num_to_python(m.group(1)), m.group(2)
    return None


def _si_factor(unit: str) -> float:
    normalized = unit.replace("µ", "μ")
    factors = {
        "pF": 1e-12,
        "nF": 1e-9,
        "μF": 1e-6,
        "uF": 1e-6,
        "mF": 1e-3,
        "F": 1.0,
        "nC": 1e-9,
        "μC": 1e-6,
        "uC": 1e-6,
        "mC": 1e-3,
        "C": 1.0,
        "mH": 1e-3,
        "μH": 1e-6,
        "uH": 1e-6,
        "H": 1.0,
        "mJ": 1e-3,
        "μJ": 1e-6,
        "uJ": 1e-6,
        "nJ": 1e-9,
        "J": 1.0,
        "cm": 1e-2,
        "mm": 1e-3,
        "m": 1.0,
        "kHz": 1e3,
        "Hz": 1.0,
        "V": 1.0,
        "A": 1.0,
        "Ω": 1.0,
        "ohm": 1.0,
        "N": 1.0,
        "V/m": 1.0,
        "N/C": 1.0,
        "W": 1.0,
    }
    return factors.get(normalized, 1.0)


def _assignment(name: str, found: tuple[str, str]) -> str:
    value, unit = found
    factor = _si_factor(unit)
    return f"{name} = ({value}) * {factor:.12g}  # {value} {unit} -> SI"


def _output_expr(si_var: str, unit: str) -> str:
    unit = normalize_unit(unit)
    if unit in {"", "-", "—"}:
        return si_var
    factor = _si_factor(unit)
    if factor != 1.0:
        return f"{si_var} / {factor:.12g}"
    return si_var


def _format_answer_line(answer: str, unit: str) -> str:
    unit = normalize_unit(unit)
    if unit and unit not in {"-", "—"}:
        return f"{answer} {unit}"
    return answer


def _code_block(lines: list[str]) -> str:
    return "\n".join(["import math", "", *lines])


def synthesize_python_code(row: dict[str, str], topic: str) -> tuple[str, str, bool]:
    """
    Build executable formula code for common high-confidence physics patterns.

    Returns (code, strategy, trainable). Untrainable records are kept for audit
    metadata but are filtered out by the training script by default.
    """
    question = row.get("question", "")
    answer = (row.get("answer") or "").strip()
    unit = normalize_unit(row.get("unit") or "")
    q = question.lower()

    capacitance = _find_value(question, ["C", "capacitance"], ["pF", "nF", "μF", "µF", "uF", "mF", "F"])
    voltage = _find_value(question, ["U", "V", "voltage"], ["V"])
    inductance = _find_value(question, ["L", "inductance"], ["mH", "μH", "µH", "uH", "H"])
    current = _find_value(question, ["I", "current"], ["A"])
    energy = _find_value(question, ["W", "E", "energy"], ["nJ", "μJ", "µJ", "uJ", "mJ", "J"])
    frequency = _find_value(question, ["f", "frequency"], ["kHz", "Hz"])
    resistance = _find_value(question, ["R", "resistance"], ["Ω", "ohm"])

    if "reson" in q and capacitance and inductance and frequency and answer.lower() in {"yes", "no"}:
        lines = [
            _assignment("L", inductance),
            _assignment("C", capacitance),
            _assignment("f_given", frequency),
            "f0 = 1 / (2 * math.pi * math.sqrt(L * C))",
            'answer = "Yes" if math.isclose(f_given, f0, rel_tol=0.02) else "No"',
            'unit = "-"',
        ]
        return _code_block(lines), "chlt_resonance_yes_no", True

    if "reson" in q and resistance and any(term in q for term in ["impedance", " z", "z="]):
        lines = [
            _assignment("Z", resistance),
            "answer = Z",
            'unit = "Ω"',
        ]
        return _code_block(lines), "resonance_impedance_equals_resistance", True

    if capacitance and voltage and any(term in q for term in ["energy", "stored"]):
        out = _output_expr("W", unit)
        lines = [
            _assignment("C", capacitance),
            _assignment("U", voltage),
            "W = 0.5 * C * U**2",
            f"answer = {out}",
            f"unit = {json.dumps(unit, ensure_ascii=False)}",
        ]
        return _code_block(lines), "capacitor_energy", True

    if inductance and current and any(term in q for term in ["energy", "stored", "magnetic field"]):
        out = _output_expr("W", unit)
        lines = [
            _assignment("L", inductance),
            _assignment("I", current),
            "W = 0.5 * L * I**2",
            f"answer = {out}",
            f"unit = {json.dumps(unit, ensure_ascii=False)}",
        ]
        return _code_block(lines), "inductor_energy", True

    if energy and capacitance and any(term in q for term in ["voltage", "potential difference"]):
        lines = [
            _assignment("W", energy),
            _assignment("C", capacitance),
            "U = math.sqrt(2 * W / C)",
            f"answer = {_output_expr('U', unit)}",
            f"unit = {json.dumps(unit, ensure_ascii=False)}",
        ]
        return _code_block(lines), "voltage_from_capacitor_energy", True

    if energy and inductance and "current" in q:
        lines = [
            _assignment("W", energy),
            _assignment("L", inductance),
            "I = math.sqrt(2 * W / L)",
            f"answer = {_output_expr('I', unit)}",
            f"unit = {json.dumps(unit, ensure_ascii=False)}",
        ]
        return _code_block(lines), "current_from_inductor_energy", True

    if energy and voltage and "capacitance" in q:
        lines = [
            _assignment("W", energy),
            _assignment("U", voltage),
            "C = 2 * W / U**2",
            f"answer = {_output_expr('C', unit)}",
            f"unit = {json.dumps(unit, ensure_ascii=False)}",
        ]
        return _code_block(lines), "capacitance_from_energy", True

    if energy and current and "inductance" in q:
        lines = [
            _assignment("W", energy),
            _assignment("I", current),
            "L = 2 * W / I**2",
            f"answer = {_output_expr('L', unit)}",
            f"unit = {json.dumps(unit, ensure_ascii=False)}",
        ]
        return _code_block(lines), "inductance_from_energy", True

    if topic == "dc_circuit" and voltage and resistance and "parallel" in q and "each" in q:
        lamp_count = 2
        count_match = re.search(r"\b(two|three|four|2|3|4)\s+lamps?\b", q)
        if count_match:
            counts = {"two": 2, "three": 3, "four": 4, "2": 2, "3": 3, "4": 4}
            lamp_count = counts[count_match.group(1)]
        lines = [
            _assignment("U", voltage),
            _assignment("R", resistance),
            f"lamp_count = {lamp_count}",
            "I_each = U / R",
            "I_total = lamp_count * I_each",
            'answer = f"I_each = {I_each:.6g}; I_total = {I_total:.6g}"',
            'unit = "A"',
        ]
        return _code_block(lines), "parallel_identical_lamps", True

    force_values = re.findall(r"([0-9]+(?:\.[0-9]+)?)\s*N\b", question, flags=re.IGNORECASE)
    if len(force_values) >= 2 and ("force" in q or "forces" in q):
        f1, f2 = force_values[0], force_values[1]
        if "same direction" in q:
            op = "F1 + F2"
            strategy = "same_direction_forces"
        elif "opposite direction" in q:
            op = "abs(F1 - F2)"
            strategy = "opposite_direction_forces"
        elif "perpendicular" in q or "right angle" in q:
            op = "math.sqrt(F1**2 + F2**2)"
            strategy = "perpendicular_forces"
        else:
            angle_match = re.search(r"angle(?: of)?\s*([0-9]+(?:\.[0-9]+)?)", q)
            if not angle_match:
                angle_match = re.search(r"([0-9]+(?:\.[0-9]+)?)°", question)
            if angle_match:
                theta = angle_match.group(1)
                lines = [
                    f"F1 = {f1}",
                    f"F2 = {f2}",
                    f"theta = math.radians({theta})",
                    "F = math.sqrt(F1**2 + F2**2 + 2 * F1 * F2 * math.cos(theta))",
                    "answer = F",
                    'unit = "N"',
                ]
                return _code_block(lines), "angled_forces", True
            return "", "no_synthesized_code", False
        lines = [
            f"F1 = {f1}",
            f"F2 = {f2}",
            f"F = {op}",
            "answer = F",
            'unit = "N"',
        ]
        return _code_block(lines), strategy, True

    return "", "no_synthesized_code", False


def build_prompt(
    row: dict[str, str],
    topic: str,
    q_type: str,
    unit_hints: list[str],
    topic_hints: list[str],
    premises: list[str],
    distractors: list[str],
) -> str:
    unit_text = "\n".join(f"  - {hint}" for hint in unit_hints) or "  (none detected)"
    topic_text = "\n".join(f"  - {hint}" for hint in topic_hints) or "  (none detected)"
    premise_text = "\n".join(f"  - {premise}" for premise in premises) or "  (none found)"
    distractor_text = "\n".join(f"  - {premise}" for premise in distractors) or "  (none)"
    return f"""Question type: {q_type}
Detected topic: {topic}

Unit conversion facts (treat as HARD CONSTRAINTS):
{unit_text}

Topic/geometry hints (treat as HARD CONSTRAINTS):
{topic_text}

Relevant physics laws/formulas:
{premise_text}

Possible distractor premises (ignore if not relevant):
{distractor_text}

Problem:
{row.get("question", "").strip()}

Solve this problem following the exact output format."""


def build_completion(row: dict[str, str], topic: str, code: str) -> str:
    cot = (row.get("cot") or "").strip()
    answer = (row.get("answer") or "").strip()
    unit = normalize_unit(row.get("unit") or "")
    answer_unit = f"{answer} {unit}".strip()

    fol = (
        f'∀p (PhysicsProblem(p) ∧ Topic(p, "{topic}") '
        f"→ SolveByRelevantPremisesAndExecutableCode(p))"
    )
    if not code:
        code = _code_block([
            "# No reliable executable target was synthesized for this sample.",
            "# This record is marked trainable=False and should be skipped by SFT.",
            'answer = ""',
            'unit = ""',
        ])

    return f"""<think>
{cot}
</think>

[FOL]: {fol}

[CODE]:
```python
{code}
```

[ANSWER]: {answer_unit}"""


def build_text(prompt: str, completion: str) -> tuple[str, str]:
    prompt_text = (
        "<|im_start|>system\n"
        f"{SYSTEM_PROMPT}<|im_end|>\n"
        "<|im_start|>user\n"
        f"{prompt}<|im_end|>\n"
        "<|im_start|>assistant\n"
    )
    return prompt_text, prompt_text + f"{completion}<|im_end|>"


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def split_topic_rows(
    rows: list[dict[str, str]],
    train_ratio: float,
    val_ratio: float,
    seed: int,
) -> dict[str, list[dict[str, str]]]:
    rng = random.Random(seed)
    by_topic: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_topic[detect_topic_prefix(row.get("id", ""))].append(row)

    splits = {"train": [], "val": [], "test": []}
    for topic_prefix in sorted(by_topic):
        topic_rows = by_topic[topic_prefix][:]
        rng.shuffle(topic_rows)
        n = len(topic_rows)

        n_train = int(n * train_ratio)
        n_val = int(n * val_ratio)
        if n >= 3:
            n_val = max(1, n_val)
            n_train = min(n_train, n - 2)
        n_test = n - n_train - n_val
        if n >= 3 and n_test < 1:
            n_test = 1
            n_train = n - n_val - n_test

        for split_name, split_rows in (
            ("train", topic_rows[:n_train]),
            ("val", topic_rows[n_train : n_train + n_val]),
            ("test", topic_rows[n_train + n_val :]),
        ):
            for row in split_rows:
                row = dict(row)
                row["_topic_prefix"] = topic_prefix
                splits[split_name].append(row)

    for split_rows in splits.values():
        rng.shuffle(split_rows)

    return splits


def to_record(row: dict[str, str], split: str) -> dict[str, Any]:
    topic_prefix = row["_topic_prefix"]
    unit = normalize_unit(row.get("unit", ""))
    answer = (row.get("answer") or "").strip()
    question = (row.get("question") or "").strip()
    detected_topic = detect_topic(question)
    q_type = route_question(question)
    unit_hints = get_unit_hints(question)
    topic_hints = get_topic_hints(question, detected_topic)
    premises, distractors = retrieve_sft_premises(question, detected_topic)
    code, code_strategy, trainable = synthesize_python_code(row, detected_topic)
    prompt = build_prompt(
        row=row,
        topic=detected_topic,
        q_type=q_type,
        unit_hints=unit_hints,
        topic_hints=topic_hints,
        premises=premises,
        distractors=distractors,
    )
    completion = build_completion(row, detected_topic, code)
    prompt_text, text = build_text(prompt, completion)
    return {
        "id": row.get("id", "").strip(),
        "topic_prefix": topic_prefix,
        "topic": detected_topic,
        "dataset_topic": TOPIC_NAMES.get(topic_prefix, topic_prefix.lower()),
        "split": split,
        "question": question,
        "answer": answer,
        "unit": unit,
        "answer_type": answer_type(answer),
        "question_type": q_type,
        "unit_hints": unit_hints,
        "topic_hints": topic_hints,
        "premises": premises,
        "distractor_premises": distractors,
        "code_strategy": code_strategy,
        "trainable": trainable,
        "prompt": prompt,
        "prompt_text": prompt_text,
        "completion": completion,
        "text": text,
    }


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def prepare_dataset(
    dataset_path: Path,
    output_dir: Path,
    seed: int = 42,
    train_ratio: float = 0.8,
    val_ratio: float = 0.1,
) -> dict[str, Any]:
    rows = load_rows(dataset_path)
    splits = split_topic_rows(rows, train_ratio=train_ratio, val_ratio=val_ratio, seed=seed)

    manifest: dict[str, Any] = {
        "dataset_path": str(dataset_path),
        "seed": seed,
        "total": len(rows),
        "splits": {},
        "topics": {},
    }

    for split_name, split_rows in splits.items():
        records = [to_record(row, split_name) for row in split_rows]
        write_jsonl(output_dir / f"{split_name}.jsonl", records)
        manifest["splits"][split_name] = len(records)
        manifest.setdefault("trainable_splits", {})[split_name] = sum(bool(r["trainable"]) for r in records)

    for row in rows:
        prefix = detect_topic_prefix(row.get("id", ""))
        manifest["topics"].setdefault(prefix, {"total": 0, "train": 0, "val": 0, "test": 0})
        manifest["topics"][prefix]["total"] += 1

    for split_name, split_rows in splits.items():
        for row in split_rows:
            manifest["topics"][row["_topic_prefix"]][split_name] += 1

    manifest["trainable_total"] = sum(manifest.get("trainable_splits", {}).values())

    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare stratified SFT JSONL files.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--train-ratio", type=float, default=0.8)
    parser.add_argument("--val-ratio", type=float, default=0.1)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = prepare_dataset(
        dataset_path=args.dataset,
        output_dir=args.output_dir,
        seed=args.seed,
        train_ratio=args.train_ratio,
        val_ratio=args.val_ratio,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
