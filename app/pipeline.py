"""
Main Pipeline Orchestrator
Coordinates all steps: Router → Cache → RAG → Reasoner → Sandbox → Normalizer → Structurer

This is the core brain of the application.
"""
import hashlib
import json
import time
from typing import Optional

from app.config import config
from app.models import PipelineContext, PhysicsResponse
from app.modules.query_router import route_question
from app.modules.topic_router import detect_topic
from app.hints import get_hints
from app.modules.rag import retrieve_premises
from app.modules.reasoner import reason
from app.modules.sandbox import execute_sandbox
from app.modules.normalizer import normalize_answer
from app.modules.confidence import compute_confidence
from app.modules.structurer import structure_response


# ─── Simple in-memory cache ───
_response_cache: dict[str, dict] = {}


def _cache_key(question: str) -> str:
    """Generate cache key from question text."""
    normalized = question.strip().lower()
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def _cache_get(question: str) -> Optional[PhysicsResponse]:
    """Look up cached response."""
    key = _cache_key(question)
    cached = _response_cache.get(key)
    if cached:
        return PhysicsResponse(**cached)
    return None


def _cache_set(question: str, response: PhysicsResponse):
    """Store response in cache."""
    key = _cache_key(question)
    _response_cache[key] = response.model_dump()


# ─── Pipeline ───

def run_pipeline(question: str) -> PhysicsResponse:
    """
    Execute the full physics problem-solving pipeline.
    
    Pipeline flow:
      Step 0: Query Router → quantitative / qualitative
      Step 1: Cache Lookup → return if HIT
      Step 2: Hybrid RAG → premises[]
      Step 3: Reasoner LLM → <think> + FOL + Python code
      Step 4: Code Sandbox → execute Python → answer + unit
      Step 5: Answer Normalizer → standardize format
      Step 6: Structurer → JSON response
      Step 7: Cache Write → store for future requests
    
    Args:
        question: The physics problem text.
        
    Returns:
        PhysicsResponse matching endpoint.txt schema.
    """
    start_time = time.time()

    # Initialize context
    ctx = PipelineContext(question=question)

    # ─── Step 0: Query Router + Hint Engine ───
    ctx.question_type = route_question(question)
    ctx.topic = detect_topic(question)
    ctx.geometry_hints = get_hints(question, topic=ctx.topic)
    if config.debug:
        print(f"[Step 0] Route: {ctx.question_type}, topic={ctx.topic}")
        print(f"         Hints: {len(ctx.geometry_hints)} generated")
        for hint in ctx.geometry_hints:
            print(f"         → {hint[:100]}")

    # ─── Step 1: Cache Lookup ───
    cached = _cache_get(question)
    if cached:
        if config.debug:
            print(f"[Step 1] Cache HIT ({time.time() - start_time:.3f}s)")
        return cached

    if config.debug:
        print("[Step 1] Cache MISS")

    # ─── Step 2: Hybrid RAG ───
    premises, rag_score = retrieve_premises(question, top_k=config.rag_rerank_top_k, topic=ctx.topic)
    ctx.premises = premises
    ctx.rag_top_score = rag_score
    if config.debug:
        print(f"[Step 2] RAG: {len(premises)} premises, top_score={rag_score:.3f}")
        for p in premises:
            print(f"         → {p}")

    # ─── Step 3: Reasoner LLM ───
    reasoner_output = reason(
        question,
        premises,
        topic=ctx.topic,
        question_type=ctx.question_type,
        geometry_hints=ctx.geometry_hints,
    )
    ctx.reasoner_output = reasoner_output
    if config.debug:
        print(f"[Step 3] Reasoner: FOL={bool(reasoner_output.fol)}, "
              f"Code={bool(reasoner_output.python_code)}, "
              f"RawAnswer={reasoner_output.raw_answer}")

    # ─── Step 4: Code Sandbox (only for quantitative) ───
    if ctx.question_type == "quantitative" and reasoner_output.python_code:
        sandbox_result = execute_sandbox(
            reasoner_output.python_code,
            question=question,
            premises=premises,
        )
        ctx.sandbox_result = sandbox_result

        # Self-repair: retry with error feedback (simplified — at pipeline level)
        retries = 0
        while not sandbox_result.success and retries < config.sandbox_max_retries:
            retries += 1
            if config.debug:
                print(f"[Step 4] Sandbox FAIL (retry {retries}): {sandbox_result.error}")
            # In production: re-prompt LLM with error → get new code → retry
            # For now: break out
            break

        sandbox_result.retries_used = retries
        ctx.sandbox_result = sandbox_result

        if config.debug:
            status = "SUCCESS" if sandbox_result.success else "FAIL"
            print(f"[Step 4] Sandbox: {status}, answer={sandbox_result.answer_value}, "
                  f"unit={sandbox_result.unit}")
    else:
        if config.debug:
            print(f"[Step 4] Skipped (qualitative or no code)")

    # ─── Step 5: Answer Normalizer ───
    if ctx.sandbox_result and ctx.sandbox_result.success:
        # Use sandbox result (most reliable)
        raw_ans = ctx.sandbox_result.answer_value or ""
        raw_unit = ctx.sandbox_result.unit or ""
        answer_type = "numeric"
    elif ctx.reasoner_output and ctx.reasoner_output.raw_answer:
        # Fallback to LLM's own answer
        raw_ans = ctx.reasoner_output.raw_answer
        raw_unit = ctx.reasoner_output.raw_unit or ""
        answer_type = "text" if any(c.isalpha() for c in raw_ans) else "numeric"
    else:
        raw_ans = "Unable to compute"
        raw_unit = ""
        answer_type = "text"

    ctx.final_answer, ctx.final_unit = normalize_answer(raw_ans, raw_unit)
    if config.debug:
        print(f"[Step 5] Normalized: {ctx.final_answer} {ctx.final_unit}")

    # ─── Confidence scoring ───
    code_success = ctx.sandbox_result.success if ctx.sandbox_result else False
    code_error = ctx.sandbox_result.error if ctx.sandbox_result else None
    retries = ctx.sandbox_result.retries_used if ctx.sandbox_result else 0

    ctx.confidence = compute_confidence(
        code_success=code_success,
        answer_type=answer_type,
        rag_score=ctx.rag_top_score,
        retries_used=retries,
        code_error=code_error,
    )

    # ─── Step 6: Structure response ───
    response = structure_response(ctx)
    if config.debug:
        print(f"[Step 6] Response structured (confidence={response.confidence})")

    # ─── Step 7: Cache write ───
    _cache_set(question, response)

    elapsed = time.time() - start_time
    if config.debug:
        print(f"[Done] Total time: {elapsed:.3f}s")

    return response
