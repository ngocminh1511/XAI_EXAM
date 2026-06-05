"""
Evaluate pipeline accuracy against dataset_2/Physics_Problems_Text_Only.csv.

This evaluator is deterministic: it compares the model/pipeline output against
the CSV gold answer and unit with rules, not with another LLM judge.
"""
import argparse
import csv
import json
import math
import re
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

# Keep Windows terminals from crashing on μ, Ω, ×, etc.
sys.stdout.reconfigure(encoding="utf-8")

from app.config import config
from app.pipeline import run_pipeline


ROOT = Path(__file__).resolve().parent
DEFAULT_DATASET = ROOT / "dataset_2" / "Physics_Problems_Text_Only.csv"
KNOWN_ID_PREFIXES = ["CHLT", "THCB", "DDT", "LD", "CH", "NL", "TD", "DT"]


UNIT_FACTORS = {
    # dimensionless
    "": ("dimensionless", 1.0),
    "-": ("dimensionless", 1.0),
    "—": ("dimensionless", 1.0),
    "%": ("percent", 1.0),
    # force
    "N": ("force", 1.0),
    # electric field
    "V/m": ("electric_field", 1.0),
    "N/C": ("electric_field", 1.0),
    # voltage
    "V": ("voltage", 1.0),
    "kV": ("voltage", 1e3),
    "mV": ("voltage", 1e-3),
    # energy
    "J": ("energy", 1.0),
    "mJ": ("energy", 1e-3),
    "nJ": ("energy", 1e-9),
    # capacitance
    "F": ("capacitance", 1.0),
    "μF": ("capacitance", 1e-6),
    "uF": ("capacitance", 1e-6),
    "nF": ("capacitance", 1e-9),
    "pF": ("capacitance", 1e-12),
    # charge
    "C": ("charge", 1.0),
    "mC": ("charge", 1e-3),
    "μC": ("charge", 1e-6),
    "uC": ("charge", 1e-6),
    "nC": ("charge", 1e-9),
    # current
    "A": ("current", 1.0),
    "mA": ("current", 1e-3),
    # resistance
    "Ω": ("resistance", 1.0),
    "ohm": ("resistance", 1.0),
    "kΩ": ("resistance", 1e3),
    # power
    "W": ("power", 1.0),
    "kW": ("power", 1e3),
    # frequency
    "Hz": ("frequency", 1.0),
    "kHz": ("frequency", 1e3),
    # inductance
    "H": ("inductance", 1.0),
    "mH": ("inductance", 1e-3),
}


@dataclass
class EvalRow:
    id: str
    question: str
    gold_answer: str
    gold_unit: str
    pred_answer: str
    pred_value: str
    pred_unit: str
    pred_explanation: str
    pred_cot: list[str]
    pred_premises: list[str]
    pred_confidence: Optional[float]
    exact_match: bool
    numeric_value_match: bool
    strict_unit_match: bool
    physical_equiv_match: bool
    final_match: bool
    error: str = ""
    elapsed_sec: float = 0.0


def normalize_text(text: str) -> str:
    text = (text or "").strip()
    text = text.replace("µ", "μ")
    text = text.replace("−", "-")
    text = re.sub(r"\s+", " ", text)
    return text


def normalize_unit(unit: str) -> str:
    unit = normalize_text(unit)
    unit = unit.replace("Ohm", "Ω").replace("ohms", "ohm").replace("Ohms", "Ω")
    unit = unit.replace("uF", "μF").replace("uC", "μC")
    return unit


def parse_numeric(value: str) -> Optional[float]:
    value = normalize_text(value)
    if not value:
        return None

    cleaned = value
    cleaned = cleaned.replace(",", "")
    cleaned = cleaned.replace("×", "x")
    cleaned = cleaned.replace("·", "*")

    # Convert forms like "4.5 x 10^-3" to "4.5e-3".
    cleaned = re.sub(r"([+-]?\d+(?:\.\d+)?)\s*x\s*10\s*\^?\s*([+-]?\d+)", r"\1e\2", cleaned)

    # Plain leading number, including scientific notation.
    match = re.search(r"^[\s=]*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?)", cleaned, re.IGNORECASE)
    if not match:
        return None

    try:
        return float(match.group(1))
    except ValueError:
        return None


def split_answer_unit(answer: str) -> tuple[str, str]:
    answer = normalize_text(answer)
    numeric_match = re.match(
        r"^\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?)(?:\s+(.+))?\s*$",
        answer,
        re.IGNORECASE,
    )
    if numeric_match:
        return numeric_match.group(1), normalize_unit(numeric_match.group(2) or "")
    return answer, ""


def close_enough(pred: float, gold: float, rel_tol: float, abs_tol: float) -> bool:
    return math.isclose(pred, gold, rel_tol=rel_tol, abs_tol=abs_tol)


def physical_value(value: float, unit: str) -> Optional[tuple[str, float]]:
    unit = normalize_unit(unit)
    if unit not in UNIT_FACTORS:
        return None
    dimension, factor = UNIT_FACTORS[unit]
    return dimension, value * factor


def compare_prediction(
    pred_answer: str,
    gold_answer: str,
    gold_unit: str,
    rel_tol: float,
    abs_tol: float,
) -> tuple[bool, bool, bool, bool, bool, str, str]:
    gold_answer = normalize_text(gold_answer)
    gold_unit = normalize_unit(gold_unit)
    pred_answer = normalize_text(pred_answer)
    pred_value, pred_unit = split_answer_unit(pred_answer)

    gold_full = normalize_text(f"{gold_answer} {gold_unit}".strip())
    exact_match = normalize_text(pred_answer).lower() == gold_full.lower()

    pred_num = parse_numeric(pred_value)
    gold_num = parse_numeric(gold_answer)
    numeric_value_match = False
    strict_unit_match = normalize_unit(pred_unit).lower() == gold_unit.lower()
    physical_equiv_match = False

    if pred_num is not None and gold_num is not None:
        numeric_value_match = close_enough(pred_num, gold_num, rel_tol, abs_tol)

        pred_physical = physical_value(pred_num, pred_unit)
        gold_physical = physical_value(gold_num, gold_unit)
        if pred_physical and gold_physical:
            pred_dim, pred_si = pred_physical
            gold_dim, gold_si = gold_physical
            physical_equiv_match = pred_dim == gold_dim and close_enough(pred_si, gold_si, rel_tol, abs_tol)

    # Main score: numeric answers can pass via strict value+unit or unit-converted equivalence.
    if pred_num is not None and gold_num is not None:
        final_match = (numeric_value_match and strict_unit_match) or physical_equiv_match
    else:
        final_match = exact_match

    return (
        exact_match,
        numeric_value_match,
        strict_unit_match,
        physical_equiv_match,
        final_match,
        pred_value,
        pred_unit,
    )


def detect_id_prefix(sample_id: str) -> str:
    """Return the dataset prefix, preferring longer prefixes such as CHLT."""
    sample_id = sample_id.upper()
    for prefix in KNOWN_ID_PREFIXES:
        if sample_id.startswith(prefix):
            return prefix
    match = re.match(r"[A-Z]+", sample_id)
    return match.group(0) if match else ""


def load_rows(path: Path, start: int, limit: Optional[int], id_prefix: Optional[str] = None) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if id_prefix:
        wanted = id_prefix.upper()
        rows = [row for row in rows if detect_id_prefix(row.get("id", "")) == wanted]
    if start < 0:
        raise ValueError("--start must be >= 0")
    rows = rows[start:]
    if limit is not None:
        rows = rows[:limit]
    return rows


def evaluate(args: argparse.Namespace) -> list[EvalRow]:
    if args.mode:
        config.mode = args.mode
    config.debug = args.debug

    if config.mode in {"local", "api"} and not args.allow_fallback:
        import app.modules.reasoner as reasoner_module

        def _blocked_mock_reason(question: str, premises: list[str]) -> str:
            raise RuntimeError(
                "Reasoner fallback to mock was blocked by evaluator. "
                "Use --allow-fallback only when you intentionally want fallback answers counted."
            )

        reasoner_module._mock_reason = _blocked_mock_reason

    rows = load_rows(args.dataset, args.start, args.limit, id_prefix=args.id_prefix)
    results: list[EvalRow] = []

    print(f"Dataset: {args.dataset}")
    if args.id_prefix:
        print(f"ID prefix: {args.id_prefix.upper()}")
    print(f"Rows: {len(rows)} (start={args.start}, limit={args.limit})")
    print(f"Mode: {config.mode}")
    print(f"Model: {config.reasoner_model}")
    print(f"Allow fallback: {args.allow_fallback}")
    print(f"Tolerance: rel={args.rel_tol}, abs={args.abs_tol}")
    print("-" * 80)

    for idx, row in enumerate(rows, 1):
        qid = row.get("id", "")
        question = row.get("question", "")
        gold_answer = row.get("answer", "")
        gold_unit = row.get("unit", "")
        start_time = time.time()

        try:
            response = run_pipeline(question)
            pred_answer = response.answer
            pred_explanation = response.explanation
            pred_cot = response.cot or []
            pred_premises = response.premises or []
            pred_confidence = response.confidence
            error = ""
        except Exception as exc:
            pred_answer = ""
            pred_explanation = ""
            pred_cot = []
            pred_premises = []
            pred_confidence = None
            error = f"{type(exc).__name__}: {exc}"

        elapsed = time.time() - start_time
        (
            exact_match,
            numeric_value_match,
            strict_unit_match,
            physical_equiv_match,
            final_match,
            pred_value,
            pred_unit,
        ) = compare_prediction(
            pred_answer=pred_answer,
            gold_answer=gold_answer,
            gold_unit=gold_unit,
            rel_tol=args.rel_tol,
            abs_tol=args.abs_tol,
        )

        result = EvalRow(
            id=qid,
            question=question,
            gold_answer=normalize_text(gold_answer),
            gold_unit=normalize_unit(gold_unit),
            pred_answer=normalize_text(pred_answer),
            pred_value=pred_value,
            pred_unit=pred_unit,
            pred_explanation=normalize_text(pred_explanation),
            pred_cot=[normalize_text(step) for step in pred_cot],
            pred_premises=[normalize_text(premise) for premise in pred_premises],
            pred_confidence=pred_confidence,
            exact_match=exact_match,
            numeric_value_match=numeric_value_match,
            strict_unit_match=strict_unit_match,
            physical_equiv_match=physical_equiv_match,
            final_match=final_match,
            error=error,
            elapsed_sec=round(elapsed, 3),
        )
        results.append(result)

        status = "OK" if final_match else "MISS"
        print(
            f"[{idx}/{len(rows)}] {status} {qid} "
            f"gold={result.gold_answer} {result.gold_unit} | "
            f"pred={result.pred_answer} | {elapsed:.2f}s"
        )
        if args.show_cot and result.pred_cot:
            for step in result.pred_cot:
                print(f"    COT: {step}")

    return results


def print_summary(results: list[EvalRow]) -> None:
    total = len(results)
    if total == 0:
        print("No rows evaluated.")
        return

    def pct(count: int) -> str:
        return f"{count / total * 100:.2f}%"

    exact = sum(r.exact_match for r in results)
    numeric = sum(r.numeric_value_match for r in results)
    unit = sum(r.strict_unit_match for r in results)
    physical = sum(r.physical_equiv_match for r in results)
    final = sum(r.final_match for r in results)
    errors = sum(bool(r.error) for r in results)
    avg_time = sum(r.elapsed_sec for r in results) / total

    print("\n" + "=" * 80)
    print("EVALUATION SUMMARY")
    print("=" * 80)
    print(f"Total: {total}")
    print(f"Final accuracy: {final}/{total} = {pct(final)}")
    print(f"Exact full-string match: {exact}/{total} = {pct(exact)}")
    print(f"Numeric value match: {numeric}/{total} = {pct(numeric)}")
    print(f"Strict unit match: {unit}/{total} = {pct(unit)}")
    print(f"Physical equivalent match: {physical}/{total} = {pct(physical)}")
    print(f"Runtime errors: {errors}/{total} = {pct(errors)}")
    print(f"Average time per row: {avg_time:.2f}s")


def write_outputs(results: list[EvalRow], output: Optional[Path]) -> None:
    if output is None:
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as f:
        for row in results:
            f.write(json.dumps(asdict(row), ensure_ascii=False) + "\n")
    print(f"\nWrote detailed results to: {output}")


def load_eval_jsonl(path: Path) -> list[EvalRow]:
    """Load previously saved JSONL evaluator results."""
    results = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            results.append(EvalRow(**json.loads(line)))
    return results


def _md_cell(text: object) -> str:
    """Escape a short value for Markdown table cells."""
    value = "" if text is None else str(text)
    value = value.replace("\n", " ").replace("|", "\\|")
    return value


def _summary_counts(results: list[EvalRow]) -> dict[str, object]:
    total = len(results)
    if total == 0:
        return {
            "total": 0,
            "final": 0,
            "exact": 0,
            "numeric": 0,
            "unit": 0,
            "physical": 0,
            "errors": 0,
            "avg_time": 0.0,
        }
    return {
        "total": total,
        "final": sum(r.final_match for r in results),
        "exact": sum(r.exact_match for r in results),
        "numeric": sum(r.numeric_value_match for r in results),
        "unit": sum(r.strict_unit_match for r in results),
        "physical": sum(r.physical_equiv_match for r in results),
        "errors": sum(bool(r.error) for r in results),
        "avg_time": sum(r.elapsed_sec for r in results) / total,
    }


def _pct(count: int, total: int) -> str:
    if total == 0:
        return "0.00%"
    return f"{count / total * 100:.2f}%"


def write_markdown_report(results: list[EvalRow], report: Optional[Path], misses_only: bool = False) -> None:
    """Write a human-readable Markdown report with answers, premises, and CoT."""
    if report is None:
        return

    report.parent.mkdir(parents=True, exist_ok=True)
    counts = _summary_counts(results)
    total = int(counts["total"])
    detail_rows = [r for r in results if (not misses_only or not r.final_match)]

    lines: list[str] = []
    lines.append("# Pipeline Evaluation Report")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("| --- | ---: |")
    lines.append(f"| Total | {total} |")
    lines.append(f"| Final accuracy | {counts['final']}/{total} ({_pct(int(counts['final']), total)}) |")
    lines.append(f"| Exact full-string match | {counts['exact']}/{total} ({_pct(int(counts['exact']), total)}) |")
    lines.append(f"| Numeric value match | {counts['numeric']}/{total} ({_pct(int(counts['numeric']), total)}) |")
    lines.append(f"| Strict unit match | {counts['unit']}/{total} ({_pct(int(counts['unit']), total)}) |")
    lines.append(f"| Physical equivalent match | {counts['physical']}/{total} ({_pct(int(counts['physical']), total)}) |")
    lines.append(f"| Runtime errors | {counts['errors']}/{total} ({_pct(int(counts['errors']), total)}) |")
    lines.append(f"| Average time per row | {float(counts['avg_time']):.2f}s |")
    lines.append("")

    lines.append("## Results Table")
    lines.append("")
    lines.append("| # | ID | Status | Gold | Prediction | Confidence | Time |")
    lines.append("| ---: | --- | --- | --- | --- | ---: | ---: |")
    for idx, row in enumerate(results, 1):
        status = "OK" if row.final_match else "MISS"
        gold = f"{row.gold_answer} {row.gold_unit}".strip()
        lines.append(
            "| "
            + " | ".join(
                [
                    str(idx),
                    _md_cell(row.id),
                    status,
                    _md_cell(gold),
                    _md_cell(row.pred_answer),
                    _md_cell(row.pred_confidence),
                    f"{row.elapsed_sec:.2f}s",
                ]
            )
            + " |"
        )
    lines.append("")

    detail_title = "Miss Details" if misses_only else "Details"
    lines.append(f"## {detail_title}")
    lines.append("")
    if not detail_rows:
        lines.append("No rows to show.")
    for idx, row in enumerate(detail_rows, 1):
        status = "OK" if row.final_match else "MISS"
        gold = f"{row.gold_answer} {row.gold_unit}".strip()
        lines.append(f"### {idx}. {status} {row.id}")
        lines.append("")
        lines.append(f"**Question:** {row.question}")
        lines.append("")
        lines.append(f"**Gold:** `{gold}`")
        lines.append("")
        lines.append(f"**Prediction:** `{row.pred_answer}`")
        lines.append("")
        lines.append(f"**Confidence:** `{row.pred_confidence}`")
        lines.append("")
        lines.append(f"**Match Flags:** exact={row.exact_match}, numeric={row.numeric_value_match}, unit={row.strict_unit_match}, physical_equiv={row.physical_equiv_match}")
        lines.append("")
        if row.error:
            lines.append(f"**Error:** `{row.error}`")
            lines.append("")
        if row.pred_explanation:
            lines.append("**Explanation:**")
            lines.append("")
            lines.append(row.pred_explanation)
            lines.append("")
        if row.pred_premises:
            lines.append("**Retrieved Premises:**")
            lines.append("")
            for premise in row.pred_premises:
                lines.append(f"- {premise}")
            lines.append("")
        if row.pred_cot:
            lines.append("**Predicted CoT / Reasoning Trace:**")
            lines.append("")
            for step_idx, step in enumerate(row.pred_cot, 1):
                lines.append(f"{step_idx}. {step}")
            lines.append("")

    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote human-readable Markdown report to: {report}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate pipeline accuracy on the physics CSV dataset.")
    parser.add_argument("--from-jsonl", type=Path, default=None, help="Build summary/report from an existing evaluator JSONL file without rerunning the model.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--id-prefix", type=str, default=None, help="Evaluate only rows whose dataset ID has this prefix, e.g. LD, TD, CHLT.")
    parser.add_argument("--mode", choices=["mock", "local", "api"], default=None)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--rel-tol", type=float, default=1e-3)
    parser.add_argument("--abs-tol", type=float, default=1e-9)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--show-cot", action="store_true", help="Print predicted CoT steps in the console.")
    parser.add_argument(
        "--allow-fallback",
        action="store_true",
        help="Allow local/api failures to fall back to mock answers. Do not use for real model accuracy.",
    )
    parser.add_argument("--output", type=Path, default=None, help="Optional JSONL path for per-row results.")
    parser.add_argument("--report", type=Path, default=None, help="Optional human-readable Markdown report path.")
    parser.add_argument("--report-misses-only", action="store_true", help="In the Markdown details section, include only missed rows.")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if args.from_jsonl:
        eval_results = load_eval_jsonl(args.from_jsonl)
    else:
        eval_results = evaluate(args)
    print_summary(eval_results)
    write_outputs(eval_results, args.output)
    write_markdown_report(eval_results, args.report, misses_only=args.report_misses_only)
