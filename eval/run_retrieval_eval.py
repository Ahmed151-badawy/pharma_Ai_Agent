"""Measure retrieval quality across Vector, BM25, and Hybrid RRF modes.

    python -m eval.run_retrieval_eval --k 1 --min-hit-rate 0.8

Evaluates Hit@1, Hit@3, Hit@5, and MRR using the real embedding model on benchmark
questions in eval/retrieval_eval.jsonl.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.rag import KnowledgeBase, build_chunks, build_embeddings, extract_pages


def evaluate_mode(
    kb: KnowledgeBase,
    questions: list[dict[str, str]],
    mode: str,
    max_k: int = 5,
) -> dict[str, Any]:
    hit_1 = 0
    hit_3 = 0
    hit_5 = 0
    reciprocal_sum = 0.0
    question_details: list[dict[str, Any]] = []

    for item in questions:
        query = item["question"]
        must_contain = item["must_contain"].lower()

        if mode == "vector":
            results = kb.search_vector_only(query, k=max_k)
        elif mode == "bm25":
            results = kb.search_bm25_only(query, k=max_k)
        elif mode == "hybrid":
            results = kb.search(query, k=max_k)
        else:
            raise ValueError(f"Unknown mode: {mode}")

        rank: int | None = None
        matched_snippet: str | None = None
        for i, hit in enumerate(results[:max_k]):
            if must_contain in hit.text.lower():
                rank = i + 1
                matched_snippet = hit.text[:120].replace("\n", " ")
                break

        if rank == 1:
            hit_1 += 1
        if rank is not None and rank <= 3:
            hit_3 += 1
        if rank is not None and rank <= 5:
            hit_5 += 1

        reciprocal = (1.0 / rank) if rank is not None else 0.0
        reciprocal_sum += reciprocal

        question_details.append({
            "question": query,
            "must_contain": item["must_contain"],
            "rank": rank,
            "reciprocal_rank": round(reciprocal, 4),
            "matched_snippet": matched_snippet,
        })

    n = len(questions)
    return {
        "mode": mode,
        "total_questions": n,
        "hit_at_1": round(hit_1 / n, 4),
        "hit_at_3": round(hit_3 / n, 4),
        "hit_at_5": round(hit_5 / n, 4),
        "mrr": round(reciprocal_sum / n, 4),
        "details": question_details,
    }


def format_markdown_table(results_by_mode: dict[str, dict[str, Any]]) -> str:
    v = results_by_mode.get("vector", {})
    b = results_by_mode.get("bm25", {})
    h = results_by_mode.get("hybrid", {})

    lines = [
        "| Metric | Vector Only (FAISS) | BM25 Only | Hybrid (RRF k=60) |",
        "|:---|:---:|:---:|:---:|",
        f"| **Hit@1** | {v.get('hit_at_1', 0):.1%} | {b.get('hit_at_1', 0):.1%} | {h.get('hit_at_1', 0):.1%} |",
        f"| **Hit@3** | {v.get('hit_at_3', 0):.1%} | {b.get('hit_at_3', 0):.1%} | {h.get('hit_at_3', 0):.1%} |",
        f"| **Hit@5** | {v.get('hit_at_5', 0):.1%} | {b.get('hit_at_5', 0):.1%} | {h.get('hit_at_5', 0):.1%} |",
        f"| **MRR**   | {v.get('mrr', 0):.4f} | {b.get('mrr', 0):.4f} | {h.get('mrr', 0):.4f} |",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate retrieval quality across Vector, BM25, and Hybrid modes.")
    parser.add_argument("--k", type=int, default=1, help="Legacy compatibility flag for target k")
    parser.add_argument("--min-hit-rate", type=float, default=0.0, help="Minimum required hit rate (0.0 to 1.0)")
    parser.add_argument(
        "--eval-file",
        type=str,
        default="eval/retrieval_eval.jsonl",
        help="Path to questions jsonl file",
    )
    parser.add_argument(
        "--output-table",
        type=str,
        default="docs/evidence/retrieval_eval_table.md",
        help="File to save Markdown comparison table",
    )
    parser.add_argument(
        "--output-json",
        type=str,
        default="docs/evidence/retrieval_eval_raw.json",
        help="File to save raw evaluation metrics",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    eval_path = root / args.eval_file
    if not eval_path.exists():
        eval_path = root / "eval/questions.jsonl"
    if not eval_path.exists():
        print(f"Error: Evaluation file not found at {eval_path}", file=sys.stderr)
        sys.exit(1)

    questions = [
        json.loads(line)
        for line in eval_path.read_text("utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    print(f"Loaded {len(questions)} evaluation questions from {eval_path.relative_to(root)}")

    settings = get_settings()
    seed = root / settings.seed_document_path
    if not seed.exists():
        print(f"Error: Seed document {seed} not found.", file=sys.stderr)
        sys.exit(1)

    print(f"Building temporary index with real embeddings ({settings.embedding_model}) from {seed.name}...")
    with tempfile.TemporaryDirectory() as tmp:
        kb = KnowledgeBase(tmp, build_embeddings(), retrieval_k=5)
        pages = extract_pages(seed.name, seed.read_bytes())
        docs, ids = build_chunks("seed", seed.name, pages)
        kb.add(docs, ids)
        print(f"Indexed {len(docs)} chunks from {seed.name}.")

        modes = ["vector", "bm25", "hybrid"]
        results_by_mode: dict[str, dict[str, Any]] = {}
        for m in modes:
            print(f"Running evaluation for mode: {m}...")
            results_by_mode[m] = evaluate_mode(kb, questions, mode=m, max_k=5)

    md_table = format_markdown_table(results_by_mode)
    print("\n### Retrieval Evaluation Results (40+ Question Benchmark)\n")
    print(md_table)
    print()

    # Honest comparison summary
    v_hit1 = results_by_mode["vector"]["hit_at_1"]
    b_hit1 = results_by_mode["bm25"]["hit_at_1"]
    h_hit1 = results_by_mode["hybrid"]["hit_at_1"]
    v_mrr = results_by_mode["vector"]["mrr"]
    b_mrr = results_by_mode["bm25"]["mrr"]
    h_mrr = results_by_mode["hybrid"]["mrr"]

    print(f"Summary Analysis ({len(questions)} questions):")
    print(f"- Hit@1: Vector={v_hit1:.1%}, BM25={b_hit1:.1%}, Hybrid={h_hit1:.1%}")
    print(f"- MRR:   Vector={v_mrr:.4f}, BM25={b_mrr:.4f}, Hybrid={h_mrr:.4f}")
    if h_mrr >= max(v_mrr, b_mrr):
        print("- Result: Hybrid RRF outperforms or matches individual retrieval models across benchmark queries.")
    else:
        print("- Result: Hybrid RRF did not outperform the single best individual retriever on this specific corpus.")

    # Save artifacts
    out_table_path = root / args.output_table
    out_table_path.parent.mkdir(parents=True, exist_ok=True)
    out_table_path.write_text(md_table + "\n", encoding="utf-8")
    print(f"\nSaved Markdown table to {out_table_path.relative_to(root)}")

    out_json_path = root / args.output_json
    out_json_path.parent.mkdir(parents=True, exist_ok=True)
    out_json_path.write_text(json.dumps(results_by_mode, indent=2), encoding="utf-8")
    print(f"Saved raw results to {out_json_path.relative_to(root)}")

    target_hit = results_by_mode["hybrid"].get(f"hit_at_{args.k}", results_by_mode["hybrid"]["hit_at_1"])
    sys.exit(0 if target_hit >= args.min_hit_rate else 1)


if __name__ == "__main__":
    main()
