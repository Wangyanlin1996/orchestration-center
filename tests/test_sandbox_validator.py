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

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from orchestrate.core.model.psop import PSOP, JumpCondition, Step, StepType, Task
from orchestrate.validation.sandbox_validator import (
    SandboxCheckStatus,
    validate_sandbox_static,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

TASK_T = "https://projects.tmforum.org/a2aproject/telecommunication/extensions/Task-T/v1"
NEGOTIATION_T = "https://projects.tmforum.org/a2aproject/telecommunication/extensions/Negotiation-T/v1"


def test_validator_can_be_imported_before_sandbox_package():
    # A child interpreter imports ``orchestrate`` from its working directory, so pin the
    # repository root instead of inheriting the directory pytest happened to start in.
    result = subprocess.run(
        [sys.executable, "-c", "from orchestrate.validation.sandbox_validator import SandboxCheck"],
        capture_output=True,
        text=True,
        check=False,
        cwd=PROJECT_ROOT,
    )
    assert result.returncode == 0, result.stderr


def _step(name, agents=("agent-a",), next_steps=(), context_from=None, step_type=StepType.ALL_SUCCESS):
    return Step(
        name=name,
        subtasks=[
            Task(description=f"diagnose {name}", agent=agent, skill=f"skill-{name}")
            for agent in agents
        ],
        next=[JumpCondition(step=target, condition="") for target in next_steps],
        context_from=context_from,
        type=step_type,
    )


def _workflow(*steps):
    return PSOP(name="sandbox workflow", steps=list(steps))


def _card(name="agent-a", extensions=(TASK_T,), skills=("skill-a",)):
    return SimpleNamespace(
        name=name,
        capabilities=SimpleNamespace(
            extensions=[SimpleNamespace(uri=uri) for uri in extensions],
        ),
        skills=[SimpleNamespace(id=skill, name=skill, description=skill) for skill in skills],
    )


def test_reports_cycle_and_unreachable_steps():
    report = validate_sandbox_static(_workflow(
        _step("a", next_steps=("b",)),
        _step("b", next_steps=("a",)),
        _step("orphan"),
    ))

    cycle = next(check for check in report.checks if check.check_id == "structure.cycle")
    assert cycle.status == SandboxCheckStatus.FAIL
    assert set(cycle.affected) == {"a", "b"}
    reachability = next(check for check in report.checks if check.check_id == "structure.reachability")
    assert reachability.status == SandboxCheckStatus.WARNING
    assert "orphan" in reachability.affected
    assert report.verdict == SandboxCheckStatus.FAIL


def test_reports_invalid_context_and_structure():
    report = validate_sandbox_static(_workflow(
        _step("a", next_steps=("b",)),
        _step("b", context_from=["missing"]),
    ), lang="en")

    context = next(check for check in report.checks if check.check_id == "structure.context_sources")
    assert context.status == SandboxCheckStatus.FAIL
    assert any("does not exist" in issue for issue in context.evidence)
    assert report.model_dump()["workflow_id"]


def test_reports_missing_agent_and_extension_capabilities():
    report = validate_sandbox_static(
        _workflow(
            _step("missing", agents=("missing",)),
            _step("a", agents=("agent-a",)),
        ),
        [_card(extensions=())],
    )

    missing = next(check for check in report.checks if check.check_id == "agents.missing")
    task_t = next(check for check in report.checks if check.check_id == "agents.task_t_extension")
    assert missing.status == SandboxCheckStatus.FAIL
    assert task_t.status == SandboxCheckStatus.FAIL
    assert report.verdict == SandboxCheckStatus.FAIL


def test_reports_skill_mismatch_without_failing_workflow():
    report = validate_sandbox_static(
        _workflow(_step("a")),
        [_card(skills=("different-skill",))],
    )

    skill = next(check for check in report.checks if check.check_id == "agents.skill_match")
    assert skill.status == SandboxCheckStatus.WARNING
    assert report.verdict == SandboxCheckStatus.WARNING


def test_all_checks_pass_for_matching_workflow():
    report = validate_sandbox_static(
        _workflow(
            _step("a", next_steps=("merge",)),
            _step("merge", context_from=["a"], step_type=StepType.SELF_LOOP),
        ),
        [_card()],
    )

    assert report.verdict == SandboxCheckStatus.PASS
    assert all(check.status == SandboxCheckStatus.PASS for check in report.checks)
