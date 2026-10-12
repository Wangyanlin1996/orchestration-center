# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Public onboarding must agree with the enforced account/bootstrap contract."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("relative", [
    "docs/en/Orchestration Center User Guide.md", "docs/zh/用户指南.md",
    "docs/en/Orchestration Center Development Guide.md", "docs/zh/开发指南.md",
    "docs/en/Orchestration Center API Reference.md", "docs/zh/编排中心API参考.md",
    "docs/en/MySQL Persistence.md", "docs/zh/MySQL持久化配置.md",
])
def test_current_guides_do_not_promise_default_password_or_anonymous_mode(relative):
    text = (ROOT / relative).read_text(encoding="utf-8")
    assert "OpenAN@2026" not in text
    assert "OC_ADMIN_INITIAL_PASSWORD" in text
    assert "No Security" not in text
    assert "所有 API 接口开放访问" not in text
    assert "authentication is disabled (backward compatible)" not in text


@pytest.mark.parametrize("relative", [
    "docs/en/Orchestration Center API Reference.md", "docs/zh/编排中心API参考.md"
])
def test_sandbox_paths_are_complete_and_unambiguous(relative):
    text = (ROOT / relative).read_text(encoding="utf-8")
    assert "`/orchestrate/sandbox/" not in text
    assert "`/rest/v1/orchestrate/sandbox/" in text


def test_legacy_gcp_guard_precedes_side_effects():
    text = (ROOT / "deploy-all.ps1").read_text(encoding="utf-8")
    assert text.index('throw "Legacy GCP') < text.index("Remove-Item")
    assert text.index('throw "Legacy GCP') < text.index("Get-Command gcloud")
