# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Check ignore rules without tracked files hiding broken negations."""

from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("path,ignored", [
    ("data/workflow_templates/example.json", True),
    ("samples/workflow_templates/example.json", False),
    ("data/workflow_storage/psop/psop_spn_cross_city_diagnosis.json", False),
    ("data/workflow_storage/psop/customer.json", True),
    ("data/workflow_storage/psop/nested/customer.json", True),
    ("data/workflow_storage/execution_records/run.json", True),
    ("data/workflow_storage/preflow/draft.json", True),
    ("data/solution_packages/IG1526A_AN_L4_Wireless_Energy_Efficiency_Optimization_Solution_Package_v1.0.0.pdf", False),
    ("data/solution_packages/IG1526A_AN_L4_Wireless_Energy_Efficiency_Optimization_Solution_Package_v1.0.0.json", False),
    ("data/solution_packages/customer.json", True),
    ("data/solution_packages/customer.pdf", True),
    ("data/solution_packages/nested/customer.json", True),
    ("data/sandbox/report.json", True),
    ("data/workflow_storage/sandbox/report.json", True),
    ("data/other/result.json", True),
    ("log/server.log", True),
    ("common/log/new_module.py", False),
])
def test_seed_whitelist_and_runtime_exclusions(tmp_path, path, ignored):
    git = shutil.which("git")
    assert git is not None, "Repository contract tests require Git"
    subprocess.run(
        [git, "init", "-q", str(tmp_path)], check=True, capture_output=True, timeout=10,
    )
    shutil.copyfile(ROOT / ".gitignore", tmp_path / ".gitignore")
    candidate = tmp_path / path
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.touch()
    result = subprocess.run(
        [git, "-c", "core.excludesFile=", "check-ignore", "--no-index", "-q", path],
        cwd=tmp_path, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode in (0, 1), result.stderr
    assert (result.returncode == 0) is ignored, path
