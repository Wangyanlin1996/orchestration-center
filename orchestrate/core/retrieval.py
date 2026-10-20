# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import json
from datetime import timezone
from typing import Optional, List

from loguru import logger

from common.llm import (
    get_chat_instance_with_body,
    get_embed_instance,
    get_llm_instance,
    get_rerank_instance,
)
from common.util.json_utils import parse_llm_json_response
from orchestrate.core.model.preflow import PreFlow
from orchestrate.core.model.psop import PSOP
from orchestrate.core.persistence import WorkflowStorage
from orchestrate.core.prompts import get_retrieve_psop_prompt
from orchestrate.core.psop_vector_index import (
    PsopVectorIndex,
    VectorSettings,
    psop_document,
    vector_settings,
)
from orchestrate.core.workflow_search_result import WorkflowSearchResult
from orchestrate.persistence import current_context


def _detect_intent_lang(text: str) -> Optional[str]:
    """Detect the language of the intent text.

    Returns "Chinese" if any CJK ideograph is present, "English" otherwise,
    or None when the input is empty. Used as a same-language tiebreaker hint
    for PSOP retrieval so that an English intent prefers English PSOPs and a
    Chinese intent prefers Chinese PSOPs when relevance is otherwise equal.
    """
    if not text:
        return None
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff":
            return "Chinese"
    return "English"

class WorkflowRetrieval:
    def __init__(self, storage: WorkflowStorage, context=None):
        self.storage = storage
        # Resolved once. In file mode this binds the storage the caller owns
        # (tests inject a temporary one); in the database modes it is the
        # configured backend's repository. See PersistenceBackend.psops_for.
        self._psops = (context or current_context()).psops_for(storage)
        self._vector_index_cache = None

    def _list_psop_summaries(self) -> List[WorkflowSearchResult]:
        return self._psops.list_summaries()

    def _load_psop_by_id(self, workflow_id: str) -> Optional[PSOP]:
        return self._psops.get(workflow_id)

    def get_psop_by_id(self, workflow_id: str) -> Optional[PSOP]:
        result = self._load_psop_by_id(workflow_id)
        if result:
            logger.debug(f"[Retrieval] Loaded PSOP by id: {workflow_id}")
        else:
            logger.debug(f"[Retrieval] PSOP not found by id: {workflow_id}")
        return result

    def get_preflow_by_id(self, workflow_id: str) -> Optional[PreFlow]:
        return self.storage.load_preflow(workflow_id)

    def search_by_name(self, name_pattern: str, workflow_type: str = "all") -> List[WorkflowSearchResult]:
        logger.debug(f"[Retrieval] search_by_name: pattern='{name_pattern}', type={workflow_type}")
        results = []
        name_lower = name_pattern.lower()
        if workflow_type in ("all", "psop"):
            for summary in self._list_psop_summaries():
                if name_lower in summary.name.lower():
                    results.append(summary)
        if workflow_type in ("all", "preflow"):
            for wf_id in self.storage.list_preflows():
                preflow = self.storage.load_preflow(wf_id)
                if preflow and name_lower in preflow.name.lower():
                    results.append(WorkflowSearchResult(
                        workflow_id=preflow.id,
                        workflow_type="preflow",
                        name=preflow.name,
                        description=preflow.description,
                        tags=preflow.tags,
                        created_at=preflow.created_at,
                    ))
        return results

    def search_by_tags(self, tags: List[str], match_all: bool = False, workflow_type: str = "all") -> List[
        WorkflowSearchResult]:
        results = []
        search_tags_lower = [t.lower() for t in tags]

        def matches_tags(wf_tags: Optional[List[str]]) -> bool:
            if not wf_tags:
                return False
            wf_lower = [t.lower() for t in wf_tags]
            if match_all:
                return all(st in wf_lower for st in search_tags_lower)
            else:
                return any(st in wf_lower for st in search_tags_lower)

        if workflow_type in ("all", "psop"):
            for summary in self._list_psop_summaries():
                if matches_tags(summary.tags):
                    results.append(summary)
        if workflow_type in ("all", "preflow"):
            for wf_id in self.storage.list_preflows():
                preflow = self.storage.load_preflow(wf_id)
                if preflow and matches_tags(preflow.tags):
                    results.append(WorkflowSearchResult(
                        workflow_id=preflow.id,
                        workflow_type="preflow",
                        name=preflow.name,
                        description=preflow.description,
                        tags=preflow.tags,
                        created_at=preflow.created_at,
                    ))
        return results

    def search_by_description(self, keyword: str, workflow_type: str = "all") -> List[WorkflowSearchResult]:
        results = []
        keyword_lower = keyword.lower()
        if workflow_type in ("all", "psop"):
            for summary in self._list_psop_summaries():
                if summary.description and keyword_lower in summary.description.lower():
                    results.append(summary)
        if workflow_type in ("all", "preflow"):
            for wf_id in self.storage.list_preflows():
                preflow = self.storage.load_preflow(wf_id)
                if preflow and preflow.description and keyword_lower in preflow.description.lower():
                    results.append(WorkflowSearchResult(
                        workflow_id=preflow.id,
                        workflow_type="preflow",
                        name=preflow.name,
                        description=preflow.description,
                        tags=preflow.tags,
                        created_at=preflow.created_at,
                    ))
        return results

    def get_psop_by_preflow(self, preflow_id: str) -> List[PSOP]:
        logger.debug(f"[Retrieval] get_psop_by_preflow: preflow_id={preflow_id}")
        results = []
        for summary in self._list_psop_summaries():
            if summary.related_preflow == preflow_id:
                psop = self._load_psop_by_id(summary.workflow_id)
                if psop:
                    results.append(psop)
        return results

    def list_recent_workflows(self, limit: int = 10, workflow_type: str = "all", offset: int = 0) -> List[WorkflowSearchResult]:
        results = []
        if workflow_type in ("all", "psop"):
            results.extend(self._list_psop_summaries())
        if workflow_type in ("all", "preflow"):
            for wf_id in self.storage.list_preflows():
                preflow = self.storage.load_preflow(wf_id)
                if preflow:
                    results.append(WorkflowSearchResult(
                        workflow_id=preflow.id,
                        workflow_type="preflow",
                        name=preflow.name,
                        description=preflow.description,
                        tags=preflow.tags,
                        created_at=preflow.created_at,
                    ))

        def _sort_key(x):
            if x.created_at.tzinfo:
                return x.created_at.timestamp(), x.workflow_id
            return x.created_at.replace(tzinfo=timezone.utc).timestamp(), x.workflow_id

        results.sort(key=_sort_key, reverse=True)
        return results[offset:offset + limit]

    def _retrieve_names_by_intent(self, user_intent: str, top_n: int = 1) -> List[str]:
        summaries = self._list_psop_summaries()
        if not summaries:
            return []

        psop_list = [{
            "name": s.name,
            "description": s.description or "",
            "tags": s.tags or [],
            "user_intent": s.user_intent or "",
            "tasks": s.tasks_summary or "",
            "id": s.workflow_id
        } for s in summaries]

        psop_list_str = json.dumps(psop_list, ensure_ascii=False, indent=2)
        llm = get_llm_instance()
        prompt = get_retrieve_psop_prompt(
            user_intent, psop_list_str, top_n, lang=_detect_intent_lang(user_intent)
        )

        try:
            _, llm_res = llm.ask_llm(prompt)
            selected_names = parse_llm_json_response(llm_res)

            if not isinstance(selected_names, list):
                raise ValueError(f"Expected a JSON array of names, got: {type(selected_names)}")

            return selected_names[:top_n]
        except Exception as e:
            raise Exception(f"Failed to retrieve PSOP by intent: {e}") from e

    # -- optional embedding recall (retrieval.vector.enabled) ----------------

    @staticmethod
    def _embed_model_name() -> str:
        from common.llm.config.llm_config import get_model_config

        config = get_model_config("embed")
        return str(getattr(config, "model", "") or "")

    def _vector_index(self, settings: VectorSettings) -> PsopVectorIndex:
        model = self._embed_model_name()
        key = (settings.index_file, model)
        if self._vector_index_cache is None or self._vector_index_cache[0] != key:
            self._vector_index_cache = (key, PsopVectorIndex(settings.index_file, model=model))
        return self._vector_index_cache[1]

    def _retrieval_llm(self):
        """Retrieval is a classification task; thinking is opt-in per deployment."""
        if vector_settings().thinking:
            return get_llm_instance()
        return get_chat_instance_with_body("retrieval_no_thinking", {"thinking": {"type": "disabled"}})

    def _vector_retrieve(self, user_intent: str, top_n: int) -> List[WorkflowSearchResult]:
        """Recall with embeddings, rerank optionally, then let the LLM choose."""
        settings = vector_settings()
        summaries = self._list_psop_summaries()
        if not summaries:
            return []

        embedder = get_embed_instance()
        index = self._vector_index(settings)
        index.reconcile(summaries, embedder.embed)
        query_vector = embedder.embed(user_intent)

        hits = index.search(query_vector, settings.top_k, settings.min_score)
        by_id = {summary.workflow_id: summary for summary in summaries}
        candidates = [
            by_id[workflow_id].model_copy(update={"score": score})
            for workflow_id, score in hits if workflow_id in by_id
        ]
        logger.info(f"[Retrieval] Vector recall returned {len(candidates)} of {len(summaries)} PSOP(s)")
        if not candidates:
            return []
        if settings.rerank:
            candidates = self._rerank_candidates(user_intent, candidates)
        if not settings.llm_final:
            return candidates[:top_n]
        return self._select_with_llm(user_intent, candidates, top_n)

    def _rerank_candidates(
        self, user_intent: str, candidates: List[WorkflowSearchResult],
    ) -> List[WorkflowSearchResult]:
        """Reorder recalled candidates; any reranker problem keeps vector order."""
        try:
            reranked = get_rerank_instance().rerank(
                user_intent, [psop_document(candidate) for candidate in candidates]
            )
        except Exception as exc:
            logger.warning(f"[Retrieval] Rerank failed, keeping vector order: {exc}")
            return candidates
        if not reranked:
            logger.warning("[Retrieval] Reranker returned no order, keeping vector order")
            return candidates

        ordered: List[WorkflowSearchResult] = []
        for item in reranked:
            if not isinstance(item, dict):
                continue
            try:
                position = int(item.get("index"))
            except (TypeError, ValueError):
                continue
            if not 0 <= position < len(candidates):
                continue
            score = item.get("relevance_score", item.get("score", candidates[position].score))
            try:
                ordered.append(candidates[position].model_copy(update={"score": float(score)}))
            except (TypeError, ValueError):
                ordered.append(candidates[position])
        return ordered or candidates

    def _select_with_llm(
        self, user_intent: str, candidates: List[WorkflowSearchResult], top_n: int,
    ) -> List[WorkflowSearchResult]:
        """Final choice among recalled candidates; failures keep the vector order."""
        rows = [{
            "name": summary.name,
            "description": summary.description or "",
            "tags": summary.tags or [],
            "user_intent": summary.user_intent or "",
            "tasks": summary.tasks_summary or "",
            "id": summary.workflow_id,
        } for summary in candidates]
        prompt = get_retrieve_psop_prompt(
            user_intent,
            json.dumps(rows, ensure_ascii=False, indent=2),
            top_n,
            lang=_detect_intent_lang(user_intent),
        )
        try:
            _, response = self._retrieval_llm().ask_llm(prompt)
            names = parse_llm_json_response(response)
        except Exception as exc:
            logger.warning(f"[Retrieval] Final selection failed, keeping vector order: {exc}")
            return candidates[:top_n]
        if not isinstance(names, list):
            return candidates[:top_n]

        by_name = {candidate.name: candidate for candidate in candidates}
        selected = [by_name[name] for name in names if isinstance(name, str) and name in by_name]
        if not selected:
            logger.warning("[Retrieval] LLM selected no recalled candidate; keeping vector order")
            return candidates[:top_n]
        return selected[:top_n]

    def _vector_or_fallback(self, user_intent: str, top_n: int):
        """Vector results, or None when the caller must use the LLM path."""
        try:
            return self._vector_retrieve(user_intent, top_n)
        except Exception as exc:
            if vector_settings().strict:
                raise
            logger.error(f"[Retrieval] Vector retrieval unavailable, using the LLM path: {exc}")
            return None

    def retrieve_psop_by_intent(self, user_intent: str) -> Optional[PSOP]:
        logger.info("[Retrieval] retrieve_psop_by_intent: length={}", len(user_intent))
        if vector_settings().enabled:
            vector_results = self._vector_or_fallback(user_intent, 1)
            if vector_results is not None:
                return self._load_psop_by_id(vector_results[0].workflow_id) if vector_results else None
        try:
            names = self._retrieve_names_by_intent(user_intent, top_n=1)
            if not names:
                return None

            summaries = self._list_psop_summaries()
            name_to_id = {s.name: s.workflow_id for s in summaries}
            psop_id = name_to_id.get(names[0])
            if psop_id:
                return self._load_psop_by_id(psop_id)
            return None
        except Exception as e:
            raise Exception(f"Failed to retrieve PSOP by intent: {e}") from e

    def retrieve_psop_by_intent_topn(
        self, user_intent: str, top_n: int = 5
    ) -> List[WorkflowSearchResult]:
        logger.info("[Retrieval] retrieve_psop_by_intent_topn: length={}, top_n={}", len(user_intent), top_n)
        if vector_settings().enabled:
            vector_results = self._vector_or_fallback(user_intent, top_n)
            if vector_results is not None:
                logger.info(f"[Retrieval] TopN returned {len(vector_results)} result(s) via embeddings")
                return vector_results[:top_n]
        try:
            names = self._retrieve_names_by_intent(user_intent, top_n)
            name_to_summary = {s.name: s for s in self._list_psop_summaries()}
            results = [name_to_summary[name] for name in names if name in name_to_summary]
            logger.info(f"[Retrieval] TopN returned {len(results)} result(s) for intent")
            return results[:top_n]
        except Exception as e:
            raise Exception(f"Failed to retrieve PSOP topN by intent: {e}")
