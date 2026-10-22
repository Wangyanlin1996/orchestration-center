# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Dispatch-side assembly: scope parsing, config fallback, projection, frozen plans."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from orchestrate.core.model.instance_binding import (
    InstanceBinding, InstanceRegistry, ServiceScope, SkillMapping,
)
from orchestrate.core.model.psop import PSOP
from orchestrate.persistence.errors import RoleReferenceError
from orchestrate.runtime.instance_projection import (
    ResolutionError, ResolutionRequest, build_context_and_policy, parse_scope,
    project_observations, resolve_execution_plan,
)
from samples.role_pilot.technical_server import pilot_card


def test_parse_scope_splits_three_parts():
    scope = parse_scope("operator-a/city-a/ran-domain-a")
    assert scope == ServiceScope(tenant="operator-a", site="city-a", business_object="ran-domain-a")


def test_parse_scope_rejects_wrong_part_count():
    with pytest.raises(ResolutionError) as exc:
        parse_scope("operator-a/city-a")
    assert exc.value.code == "RESOLUTION_INPUT_INVALID"


def test_build_context_requires_scope():
    with pytest.raises(ResolutionError) as exc:
        build_context_and_policy(ResolutionRequest())
    assert exc.value.code == "RESOLUTION_INPUT_INVALID"


def test_build_context_prefers_request_over_config(monkeypatch):
    monkeypatch.setattr(
        "orchestrate.runtime.instance_projection.configured_execution_scope",
        lambda: "cfg-t/cfg-s/cfg-b",
    )
    context, policy = build_context_and_policy(ResolutionRequest(
        scope="req-t/req-s/req-b",
        authorized_instance_ids=["inst-1"],
        caller_id="tester",
    ))
    assert context.scope.tenant == "req-t"
    assert context.authorized_instance_ids == {"inst-1"}
    assert context.caller_id == "tester"


def test_build_context_falls_back_to_config(monkeypatch):
    monkeypatch.setattr(
        "orchestrate.runtime.instance_projection.configured_execution_scope",
        lambda: "cfg-t/cfg-s/cfg-b",
    )
    monkeypatch.setattr(
        "orchestrate.runtime.instance_projection.configured_authorized_instances",
        lambda: ["inst-a", "inst-b"],
    )
    context, policy = build_context_and_policy(ResolutionRequest())
    assert context.scope == ServiceScope(tenant="cfg-t", site="cfg-s", business_object="cfg-b")
    assert context.authorized_instance_ids == {"inst-a", "inst-b"}
    assert context.caller_id == "orchestration-center"


def test_build_policy_defaults():
    context, policy = build_context_and_policy(ResolutionRequest(scope="t/s/b"))
    assert policy.policy_version == "policy-v1"
    assert policy.tie_break == "error"
    assert policy.task_overrides == {} and policy.group_overrides == {}


def _card(name, url, skill_ids):
    return SimpleNamespace(
        name=name, url=url, skills=[SimpleNamespace(id=sid, name=sid) for sid in skill_ids],
    )


def _registry():
    return InstanceRegistry(config_version="cfg-v1", instances=[
        InstanceBinding(
            instance_id="inst-a", agent_name="agent-a", endpoint="http://a:1",
            enabled=True, technical_status="passed",
            scopes=[ServiceScope(tenant="t", site="s", business_object="b")],
            skills=[SkillMapping(role_id="r", role_version="v1", skill_id="sk",
                                 instance_skill_id="exp-a", execution_skill="exp-a")],
        ),
        InstanceBinding(
            instance_id="inst-b", agent_name="agent-b", endpoint="http://b:2",
            enabled=True, technical_status="passed",
            scopes=[ServiceScope(tenant="t", site="s", business_object="b")],
            skills=[SkillMapping(role_id="r", role_version="v1", skill_id="sk",
                                 instance_skill_id="exp-b", execution_skill="exp-b")],
        ),
    ])


def test_projection_matches_by_name_and_endpoint():
    cards = [_card("agent-a", "http://a:1", ["exp-a"]), _card("agent-b", "http://other", ["exp-b"])]
    observed = project_observations(_registry(), cards)
    assert [o.instance_id for o in observed] == ["inst-a"]
    assert observed[0].skills == {"exp-a": "exp-a"}
    assert observed[0].prerequisites_passed is True


def test_projection_skips_missing_cards():
    assert project_observations(_registry(), []) == []


SEED_CATALOG = Path("samples/role_pilot/role_catalog.json")
OPTIMIZER = "ran-energy-optimizer"


def _approve_all(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "review_status":
                value[key] = "approved"
            else:
                _approve_all(item)
    elif isinstance(value, list):
        for item in value:
            _approve_all(item)


def _approved_catalog_file(tmp_path):
    data = json.loads(SEED_CATALOG.read_text(encoding="utf-8"))
    _approve_all(data)
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(path)


def _registry_file(tmp_path):
    scope = ServiceScope(tenant="t", site="s", business_object="b")
    registry = InstanceRegistry(config_version="cfg-v1", instances=[
        InstanceBinding(
            instance_id="inst-a", agent_name="Technical RAN A", endpoint="http://127.0.0.1:1",
            enabled=True, technical_status="passed", scopes=[scope],
            skills=[SkillMapping(role_id=OPTIMIZER, role_version="1.0.0",
                                 skill_id="explore-energy-intent",
                                 instance_skill_id="explore-a", execution_skill="Explore A")],
        ),
        InstanceBinding(
            instance_id="inst-b", agent_name="Technical RAN B", endpoint="http://127.0.0.1:2",
            enabled=True, technical_status="passed", scopes=[scope],
            skills=[SkillMapping(role_id=OPTIMIZER, role_version="1.0.0",
                                 skill_id="fulfill-energy-intent",
                                 instance_skill_id="explore-b", execution_skill="Explore B")],
        ),
    ])
    path = tmp_path / "registry.json"
    path.write_text(registry.model_dump_json(), encoding="utf-8")
    return str(path)


def _role_psop():
    return PSOP.model_validate(dict(
        id="wf-role-pilot", name="Role pilot", catalog_version="pilot-wireless-v1",
        steps=[dict(name="explore", subtasks=[dict(
            task_id="t1", description="Explore energy intent", binding="role",
            agent=OPTIMIZER, skill="explore-energy-intent", role_version="1.0.0",
        )])],
    ))


def _plain_psop():
    return PSOP.model_validate(dict(
        id="wf-plain", name="Plain",
        steps=[dict(name="work", subtasks=[dict(
            task_id="t1", description="Do work", binding="instance",
            agent="Legacy Agent", skill="Legacy Skill",
        )])],
    ))


def test_resolve_execution_plan_happy_path(monkeypatch, tmp_path):
    monkeypatch.setattr("orchestrate.core.catalog_gate.configured_catalog_path",
                        lambda: _approved_catalog_file(tmp_path))
    monkeypatch.setattr("orchestrate.runtime.instance_projection.configured_registry_path",
                        lambda: _registry_file(tmp_path))
    psop = _role_psop()
    request = ResolutionRequest(scope="t/s/b", authorized_instance_ids=["inst-a", "inst-b"])
    cards = [pilot_card("a", 1), pilot_card("b", 2)]
    snapshot = resolve_execution_plan(psop, request, cards)
    assert snapshot.execution_psop.id == psop.id
    assert all(task.binding == "instance"
               for step in snapshot.execution_psop.steps for task in step.subtasks)
    assert snapshot.execution_psop.catalog_version is None
    assert snapshot.bindings and snapshot.cards
    assert snapshot.execution_id


def test_resolve_execution_plan_requires_role_tasks():
    with pytest.raises(ResolutionError) as exc:
        resolve_execution_plan(_plain_psop(), ResolutionRequest(scope="t/s/b"), [])
    assert exc.value.code == "RESOLUTION_INPUT_INVALID"


def test_resolve_execution_plan_requires_registry(monkeypatch, tmp_path):
    monkeypatch.setattr("orchestrate.core.catalog_gate.configured_catalog_path",
                        lambda: _approved_catalog_file(tmp_path))
    monkeypatch.setattr("orchestrate.runtime.instance_projection.configured_registry_path",
                        lambda: None)
    with pytest.raises(ResolutionError) as exc:
        resolve_execution_plan(_role_psop(), ResolutionRequest(scope="t/s/b"), [])
    assert exc.value.code == "RESOLUTION_INPUT_INVALID"


def test_resolve_execution_plan_catalog_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr("orchestrate.core.catalog_gate.configured_catalog_path",
                        lambda: None)
    with pytest.raises(RoleReferenceError) as exc:
        resolve_execution_plan(_role_psop(), ResolutionRequest(scope="t/s/b"), [])
    assert "CATALOG_VERSION_UNAVAILABLE" in str(exc.value)
