"""Optional Ragas 0.4 collections adapter isolated from business runners."""

from __future__ import annotations

import asyncio
from typing import Any

from evals.codex_executor import CodexStructuredExecutor
from evals.schemas import MetricValue


class RagasUnavailableError(RuntimeError):
    """Ragas or an evaluator dependency is unavailable."""


def build_codex_ragas_llm(
    executor: CodexStructuredExecutor | None = None,
) -> Any:
    """Adapt the isolated local Codex executor to Ragas' structured LLM port."""

    try:
        from ragas.llms.base import InstructorBaseRagasLLM
    except ImportError as exc:  # pragma: no cover - eval extra is optional
        raise RagasUnavailableError(
            'Ragas is unavailable; install backend with the "eval" extra'
        ) from exc

    codex = executor or CodexStructuredExecutor()

    class LocalCodexRagasLLM(InstructorBaseRagasLLM):
        def generate(self, prompt: str, response_model: type[Any]) -> Any:
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                return asyncio.run(self.agenerate(prompt, response_model))
            raise RuntimeError("use agenerate inside an active event loop")

        async def agenerate(self, prompt: str, response_model: type[Any]) -> Any:
            return await codex.generate_structured(
                prompt,
                response_model,
                step_name=f"eval.ragas.{response_model.__name__}",
            )

    return LocalCodexRagasLLM()


async def context_precision(
    *,
    llm: Any,
    user_input: str,
    retrieved_contexts: list[str],
    reference: str,
) -> MetricValue:
    try:
        from ragas.metrics.collections import ContextPrecision
    except ImportError as exc:  # pragma: no cover - eval extra is optional
        raise RagasUnavailableError(
            'Ragas is unavailable; install backend with the "eval" extra'
        ) from exc

    scorer = ContextPrecision(llm=llm)
    return await _score(
        "ragas_context_precision",
        scorer.ascore(
            user_input=user_input,
            retrieved_contexts=retrieved_contexts,
            reference=reference,
        ),
    )


async def context_recall(
    *,
    llm: Any,
    user_input: str,
    retrieved_contexts: list[str],
    reference: str,
) -> MetricValue:
    try:
        from ragas.metrics.collections import ContextRecall
    except ImportError as exc:  # pragma: no cover - eval extra is optional
        raise RagasUnavailableError(
            'Ragas is unavailable; install backend with the "eval" extra'
        ) from exc
    return await _score(
        "ragas_context_recall",
        ContextRecall(llm=llm).ascore(
            user_input=user_input,
            retrieved_contexts=retrieved_contexts,
            reference=reference,
        ),
    )


async def noise_sensitivity(
    *,
    llm: Any,
    user_input: str,
    response: str,
    reference: str,
    retrieved_contexts: list[str],
    mode: str = "irrelevant",
) -> MetricValue:
    try:
        from ragas.metrics.collections import NoiseSensitivity
    except ImportError as exc:  # pragma: no cover - eval extra is optional
        raise RagasUnavailableError(
            'Ragas is unavailable; install backend with the "eval" extra'
        ) from exc
    return await _score(
        f"ragas_noise_sensitivity_{mode}",
        NoiseSensitivity(llm=llm, mode=mode).ascore(
            user_input=user_input,
            response=response,
            reference=reference,
            retrieved_contexts=retrieved_contexts,
        ),
    )


async def faithfulness(
    *,
    llm: Any,
    user_input: str,
    response: str,
    retrieved_contexts: list[str],
) -> MetricValue:
    try:
        from ragas.metrics.collections import Faithfulness
    except ImportError as exc:  # pragma: no cover - eval extra is optional
        raise RagasUnavailableError(
            'Ragas is unavailable; install backend with the "eval" extra'
        ) from exc
    return await _score(
        "ragas_faithfulness",
        Faithfulness(llm=llm).ascore(
            user_input=user_input,
            response=response,
            retrieved_contexts=retrieved_contexts,
        ),
    )


async def _score(name: str, score_awaitable: Any) -> MetricValue:
    try:
        score = await score_awaitable
    except Exception as exc:
        return MetricValue(
            name=name,
            available=False,
            details={"error": str(exc), "adapter": "ragas-collections"},
        )
    return MetricValue(
        name=name,
        value=float(score.value),
        available=True,
        details={"adapter": "ragas-collections"},
    )
