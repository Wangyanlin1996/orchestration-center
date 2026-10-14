# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Public onboarding must agree with the enforced account/bootstrap contract."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("relative, marker", [
    ("docs/en/Orchestration Center API Reference.md", "does not generate"),
    ("docs/zh/编排中心API参考.md", "不会自动生成"),
])
def test_intent_execution_documents_no_match_failure_not_automatic_generation(relative, marker):
    text = (ROOT / relative).read_text(encoding="utf-8")
    assert marker in text
    assert "No matching workflow found" in text
    assert "auto-generates if no match" not in text
    assert "无匹配则自动生成" not in text


def test_execute_request_schema_does_not_promise_generation_or_effective_name():
    from orchestrate.server.external_api import ExecuteRequest, execute_workflow

    import inspect

    schema = ExecuteRequest.model_json_schema()["properties"]
    assert "does not generate" in schema["task"]["description"]
    assert schema["name"]["deprecated"] is True
    assert "ignored" in schema["name"]["description"]
    assert "auto-generate" not in inspect.getdoc(execute_workflow)


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


@pytest.mark.parametrize("relative", [
    "README.md", "README_zh.md", "docs/DESIGN.md",
    "docs/en/Orchestration Center API Reference.md", "docs/zh/编排中心API参考.md",
])
def test_public_event_contract_does_not_invent_init_or_named_close(relative):
    text = (ROOT / relative).read_text(encoding="utf-8")
    assert '"type":"init"' not in text
    assert '"type": "init"' not in text
    assert "cancelled" in text


@pytest.mark.parametrize("relative", ["docs/zh/用户指南.md", "docs/zh/编排中心API参考.md"])
def test_pdf_input_heading_is_not_translated(relative):
    from orchestrate.server import frontend_support_server
    import inspect

    source = inspect.getsource(frontend_support_server)
    assert 'chapters_md.get("5. Interaction Flow")' in source
    assert "5. Interaction Flow" in (ROOT / relative).read_text(encoding="utf-8")


@pytest.mark.parametrize("relative", [
    "docs/en/Orchestration Center API Reference.md", "docs/zh/编排中心API参考.md",
])
@pytest.mark.parametrize("outcome", ["complete", "cancelled", None])
def test_documented_sse_parser_handles_heartbeat_unknown_events_and_cancellation(relative, outcome, monkeypatch):
    import requests

    text = (ROOT / relative).read_text(encoding="utf-8")
    start = text.index("import json\nimport os\nfrom urllib.parse import quote")
    snippet = text[start:text.index("\n```", start)]
    calls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def raise_for_status(self):
            pass

        def iter_lines(self, **kwargs):
            yield ": heartbeat"
            yield ""
            yield 'data: {"type":"future_extension","message":"optional payload"}'
            if outcome is not None:
                yield 'data: {"type":"' + outcome + '"}'

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setenv("OC_TOKEN", "test-only-token")
    monkeypatch.setenv("PSOP_ID", "test id")
    monkeypatch.delenv("OC_BASE_URL", raising=False)
    monkeypatch.setattr(requests, "get", get)
    scope = {}
    if outcome is None:
        with pytest.raises(RuntimeError):
            exec(compile(snippet, relative, "exec"), scope)
        assert scope["terminal"] is False
    else:
        exec(compile(snippet, relative, "exec"), scope)
        assert scope["terminal"] is True
    assert calls[0][0].endswith("/test%20id?lang=zh")
    assert calls[0][1]["headers"]["Authorization"] == "Bearer test-only-token"
    assert "verify" not in calls[0][1]  # requests' secure default is preserved.
