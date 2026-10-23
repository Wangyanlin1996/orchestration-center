# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Versioned role dispatch wire contract, independent of authoring models.

Both the producer and Host validate these invariants. Workflow dictionaries
remain intact so the contract can prove that only declared bindings changed.
"""

import hashlib
import json
from copy import deepcopy
from typing import Annotated, Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from host_agent.dispatch_auth import DispatchValidationError

Identifier = Annotated[str, StringConstraints(min_length=1, max_length=1024, pattern=r"\S")]
BindingGroup = Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]
Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


def content_digest(value: dict[str, Any]) -> str:
    """Canonical role-pilot-v2 SHA-256, sorting only the authorization set."""
    value = deepcopy(value)
    if isinstance(value.get("context"), dict) and isinstance(value["context"].get("authorized_instance_ids"), list):
        value["context"]["authorized_instance_ids"] = sorted(value["context"]["authorized_instance_ids"])
    wire = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(wire.encode("utf-8")).hexdigest()


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class ExecutionScope(WireModel):
    tenant: Identifier
    site: Identifier
    business_object: Identifier

    @model_validator(mode="after")
    def require_concrete_scope(self):
        if any(value == "*" or value != value.strip() for value in self.model_dump().values()):
            raise ValueError("Execution scope must be concrete and normalized")
        return self

    def as_path(self) -> str:
        return f"{self.tenant}/{self.site}/{self.business_object}"


class ExecutionContext(WireModel):
    caller_id: Identifier
    scope: ExecutionScope
    authorized_instance_ids: list[Identifier]


class RoleBinding(WireModel):
    # Workflow identifiers follow PSOP, rather than catalog identifier limits.
    task_id: str
    role_id: Identifier
    role_version: Identifier
    role_skill_id: Identifier
    instance_id: Identifier
    instance_skill_id: Identifier
    execution_skill: Identifier
    binding_group: BindingGroup | None = None
    agent: Identifier
    endpoint: Identifier
    selection_reason: Identifier
    selected_priority: int
    candidates: list[Identifier]
    candidate_priorities: dict[Identifier, int]
    exclusions: dict[Identifier, list[Identifier]]


class FrozenCard(WireModel):
    instance_id: Identifier
    agent_name: Identifier
    endpoint: Identifier
    card: dict[str, Any]
    fingerprint: Digest


class TaskShape(BaseModel):
    """Only the task fields involved in binding; other workflow fields survive."""

    model_config = ConfigDict(extra="allow", strict=True)
    task_id: str
    agent: str
    skill: str
    binding: Literal["instance", "role"]
    role_version: Identifier | None
    binding_group: BindingGroup | None


class StepShape(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)
    name: str
    type: Literal["AllSuccess", "AnySuccess", "SelfLoop"]
    subtasks: list[TaskShape]


def _require(condition: bool, reason: str, message: str, binding: RoleBinding | None = None) -> None:
    if not condition:
        raise DispatchValidationError(message, reason=reason,
            task_ids=(binding.task_id,) if binding else (),
            instance_id=binding.instance_id if binding else None,
            binding_group=binding.binding_group if binding else None,
            role_ids=(binding.role_id,) if binding else ())


class RoleSnapshot(WireModel):
    schema_version: Literal["role-pilot-v2"] = "role-pilot-v2"
    execution_id: Identifier
    catalog_version: Identifier
    config_version: Identifier
    policy_version: Identifier
    context: ExecutionContext
    template: dict[str, Any]
    template_fingerprint: Digest
    execution_psop: dict[str, Any]
    bindings: list[RoleBinding] = Field(min_length=1)
    cards: list[FrozenCard] = Field(min_length=1)
    fingerprint: Digest

    @model_validator(mode="after")
    def verify(self):
        payload = self.model_dump(mode="json", exclude={"fingerprint"})
        _require(self.fingerprint == content_digest(payload), "SNAPSHOT_DIGEST", "Execution snapshot fingerprint mismatch")
        _require(self.template_fingerprint == content_digest(self.template), "TEMPLATE_DIGEST", "Template fingerprint mismatch")
        _require(self.catalog_version == self.template.get("catalog_version"), "CATALOG_REFERENCE", "Catalog version mismatch")
        _require(bool(self.template.get("id")), "TEMPLATE_ID", "Missing template identity")
        raw_steps = self.template.get("steps")
        _require(isinstance(raw_steps, list), "WORKFLOW_SCHEMA", "Invalid workflow steps")
        steps = [StepShape.model_validate(step) for step in raw_steps]
        tasks = [task for step in steps for task in step.subtasks]
        roles = {task.task_id: task for task in tasks if task.binding == "role"}
        _require(bool(roles), "TASK_COVERAGE", "Execution snapshots require role tasks")
        _require(len({task.task_id for task in tasks}) == len(tasks), "TASK_COVERAGE", "Duplicate task IDs")
        bindings = {binding.task_id: binding for binding in self.bindings}
        _require(len(bindings) == len(self.bindings) and set(bindings) == set(roles),
                 "TASK_COVERAGE", "Task bindings must cover the template exactly once")
        cards = {card.instance_id: card for card in self.cards}
        _require(len(cards) == len(self.cards) and set(cards) == {binding.instance_id for binding in self.bindings},
                 "CARD_COVERAGE", "Cards must cover selected instances exactly once")
        names = {card.agent_name for card in self.cards}
        legacy_names = {task.agent for task in tasks if task.binding == "instance"}
        _require(len(names) == len(cards) and not names.intersection(legacy_names),
                 "AGENT_NAME_COLLISION", "Duplicate selected agent name or legacy task conflict")
        for card in self.cards:
            _require(card.fingerprint == content_digest(card.card), "CARD_DIGEST", "Card fingerprint mismatch")
            _require(card.agent_name == card.card.get("name"), "CARD_IDENTITY", "Card identity mismatch")
            interfaces = card.card.get("supportedInterfaces", [])
            _require(isinstance(interfaces, list) and len(interfaces) == 1 and isinstance(interfaces[0], dict)
                     and interfaces[0].get("url") == card.endpoint and interfaces[0].get("protocolBinding") == "HTTP+JSON",
                     "CARD_INTERFACE", "Pilot requires one matching HTTP+JSON endpoint")
            endpoint = urlparse(card.endpoint)
            _require(endpoint.scheme in {"http", "https"} and bool(endpoint.hostname)
                     and endpoint.username is None and endpoint.password is None,
                     "CARD_INTERFACE", "Pilot endpoint must be HTTP(S) without embedded credentials")
            capabilities = card.card.get("capabilities", {})
            _require(isinstance(capabilities, dict), "CARD_SCHEMA", "Invalid card capabilities")
            extensions = capabilities.get("extensions", [])
            _require(not card.card.get("securitySchemes") and not card.card.get("securityRequirements")
                     and isinstance(extensions, list) and all(isinstance(ext, dict) and not ext.get("required") for ext in extensions),
                     "UNSUPPORTED_PREREQUISITE", "Role pilot does not support authentication or required extensions")
        self._verify_execution_copy(steps, bindings, cards)
        return self

    def _verify_execution_copy(self, steps: list[StepShape], bindings: dict[str, RoleBinding],
                               cards: dict[str, FrozenCard]) -> None:
        expected = deepcopy(self.template)
        expected["catalog_version"] = None
        groups: dict[str, tuple[str, str, str]] = {}
        for raw_step, step in zip(expected["steps"], steps, strict=True):
            for raw_task, task in zip(raw_step["subtasks"], step.subtasks, strict=True):
                if task.binding != "role":
                    _require(task.role_version is None and task.binding_group is None,
                             "ROLE_REFERENCE", "Instance tasks cannot carry role fields")
                    continue
                binding = bindings[task.task_id]
                _require(step.type != "SelfLoop", "ROLE_SELF_LOOP", "Role binding is not supported in SelfLoop", binding)
                _require((binding.role_id, binding.role_version, binding.role_skill_id, binding.binding_group) == (
                    task.agent, task.role_version, task.skill, task.binding_group),
                    "ROLE_REFERENCE", "Original role reference mismatch", binding)
                _require(binding.instance_id in self.context.authorized_instance_ids,
                         "NOT_AUTHORIZED", "Selected instance is not authorized", binding)
                if task.binding_group:
                    identity = (task.agent, binding.role_version, binding.instance_id)
                    _require(groups.setdefault(task.binding_group, identity) == identity,
                             "BINDING_GROUP", "Binding group instance mismatch", binding)
                card = cards[binding.instance_id]
                _require((binding.agent, binding.endpoint) == (card.agent_name, card.endpoint),
                         "CARD_IDENTITY", "Binding card identity mismatch", binding)
                skills = card.card.get("skills", [])
                _require(isinstance(skills, list) and all(isinstance(skill, dict) for skill in skills),
                         "CARD_SKILL", "Invalid card skills", binding)
                matching = [skill for skill in skills if skill.get("id") == binding.instance_skill_id]
                _require(len(matching) == 1 and matching[0].get("name") == binding.execution_skill,
                         "CARD_SKILL", "Selected skill mismatch", binding)
                raw_task.update(agent=binding.agent, skill=binding.execution_skill, binding="instance",
                                role_version=None, binding_group=None)
        _require(expected == self.execution_psop, "EXECUTION_COPY", "Execution copy differs from resolved template")

    def binding_metadata(self) -> dict[str, Any]:
        return {"catalog_version": self.catalog_version, "config_version": self.config_version,
                "policy_version": self.policy_version, "scope": self.context.scope.as_path(),
                "bindings": [binding.model_dump(mode="json") for binding in self.bindings]}
