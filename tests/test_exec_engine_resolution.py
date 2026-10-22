# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""events() role-resolution integration: resolution event, dispatch metadata, errors."""

import json
from pathlib import Path

import pytest

from orchestrate.core.model.instance_binding import (
    InstanceBinding, InstanceRegistry, ServiceScope, SkillMapping,
)
from orchestrate.core.model.psop import PSOP
from orchestrate.runtime.instance_projection import ResolutionRequest
from samples.role_pilot.technical_server import pilot_card

SEED_CATALOG = Path("samples/role_pilot/role_catalog.json")
OPTIMIZER = "ran-energy-optimizer"


class _CapturingClient:
    def __init__(self):
        self.contents = []

    async def stream_message(self, agent_name, content):
        self.contents.append(content)
        yield {"task_state": "COMPLETED", "metadata": {}}

    async def close(self):
        pass


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


def _engine(monkeypatch, cards, client):
    from orchestrate.runtime.exec_engine import OrchestrationEngine

    engine = OrchestrationEngine.__new__(OrchestrationEngine)
    engine._agent_cards = cards
    engine._target_agent = "Host Agent"
    monkeypatch.setattr(engine, "_get_engine_client", lambda: client)
    return engine


async def _collect(engine, intent, **kwargs):
    return [event async for event in engine.events(intent, **kwargs)]


@pytest.mark.asyncio
async def test_events_resolves_role_psop_and_dispatches_execution_copy(monkeypatch, tmp_path):
    monkeypatch.setattr("orchestrate.core.catalog_gate.configured_catalog_path",
                        lambda: _approved_catalog_file(tmp_path))
    monkeypatch.setattr("orchestrate.runtime.instance_projection.configured_registry_path",
                        lambda: _registry_file(tmp_path))
    client = _CapturingClient()
    engine = _engine(monkeypatch, [pilot_card("a", 1), pilot_card("b", 2)], client)
    psop = _role_psop()
    request = ResolutionRequest(scope="t/s/b", authorized_instance_ids=["inst-a", "inst-b"])

    events = await _collect(engine, "explore", psop=psop, resolution_request=request)

    resolution_events = [e for e in events if e["type"] == "resolution"]
    assert len(resolution_events) == 1
    data = resolution_events[0]["data"]
    assert data["catalog_version"] == "pilot-wireless-v1"
    assert data["execution_scope"] == "t/s/b"
    assert data["execution_id"]
    assert data["bindings"]
    assert data["card_fingerprints"]
    # Only inst-a satisfies the explore skill, so selection is pinned.
    assert data["bindings"][0]["instance_id"] == "inst-a"

    psop_updates = [e for e in events if e["type"] == "psop_update"]
    final_psop = psop_updates[-1]["data"]["psop"]
    assert all(task["binding"] == "instance"
               for step in final_psop["steps"] for task in step["subtasks"])
    assert final_psop["catalog_version"] is None

    assert len(client.contents) == 1
    metadata = client.contents[0].metadata
    binding = json.loads(metadata["__orch_binding__"])
    assert binding["config_version"] == "cfg-v1"
    assert binding["bindings"]
    cards = json.loads(metadata["__orch_cards__"])
    assert cards["cards"]
    assert cards["execution_id"] == data["execution_id"]
    assert metadata["__orch_psop_id__"] == psop.id


@pytest.mark.asyncio
async def test_events_resolution_failure_yields_structured_error_without_dispatch(monkeypatch, tmp_path):
    monkeypatch.setattr("orchestrate.core.catalog_gate.configured_catalog_path",
                        lambda: _approved_catalog_file(tmp_path))
    monkeypatch.setattr("orchestrate.runtime.instance_projection.configured_registry_path",
                        lambda: None)
    client = _CapturingClient()
    engine = _engine(monkeypatch, [], client)

    events = await _collect(engine, "explore", psop=_role_psop(),
                            resolution_request=ResolutionRequest(scope="t/s/b"))

    errors = [e for e in events if e["type"] == "error"]
    assert len(errors) == 1
    assert errors[0]["data"]["code"] == "RESOLUTION_INPUT_INVALID"
    assert client.contents == []


@pytest.mark.asyncio
async def test_events_catalog_unavailable_error(monkeypatch):
    monkeypatch.setattr("orchestrate.core.catalog_gate.configured_catalog_path", lambda: None)
    client = _CapturingClient()
    engine = _engine(monkeypatch, [], client)

    events = await _collect(engine, "explore", psop=_role_psop(),
                            resolution_request=ResolutionRequest(scope="t/s/b"))

    errors = [e for e in events if e["type"] == "error"]
    assert len(errors) == 1
    assert errors[0]["data"]["code"] == "CATALOG_VERSION_UNAVAILABLE"
    assert client.contents == []


@pytest.mark.asyncio
async def test_events_without_role_tasks_unchanged(monkeypatch):
    client = _CapturingClient()
    engine = _engine(monkeypatch, [], client)

    events = await _collect(engine, "do work", psop=_plain_psop())

    assert all(e["type"] != "resolution" for e in events)
    assert len(client.contents) == 1
    metadata = client.contents[0].metadata
    assert "__orch_binding__" not in metadata
    assert "__orch_cards__" not in metadata
    assert metadata["__orch_psop_id__"] == "wf-plain"
