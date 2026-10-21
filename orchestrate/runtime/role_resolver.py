# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Pure, deterministic selection for technical pilots; no dispatch or I/O.

This returns a proposed execution copy. Host verification and full-card freezing
must be connected before these results may be dispatched in production.
"""

from copy import deepcopy
from dataclasses import dataclass

from orchestrate.core.model.instance_binding import (
    InstanceRegistry, ObservedInstance, ResolutionContext, ResolutionPolicy,
)
from orchestrate.core.model.psop import PSOP
from orchestrate.core.model.role_catalog import RoleCatalog


class ResolutionError(ValueError):
    def __init__(self, code, message, *, task_ids=(), binding_group=None, exclusions=None, candidates=()):
        self.code = code
        self.task_ids = list(task_ids)
        self.binding_group = binding_group
        self.exclusions = deepcopy(exclusions or {})
        self.candidates = list(candidates)
        super().__init__(f"{code}: {message}")


@dataclass
class ResolutionResult:
    execution_psop: PSOP
    bindings: list[dict]
    catalog_version: str
    config_version: str
    policy_version: str
    context: ResolutionContext


def resolve_role_bindings(
    psop: PSOP,
    catalog: RoleCatalog,
    registry: InstanceRegistry,
    observations: list[ObservedInstance],
    context: ResolutionContext,
    policy: ResolutionPolicy,
) -> ResolutionResult:
    # Revalidate to catch callers mutating Pydantic objects after construction.
    psop = PSOP.model_validate(psop.model_dump())
    catalog = RoleCatalog.model_validate(catalog.model_dump())
    registry = InstanceRegistry.model_validate(registry.model_dump())
    context = ResolutionContext.model_validate(context.model_dump())
    policy = ResolutionPolicy.model_validate(policy.model_dump())
    observations = [ObservedInstance.model_validate(o.model_dump()) for o in observations]
    tasks = [t for step in psop.steps for t in step.subtasks if t.binding == "role"]
    try:
        catalog.validate_workflow(psop)
    except ValueError as exc:
        code = str(exc).split(":")[0]
        raise ResolutionError(code, str(exc), task_ids=[t.task_id for t in tasks]) from exc

    observed = {o.instance_id: o for o in observations}
    if len(observed) != len(observations):
        raise ResolutionError("INSTANCE_SNAPSHOT_MISMATCH", "Duplicate observed instance ID")
    ids = {t.task_id for t in tasks}
    groups = {t.binding_group for t in tasks if t.binding_group}
    if set(policy.task_overrides) - ids or set(policy.group_overrides) - groups:
        raise ResolutionError("INVALID_OVERRIDE", "Override refers to unknown role task or group")

    units = {}
    for task in tasks:
        # Namespace group IDs independently of task IDs.
        key = ("group", task.binding_group) if task.binding_group else ("task", task.task_id)
        units.setdefault(key, []).append(task)
    selected = {}
    records = []
    for (kind, key), members in units.items():
        exclusions = {}
        candidates = []
        mappings = {}
        for instance in sorted(registry.instances, key=lambda i: i.instance_id):
            reasons = []
            card = observed.get(instance.instance_id)
            if not instance.enabled or instance.technical_status != "passed":
                reasons.append("TECHNICAL_ADMISSION_REQUIRED")
            if instance.instance_id not in context.authorized_instance_ids:
                reasons.append("NOT_AUTHORIZED")
            if not any(scope.covers(context.scope) for scope in instance.scopes):
                reasons.append("OUT_OF_SCOPE")
            if card is None:
                reasons.append("INSTANCE_NOT_VISIBLE")
            elif (card.agent_name, card.endpoint) != (instance.agent_name, instance.endpoint):
                reasons.append("INSTANCE_SNAPSHOT_MISMATCH")
            if card is not None and not card.prerequisites_passed:
                reasons.append("PREREQUISITES_NOT_MET")
            index = {(s.role_id, s.role_version, s.skill_id): s for s in instance.skills}
            for task in members:
                mapping = index.get((task.agent, task.role_version, task.skill))
                if mapping is None:
                    reasons.append("MISSING_ROLE_SKILL")
                elif card is not None and card.skills.get(mapping.instance_skill_id) != mapping.execution_skill:
                    reasons.append("INSTANCE_SKILL_MISMATCH")
            if reasons:
                exclusions[instance.instance_id] = sorted(set(reasons))
            else:
                candidates.append(instance)
                mappings[instance.instance_id] = index

        overrides = {policy.task_overrides[t.task_id] for t in members if t.task_id in policy.task_overrides}
        if kind == "group" and key in policy.group_overrides:
            overrides.add(policy.group_overrides[key])
        detail = dict(task_ids=[t.task_id for t in members],
                      binding_group=key if kind == "group" else None,
                      exclusions=exclusions,
                      candidates=[i.instance_id for i in candidates])
        if len(overrides) > 1:
            raise ResolutionError("INVALID_OVERRIDE", "Conflicting group overrides", **detail)
        if overrides:
            chosen = next((i for i in candidates if i.instance_id in overrides), None)
            if chosen is None:
                raise ResolutionError("INVALID_OVERRIDE", "Override fails hard constraints", **detail)
            reason = "explicit_override"
        else:
            if not candidates:
                code = "BINDING_GROUP_UNSATISFIED" if kind == "group" else "NO_ELIGIBLE_INSTANCE"
                raise ResolutionError(code, "No instance satisfies all required skills and scope", **detail)
            best = max(i.priority for i in candidates)
            top = [i for i in candidates if i.priority == best]
            if len(top) > 1 and policy.tie_break == "error":
                raise ResolutionError("AMBIGUOUS_BINDING", "Equal-priority candidates", **detail)
            chosen = min(top, key=lambda i: i.instance_id)
            reason = "instance_id_tie_break" if len(top) > 1 else "highest_priority"
        for task in members:
            mapping = mappings[chosen.instance_id][(task.agent, task.role_version, task.skill)]
            selected[task.task_id] = (chosen, mapping)
            records.append({
                "task_id": task.task_id, "binding_group": task.binding_group,
                "role_id": task.agent, "role_version": task.role_version,
                "role_skill_id": task.skill, "instance_id": chosen.instance_id,
                "agent": chosen.agent_name, "endpoint": chosen.endpoint,
                "instance_skill_id": mapping.instance_skill_id,
                "execution_skill": mapping.execution_skill,
                "selection_reason": reason,
                "selected_priority": chosen.priority,
                "candidates": [i.instance_id for i in candidates],
                "candidate_priorities": {i.instance_id: i.priority for i in candidates},
                "exclusions": deepcopy(exclusions),
            })

    names = {}
    legacy_names = {t.agent for s in psop.steps for t in s.subtasks if t.binding == "instance"}
    for instance, _ in selected.values():
        previous = names.setdefault(instance.agent_name, instance.instance_id)
        if previous != instance.instance_id or instance.agent_name in legacy_names:
            raise ResolutionError(
                "INSTANCE_SNAPSHOT_MISMATCH",
                "Selected name is ambiguous with another selected or legacy instance",
            )
    data = psop.model_dump(mode="json")
    data["catalog_version"] = None
    for step in data["steps"]:
        for task in step["subtasks"]:
            if task["task_id"] not in selected:
                continue
            instance, mapping = selected[task["task_id"]]
            task.update(agent=instance.agent_name, skill=mapping.execution_skill,
                        binding="instance", role_version=None, binding_group=None)
    return ResolutionResult(
        execution_psop=PSOP.model_validate(data), bindings=records,
        catalog_version=catalog.catalog_version, config_version=registry.config_version,
        policy_version=policy.policy_version, context=context.model_copy(deep=True),
    )
