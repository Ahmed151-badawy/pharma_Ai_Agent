"""Measure retrieval quality: does the right passage appear in the top-k results?

    python -m eval.run_retrieval_eval --k 1 --min-hit-rate 0.8

Uses the REAL embedding model (downloads it on first run). Add your own questions to
eval/questions.jsonl, ideally about documents you uploaded: a retrieval change is only an
improvement if this number goes up.
"""
import argparse
import json
import sys
import tempfile
from pathlib import Path

from app.config import get_settings
from app.rag import KnowledgeBase, build_chunks, build_embeddings, extract_pages


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--k", type=int, default=1)
    parser.add_argument("--min-hit-rate", type=float, default=0.0)
    args = parser.parse_args()

    settings = get_settings()
    seed = Path(__file__).resolve().parent.parent / settings.seed_document_path
    with tempfile.TemporaryDirectory() as tmp:
        kb = KnowledgeBase(tmp, build_embeddings(), args.k)
        docs, ids = build_chunks("seed", seed.name, extract_pages(seed.name, seed.read_bytes()))
        kb.add(docs, ids)

        questions = [json.loads(line) for line in Path(__file__).with_name("questions.jsonl").read_text("utf-8").splitlines() if line.strip()]
        hits, reciprocal = 0, 0.0
        for item in questions:
            results = kb.search(item["question"], k=args.k)
            rank = next((i + 1 for i, h in enumerate(results) if item["must_contain"].lower() in h.text.lower()), None)
            hits += rank is not None
            reciprocal += 1 / rank if rank else 0
            print(f"{'PASS' if rank else 'FAIL'}  rank={rank}  {item['question']}")

    hit_rate = hits / len(questions)
    print(f"\nhit@{args.k} = {hit_rate:.0%}   MRR = {reciprocal / len(questions):.2f}   ({len(questions)} questions)")
    sys.exit(0 if hit_rate >= args.min_hit_rate else 1)


if __name__ == "__main__":
    main()
