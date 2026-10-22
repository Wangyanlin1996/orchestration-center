# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Frozen role bindings, including mixed templates. Hashes are not authentication."""

import hashlib
import json
from copy import deepcopy
from typing import Literal

from pydantic import Field, model_validator

from orchestrate.core.model.card_snapshot import AgentCardSnapshot, card_fingerprint
from orchestrate.core.model.instance_binding import ResolutionContext
from orchestrate.core.model.psop import PSOP
from orchestrate.core.model.role_catalog import CatalogModel, Identifier


def content_digest(value: dict) -> str:
    value = deepcopy(value)
    # Authorization IDs are a mathematical set, unlike ordered workflow/card arrays.
    if isinstance(value.get("context"), dict) and "authorized_instance_ids" in value["context"]:
        value["context"]["authorized_instance_ids"] = sorted(value["context"]["authorized_instance_ids"])
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class FrozenBinding(CatalogModel):
    task_id: Identifier
    role_id: Identifier
    role_version: Identifier
    role_skill_id: Identifier
    instance_id: Identifier
    instance_skill_id: Identifier
    execution_skill: Identifier
    binding_group: str | None = None
    agent: Identifier
    endpoint: Identifier
    selection_reason: Identifier
    selected_priority: int
    candidates: list[str]
    candidate_priorities: dict[str, int]
    exclusions: dict[str, list[str]]


class RoleExecutionSnapshot(CatalogModel):
    schema_version: Literal["role-pilot-v2"] = "role-pilot-v2"
    execution_id: Identifier
    catalog_version: Identifier
    config_version: Identifier
    policy_version: Identifier
    context: ResolutionContext
    template: PSOP
    template_fingerprint: Identifier
    execution_psop: PSOP
    bindings: list[FrozenBinding] = Field(min_length=1)
    cards: list[AgentCardSnapshot] = Field(min_length=1)
    fingerprint: Identifier

    @model_validator(mode="after")
    def verify(self):
        if self.fingerprint != content_digest(self.model_dump(mode="json", exclude={"fingerprint"})):
            raise ValueError("Execution snapshot fingerprint mismatch")
        if self.template_fingerprint != content_digest(self.template.model_dump(mode="json")):
            raise ValueError("Template fingerprint mismatch")
        if self.catalog_version != self.template.catalog_version:
            raise ValueError("Catalog version mismatch")
        original = {t.task_id: t for s in self.template.steps for t in s.subtasks if t.binding == "role"}
        if not original:
            raise ValueError("Execution snapshots require role tasks")
        bindings = {b.task_id: b for b in self.bindings}
        cards = {c.instance_id: c for c in self.cards}
        if len(bindings) != len(self.bindings) or set(bindings) != set(original):
            raise ValueError("Task bindings must cover the template exactly once")
        if len(cards) != len(self.cards) or set(cards) != {b.instance_id for b in self.bindings}:
            raise ValueError("Cards must cover selected instances exactly once")
        if len({c.agent_name for c in self.cards}) != len(cards):
            raise ValueError("Duplicate selected agent name")
        legacy_names = {t.agent for s in self.template.steps for t in s.subtasks if t.binding == "instance"}
        if legacy_names & {c.agent_name for c in self.cards}:
            raise ValueError("Selected agent name conflicts with legacy task")
        groups = {}
        for card in self.cards:
            if card.fingerprint != card_fingerprint(card.card):
                raise ValueError("Card fingerprint mismatch")
            if card.card.get("name") != card.agent_name:
                raise ValueError("Card identity mismatch")
            interfaces = card.card.get("supportedInterfaces", [])
            # Restrict the pilot to a single HTTP interface so SDK selection cannot drift.
            if len(interfaces) != 1 or interfaces[0].get("url") != card.endpoint or interfaces[0].get("protocolBinding") != "HTTP+JSON":
                raise ValueError("Pilot requires one matching HTTP+JSON endpoint")
        expected = self.template.model_dump(mode="json")
        expected["catalog_version"] = None
        for step in expected["steps"]:
            for task in step["subtasks"]:
                if task["binding"] != "role":
                    continue
                binding = bindings[task["task_id"]]
                if (binding.role_id, binding.role_version, binding.role_skill_id) != (task["agent"], task["role_version"], task["skill"]):
                    raise ValueError("Original role reference mismatch")
                if binding.instance_id not in self.context.authorized_instance_ids:
                    raise ValueError("Selected instance is not authorized")
                if task["binding_group"]:
                    previous = groups.setdefault(task["binding_group"], binding.instance_id)
                    if previous != binding.instance_id:
                        raise ValueError("Binding group instance mismatch")
                card = cards[binding.instance_id]
                if (binding.agent, binding.endpoint) != (card.agent_name, card.endpoint):
                    raise ValueError("Binding card identity mismatch")
                skills = card.card.get("skills", [])
                matching = [s for s in skills if s.get("id") == binding.instance_skill_id]
                if len(matching) != 1 or matching[0].get("name") != binding.execution_skill:
                    raise ValueError("Selected skill mismatch")
                task.update(agent=card.agent_name, skill=binding.execution_skill, binding="instance", role_version=None, binding_group=None)
        if expected != self.execution_psop.model_dump(mode="json"):
            raise ValueError("Execution copy differs from resolved template")
        return self


def freeze_role_execution(template: PSOP, result, cards: list[AgentCardSnapshot], execution_id: str) -> RoleExecutionSnapshot:
    """Detach all input data and validate the entire envelope before returning."""
    fields = FrozenBinding.model_fields
    payload = dict(schema_version="role-pilot-v2", execution_id=execution_id,
        catalog_version=result.catalog_version, config_version=result.config_version,
        policy_version=result.policy_version, context=result.context.model_dump(mode="json"),
        template=template.model_dump(mode="json"),
        template_fingerprint=content_digest(template.model_dump(mode="json")),
        execution_psop=result.execution_psop.model_dump(mode="json"),
        bindings=[{k: record[k] for k in fields} for record in result.bindings],
        cards=[card.model_dump(mode="json") for card in cards])
    # JSON serialization creates an independent transport boundary.
    payload = json.loads(json.dumps(payload, allow_nan=False))
    payload["fingerprint"] = content_digest(payload)
    return RoleExecutionSnapshot.model_validate(payload)
