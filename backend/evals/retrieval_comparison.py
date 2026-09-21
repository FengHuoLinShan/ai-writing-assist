"""Offline retrieval experiment; production chunking/scoring, synthetic embeddings.

The reranker arm exercises the production decision consumer with scripted output,
not an LLM judge. No quality or production strategy claim follows from this run.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import time
import unicodedata
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

from rank_bm25 import BM25Okapi

from evals.experiment import experiment_evidence, validate_story_splits
from evals.metrics import evidence_group_recall
from evals.schemas import DatasetCase, LogicalSourceRef
from modules.evidence.compilation.services.parent_evidence import bounded_ranges
from modules.evidence.indexing.chunking import ChunkingService
from modules.evidence.indexing.reranker import RerankerOutput, apply_rerank_output
from modules.evidence.indexing.retrieval import RetrievalOrchestrator
from modules.evidence.indexing.scoring import Scorer, keyword_query_terms

DEFAULT_DATASET = Path(__file__).parent / "datasets/baselines/technical-rag-v1.jsonl"
GENERATION_ARMS = {
    "no_retrieval": {"retrieval": False, "followups": 0},
    "current_rag": {"retrieval": "current", "followups": 0},
    "improved_rag": {"retrieval": "bm25-vector-rrf", "followups": 0},
    "long_context": {"retrieval": "all_authorized_sources", "followups": 0},
    "bounded_followup": {"retrieval": "bm25-vector-rrf", "followups": 1},
}


def tokenize(text: str) -> list[str]:
    text = unicodedata.normalize("NFKC", text).lower()
    tokens = []
    for match in re.finditer(r"[\u4e00-\u9fff]+|[a-z0-9]+", text):
        term = match.group()
        tokens.extend(
            [term]
            if term.isascii() or len(term) == 1
            else [term[i : i + 2] for i in range(len(term) - 1)]
        )
    return tokens


def _vector(text):
    # Deterministic test embedding, explicitly not a semantic model benchmark.
    vector = [0.0] * 128
    for token, count in Counter(tokenize(text)).items():
        index = int.from_bytes(hashlib.sha256(token.encode()).digest()[:2], "big") % 128
        vector[index] += count
    return vector


class _OfflineRepository:
    def __init__(self, chunks):
        self.chunks = chunks

    async def keyword_search(self, db, novel_id, query, **kwargs):
        terms = keyword_query_terms(query)
        return [
            chunk for chunk in self.chunks if any(term in chunk.text for term in terms)
        ][: kwargs["limit"]]

    async def vector_search(self, db, novel_id, embedding, **kwargs):
        return sorted(
            [
                (chunk, Scorer().vector_score(chunk.embedding, embedding))
                for chunk in self.chunks
            ],
            key=lambda pair: -pair[1],
        )[: kwargs["top_k"]]


def load_cases(path=DEFAULT_DATASET):
    cases = [
        DatasetCase.model_validate_json(line)
        for line in path.read_text().splitlines()
        if line.strip()
    ]
    validate_story_splits(cases)
    for case in cases:
        for doc in case.input["documents"]:
            if hashlib.sha256(doc["text"].encode()).hexdigest() != doc["source_hash"]:
                raise ValueError("synthetic source hash mismatch")
        # Gold remains evaluator-only. A case with an answer needs complete ranges.
        groups = case.reference["evidence_groups"]
        if not case.reference.get("no_answer") and not groups:
            raise ValueError("answerable cases require immutable range gold")
        for group in groups:
            for raw in group:
                ref = LogicalSourceRef.model_validate(raw)
                if ref.start_offset is None:
                    raise ValueError("gold must use source ranges, not chunk IDs")
    return cases


def _eligible(case):
    manifest = case.input["source_manifest"]
    cutoff = case.visibility.visible_until_chapter
    return [
        doc
        for doc in case.input["documents"]
        if doc["novel_id"] == case.input["novel_id"]
        and manifest.get(doc["id"]) == doc["source_hash"]
        and (cutoff is None or doc["chapter"] <= cutoff)
        and doc["id"] not in case.input.get("excluded_sources", [])
    ]


def _range(case, doc, start, end):
    return LogicalSourceRef(
        corpus_id="technical-rag-v1",
        source_alias=doc["id"],
        source_group_id=case.source_group_id,
        chapter_index=doc["chapter"],
        content_hash=doc["source_hash"],
        start_offset=start,
        end_offset=end,
    )


async def evaluate_case(case, *, chunk_target=None):
    documents = _eligible(case)  # Filter before embeddings, BM25, or rerank.
    by_id = {doc["id"]: doc for doc in documents}
    chunks = []
    for doc in documents:
        for part in ChunkingService().split_chinese_novel(
            doc["text"],
            target_length=chunk_target,
            max_length=max(chunk_target, chunk_target * 3 // 2) if chunk_target else None,
            overlap=min(160, chunk_target // 4) if chunk_target else None,
        ):
            if bounded_ranges(
                part.start_offset,
                part.end_offset,
                allowed=doc.get("allowed_ranges"),
                excluded=doc.get("excluded_ranges", []),
            ) != [(part.start_offset, part.end_offset)]:
                continue
            chunks.append(
                SimpleNamespace(
                    id=f"{doc['id']}:{part.chunk_index}",
                    source_id=doc["id"],
                    source_content_hash=doc["source_hash"],
                    text=part.text,
                    start_offset=part.start_offset,
                    end_offset=part.end_offset,
                    embedding=_vector(part.text),
                    importance=0.5,
                    chapter_index=doc["chapter"],
                    entity_ids=[],
                    character_ids=[],
                    thread_ids=[],
                    scene_id=None,
                )
            )
    query = case.input["query"]
    for alias, name in case.input.get("aliases", {}).items():
        query = query.replace(alias, name)
    vector = _vector(query)
    started = time.perf_counter()
    current = await RetrievalOrchestrator(repo=_OfflineRepository(chunks)).hybrid_search(
        None,
        case.input["novel_id"],
        query,
        query_embedding=vector,
        source_manifest=case.input["source_manifest"],
        expand_query=False,
        top_k=5,
    )
    ranking = []
    if chunks:
        scores = BM25Okapi([tokenize(chunk.text) for chunk in chunks]).get_scores(
            tokenize(query)
        )
        lexical = sorted(zip(chunks, scores), key=lambda pair: -pair[1])
        lexical = [chunk for chunk, score in lexical if score > 0]
        vectors = sorted(
            chunks, key=lambda chunk: -Scorer().vector_score(chunk.embedding, vector)
        )
        vectors = [
            chunk
            for chunk in vectors
            if Scorer().vector_score(chunk.embedding, vector) >= 0.65
        ]
        fused = Counter()
        for channel in (lexical, vectors):
            for rank, chunk in enumerate(channel, 1):
                fused[chunk.id] += 1 / (60 + rank)
        ranking = sorted(
            [(chunk, fused[chunk.id]) for chunk in chunks if fused[chunk.id]],
            key=lambda pair: (-pair[1], pair[0].id),
        )[:5]
    # Scripted adapter contract: no gold, annotations, or expected answers enter it.
    output = RerankerOutput.model_validate(
        {
            "support_status": "supported" if ranking else "unsupported",
            "confidence": 1,
            "basis": "offline scripted contract, not model judgment",
            "ranked_candidates": [
                {
                    "candidate_ref": f"candidate-{i:03d}",
                    "evidence_role": "supporting",
                    "relevance_score": float(score),
                    "basis": "frozen input ranking",
                }
                for i, (_, score) in enumerate(ranking, 1)
            ],
        }
    )
    reranked = apply_rerank_output(
        output, ranking, top_k=5, retrieval_mode="context"
    ).chunks
    groups = [
        [LogicalSourceRef.model_validate(ref) for ref in group]
        for group in case.reference["evidence_groups"]
    ]
    arms = {}
    for name, ordered in (
        ("current", current),
        ("bm25_vector_rrf", ranking),
        ("fusion_rerank_contract", reranked),
    ):
        refs = [
            _range(case, by_id[chunk.source_id], chunk.start_offset, chunk.end_offset)
            for chunk, _ in ordered
        ]
        parent_refs = []
        for chunk, _ in ordered:
            doc = by_id[chunk.source_id]
            # Frozen synthetic parent ranges; real DB Scene lookup is integration-tested.
            for left, right in bounded_ranges(
                0,
                len(doc["text"]),
                allowed=doc.get("allowed_ranges"),
                excluded=doc.get("excluded_ranges", []),
            ):
                parent_refs.append(_range(case, doc, left, right))
        arms[name] = {
            "retrieved": [ref.model_dump() for ref in refs],
            "range_group_recall": evidence_group_recall(refs, groups),
            "parent_group_recall": evidence_group_recall(parent_refs, groups),
            "no_answer_retrieval": bool(case.reference.get("no_answer") and refs),
            "model_executed": False,
        }
    return {
        "case_id": case.case_id,
        "scenario": case.scenario,
        "split": case.split.value,
        "arms": arms,
        "duration_ms": (time.perf_counter() - started) * 1000,
    }


async def run(path=DEFAULT_DATASET, *, chunk_target=None):
    cases = load_cases(path)
    results = [await evaluate_case(case, chunk_target=chunk_target) for case in cases]
    return {
        "evidence": experiment_evidence(
            dataset=[case.model_dump(mode="json") for case in cases],
            source_fingerprints={
                doc["id"]: doc["source_hash"] for case in cases for doc in _eligible(case)
            },
            implementation_files=[Path(__file__), Path(__file__).with_name("metrics.py")],
            receipts=[],
        ),
        "embedding": "deterministic-hashed-bigrams-v1; not a semantic-model benchmark",
        "reranker": "scripted-output/production-consumer; not LLM quality",
        "chunk_target": chunk_target or ChunkingService.DEFAULT_CN_TARGET_LENGTH,
        "generation_arms": GENERATION_ARMS,
        "generation_status": "not_run_requires_separate_budget_and_profile",
        "cases": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--chunk-target", type=int)
    args = parser.parse_args()
    if args.chunk_target is not None and args.chunk_target < 8:
        parser.error("--chunk-target must be at least 8")
    report = asyncio.run(run(args.dataset, chunk_target=args.chunk_target))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
