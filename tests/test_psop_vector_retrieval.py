# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for the optional embedding recall path in orchestrate/core/retrieval.py.

The switch is the contract: with ``retrieval.vector.enabled`` off the retrieval
behaviour must stay byte-for-byte identical to the LLM-only path.
"""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from orchestrate.core.psop_vector_index import VectorSettings
from orchestrate.core.retrieval import WorkflowRetrieval
from orchestrate.core.workflow_search_result import WorkflowSearchResult


CORE = "Core Network Fault Management"
TRANSPORT = "Transport Network Fault Management"


def _summary(workflow_id, name, description):
    return WorkflowSearchResult(
        workflow_id=workflow_id,
        workflow_type="psop",
        name=name,
        description=description,
        tags=["an-l4"],
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        user_intent=description,
        tasks_summary=f"{description} steps",
    )


def _fake_embed(text):
    """Deterministic three-dimensional 'semantic' space."""
    lowered = text.lower()
    if "core" in lowered or "核心" in lowered:
        return [1.0, 0.0, 0.0]
    if "transport" in lowered or "承载" in lowered:
        return [0.0, 1.0, 0.0]
    return [0.0, 0.0, 1.0]


class _CountingEmbedder:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def embed(self, text):
        self.calls.append(text)
        if self.fail:
            raise RuntimeError("embedding endpoint unavailable")
        return _fake_embed(text)


class _FakeLLM:
    def __init__(self, names):
        self.names = names
        self.calls = []

    def ask_llm(self, prompt):
        self.calls.append(prompt)
        return "", json.dumps(self.names)


def _retrieval():
    return WorkflowRetrieval(MagicMock())


def _summaries():
    return [
        _summary("core", CORE, "core network"),
        _summary("transport", TRANSPORT, "transport network"),
    ]


def _settings(tmp_path, **overrides):
    base = dict(
        enabled=True,
        top_k=20,
        min_score=0.0,
        rerank=False,
        llm_final=True,
        strict=False,
        index_file=str(tmp_path / "psop_vectors.json"),
        thinking=True,
    )
    base.update(overrides)
    return VectorSettings(**base)


# ---------------------------------------------------------------------------
# switch off: unchanged behaviour
# ---------------------------------------------------------------------------

class TestSwitchOff:
    def test_llm_path_is_used_and_embeddings_are_never_called(self, tmp_path):
        retrieval = _retrieval()
        embedder = _CountingEmbedder()
        with patch("orchestrate.core.retrieval.vector_settings", return_value=_settings(tmp_path, enabled=False)), \
             patch.object(retrieval, "_list_psop_summaries", return_value=_summaries()), \
             patch.object(retrieval, "_retrieve_names_by_intent", return_value=[CORE]), \
             patch("orchestrate.core.retrieval.get_embed_instance", return_value=embedder):
            results = retrieval.retrieve_psop_by_intent_topn("任意意图", top_n=3)

        assert [result.workflow_id for result in results] == ["core"]
        assert embedder.calls == []


# ---------------------------------------------------------------------------
# switch on: recall -> optional rerank -> final choice
# ---------------------------------------------------------------------------

class TestVectorPath:
    def test_recall_then_llm_final_choice(self, tmp_path):
        retrieval = _retrieval()
        embedder = _CountingEmbedder()
        llm = _FakeLLM([CORE])
        with patch("orchestrate.core.retrieval.vector_settings", return_value=_settings(tmp_path)), \
             patch.object(retrieval, "_list_psop_summaries", return_value=_summaries()), \
             patch("orchestrate.core.retrieval.get_embed_instance", return_value=embedder), \
             patch("orchestrate.core.retrieval.get_llm_instance", return_value=llm):
            results = retrieval.retrieve_psop_by_intent_topn("核心网故障处理", top_n=1)

        assert [result.workflow_id for result in results] == ["core"]
        assert len(llm.calls) == 1
        # Two PSOP documents plus one query embedding on a cold index.
        assert len(embedder.calls) == 3

    def test_llm_final_can_be_switched_off(self, tmp_path):
        retrieval = _retrieval()
        llm = _FakeLLM(["unused"])
        with patch("orchestrate.core.retrieval.vector_settings",
                   return_value=_settings(tmp_path, llm_final=False)), \
             patch.object(retrieval, "_list_psop_summaries", return_value=_summaries()), \
             patch("orchestrate.core.retrieval.get_embed_instance", return_value=_CountingEmbedder()), \
             patch("orchestrate.core.retrieval.get_llm_instance", side_effect=AssertionError("LLM must not run")):
            results = retrieval.retrieve_psop_by_intent_topn("核心网故障处理", top_n=2)

        # Vector order: exact match first, unrelated second.
        assert [result.workflow_id for result in results] == ["core", "transport"]
        assert llm.calls == []

    def test_index_is_reused_between_calls(self, tmp_path):
        retrieval = _retrieval()
        embedder = _CountingEmbedder()
        with patch("orchestrate.core.retrieval.vector_settings",
                   return_value=_settings(tmp_path, llm_final=False)), \
             patch.object(retrieval, "_list_psop_summaries", return_value=_summaries()), \
             patch("orchestrate.core.retrieval.get_embed_instance", return_value=embedder):
            retrieval.retrieve_psop_by_intent_topn("核心网故障处理", top_n=2)
            first_pass = len(embedder.calls)
            retrieval.retrieve_psop_by_intent_topn("核心网故障处理", top_n=2)

        assert first_pass == 3
        # Only the new query is embedded; the PSOP catalog stays cached.
        assert len(embedder.calls) == 4

    def test_min_score_can_filter_everything(self, tmp_path):
        retrieval = _retrieval()
        with patch("orchestrate.core.retrieval.vector_settings",
                   return_value=_settings(tmp_path, min_score=0.9, llm_final=False)), \
             patch.object(retrieval, "_list_psop_summaries", return_value=_summaries()), \
             patch("orchestrate.core.retrieval.get_embed_instance", return_value=_CountingEmbedder()):
            results = retrieval.retrieve_psop_by_intent_topn("完全无关的意图", top_n=2)

        assert results == []

    def test_single_result_api_uses_the_vector_path(self, tmp_path):
        retrieval = _retrieval()
        sentinel = object()
        with patch("orchestrate.core.retrieval.vector_settings", return_value=_settings(tmp_path)), \
             patch.object(retrieval, "_list_psop_summaries", return_value=_summaries()), \
             patch.object(retrieval, "_load_psop_by_id", return_value=sentinel) as loader, \
             patch("orchestrate.core.retrieval.get_embed_instance", return_value=_CountingEmbedder()), \
             patch("orchestrate.core.retrieval.get_llm_instance", return_value=_FakeLLM([CORE])):
            result = retrieval.retrieve_psop_by_intent("核心网故障处理")

        assert result is sentinel
        loader.assert_called_once_with("core")


# ---------------------------------------------------------------------------
# rerank
# ---------------------------------------------------------------------------

class TestRerank:
    def test_reranker_order_wins(self, tmp_path):
        retrieval = _retrieval()
        reranker = MagicMock()
        reranker.rerank.return_value = [
            {"index": 1, "relevance_score": 0.9},
            {"index": 0, "relevance_score": 0.1},
        ]
        with patch("orchestrate.core.retrieval.vector_settings",
                   return_value=_settings(tmp_path, rerank=True, llm_final=False)), \
             patch.object(retrieval, "_list_psop_summaries", return_value=_summaries()), \
             patch("orchestrate.core.retrieval.get_embed_instance", return_value=_CountingEmbedder()), \
             patch("orchestrate.core.retrieval.get_rerank_instance", return_value=reranker):
            results = retrieval.retrieve_psop_by_intent_topn("核心网故障处理", top_n=2)

        assert [result.workflow_id for result in results] == ["transport", "core"]
        assert results[0].score == pytest.approx(0.9)

    def test_reranker_failure_keeps_vector_order(self, tmp_path):
        retrieval = _retrieval()
        reranker = MagicMock()
        reranker.rerank.side_effect = RuntimeError("rerank down")
        with patch("orchestrate.core.retrieval.vector_settings",
                   return_value=_settings(tmp_path, rerank=True, llm_final=False)), \
             patch.object(retrieval, "_list_psop_summaries", return_value=_summaries()), \
             patch("orchestrate.core.retrieval.get_embed_instance", return_value=_CountingEmbedder()), \
             patch("orchestrate.core.retrieval.get_rerank_instance", return_value=reranker):
            results = retrieval.retrieve_psop_by_intent_topn("核心网故障处理", top_n=2)

        assert [result.workflow_id for result in results] == ["core", "transport"]

    def test_empty_rerank_result_keeps_vector_order(self, tmp_path):
        retrieval = _retrieval()
        reranker = MagicMock()
        reranker.rerank.return_value = []
        with patch("orchestrate.core.retrieval.vector_settings",
                   return_value=_settings(tmp_path, rerank=True, llm_final=False)), \
             patch.object(retrieval, "_list_psop_summaries", return_value=_summaries()), \
             patch("orchestrate.core.retrieval.get_embed_instance", return_value=_CountingEmbedder()), \
             patch("orchestrate.core.retrieval.get_rerank_instance", return_value=reranker):
            results = retrieval.retrieve_psop_by_intent_topn("核心网故障处理", top_n=2)

        assert [result.workflow_id for result in results] == ["core", "transport"]


# ---------------------------------------------------------------------------
# failure handling
# ---------------------------------------------------------------------------

class TestFailureHandling:
    def test_embedding_failure_falls_back_to_the_llm_path(self, tmp_path):
        retrieval = _retrieval()
        with patch("orchestrate.core.retrieval.vector_settings", return_value=_settings(tmp_path)), \
             patch.object(retrieval, "_list_psop_summaries", return_value=_summaries()), \
             patch.object(retrieval, "_retrieve_names_by_intent", return_value=[TRANSPORT]), \
             patch("orchestrate.core.retrieval.get_embed_instance",
                   return_value=_CountingEmbedder(fail=True)):
            results = retrieval.retrieve_psop_by_intent_topn("核心网故障处理", top_n=1)

        assert [result.workflow_id for result in results] == ["transport"]

    def test_strict_mode_propagates_the_failure(self, tmp_path):
        retrieval = _retrieval()
        with patch("orchestrate.core.retrieval.vector_settings",
                   return_value=_settings(tmp_path, strict=True)), \
             patch.object(retrieval, "_list_psop_summaries", return_value=_summaries()), \
             patch("orchestrate.core.retrieval.get_embed_instance",
                   return_value=_CountingEmbedder(fail=True)):
            with pytest.raises(RuntimeError, match="embedding endpoint unavailable"):
                retrieval.retrieve_psop_by_intent_topn("核心网故障处理", top_n=1)

    def test_llm_final_failure_keeps_vector_order(self, tmp_path):
        retrieval = _retrieval()
        broken = MagicMock()
        broken.ask_llm.side_effect = RuntimeError("llm down")
        with patch("orchestrate.core.retrieval.vector_settings", return_value=_settings(tmp_path)), \
             patch.object(retrieval, "_list_psop_summaries", return_value=_summaries()), \
             patch("orchestrate.core.retrieval.get_embed_instance", return_value=_CountingEmbedder()), \
             patch("orchestrate.core.retrieval.get_llm_instance", return_value=broken):
            results = retrieval.retrieve_psop_by_intent_topn("核心网故障处理", top_n=2)

        assert [result.workflow_id for result in results] == ["core", "transport"]

    def test_llm_naming_nothing_relevant_keeps_vector_order(self, tmp_path):
        retrieval = _retrieval()
        with patch("orchestrate.core.retrieval.vector_settings", return_value=_settings(tmp_path)), \
             patch.object(retrieval, "_list_psop_summaries", return_value=_summaries()), \
             patch("orchestrate.core.retrieval.get_embed_instance", return_value=_CountingEmbedder()), \
             patch("orchestrate.core.retrieval.get_llm_instance", return_value=_FakeLLM(["Not A Candidate"])):
            results = retrieval.retrieve_psop_by_intent_topn("核心网故障处理", top_n=2)

        assert [result.workflow_id for result in results] == ["core", "transport"]


# ---------------------------------------------------------------------------
# thinking control for retrieval calls
# ---------------------------------------------------------------------------

class TestRetrievalThinking:
    def test_thinking_enabled_uses_the_shared_chat_instance(self, tmp_path):
        retrieval = _retrieval()
        llm = _FakeLLM([CORE])
        with patch("orchestrate.core.retrieval.vector_settings",
                   return_value=_settings(tmp_path, thinking=True)), \
             patch.object(retrieval, "_list_psop_summaries", return_value=_summaries()), \
             patch("orchestrate.core.retrieval.get_embed_instance", return_value=_CountingEmbedder()), \
             patch("orchestrate.core.retrieval.get_llm_instance", return_value=llm) as shared, \
             patch("orchestrate.core.retrieval.get_chat_instance_with_body") as extended:
            retrieval.retrieve_psop_by_intent_topn("核心网故障处理", top_n=1)

        shared.assert_called_once()
        extended.assert_not_called()

    def test_thinking_disabled_requests_an_extended_body(self, tmp_path):
        retrieval = _retrieval()
        llm = _FakeLLM([CORE])
        with patch("orchestrate.core.retrieval.vector_settings",
                   return_value=_settings(tmp_path, thinking=False)), \
             patch.object(retrieval, "_list_psop_summaries", return_value=_summaries()), \
             patch("orchestrate.core.retrieval.get_embed_instance", return_value=_CountingEmbedder()), \
             patch("orchestrate.core.retrieval.get_chat_instance_with_body", return_value=llm) as extended:
            retrieval.retrieve_psop_by_intent_topn("核心网故障处理", top_n=1)

        extended.assert_called_once_with("retrieval_no_thinking", {"thinking": {"type": "disabled"}})
        assert llm.calls
