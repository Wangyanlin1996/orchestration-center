# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: Apache-2.0
"""First SQL administrator must use the declared secret, not a default."""
import pytest
from orchestrate.server.security_preflight import initial_admin_password, SecurityPreflightError
from tests.test_storage_assembly import _install
from orchestrate import start


@pytest.fixture(autouse=True)
def no_ambient_secret(monkeypatch):
    monkeypatch.delenv("OC_ADMIN_INITIAL_PASSWORD", raising=False)


def test_file_password_seeds_after_schema(tmp_path, monkeypatch):
    password = tmp_path / "bootstrap"
    password.write_text("ConfiguredFile9!\r\n", encoding="utf-8")
    events = []
    _install(monkeypatch, events)
    start.initialize_storage({"admin_initial_password_file": str(password)})
    assert events == ["build", "check_ready", "initialize", ("seed", "ConfiguredFile9!", True)]


def test_environment_wins_without_trimming_password(tmp_path, monkeypatch):
    password = tmp_path / "bootstrap"
    password.write_text("OtherFile9!")
    monkeypatch.setenv("OC_ADMIN_INITIAL_PASSWORD", " ConfiguredEnv9! ")
    assert initial_admin_password({"admin_initial_password_file": str(password)}) == " ConfiguredEnv9! "


@pytest.mark.parametrize("value", ["", "short", "a" * 300, "ConfiguredEnv9!\nsecond"])
def test_invalid_explicit_environment_never_falls_back(tmp_path, monkeypatch, value):
    password = tmp_path / "bootstrap"
    password.write_text("ValidFile9!")
    monkeypatch.setenv("OC_ADMIN_INITIAL_PASSWORD", value)
    with pytest.raises(SecurityPreflightError):
        initial_admin_password({"admin_initial_password_file": str(password)})


def test_empty_store_without_secret_does_not_seed_default(monkeypatch):
    events = []
    _install(monkeypatch, events)
    with pytest.raises(SecurityPreflightError, match="Empty user store"):
        start.initialize_storage({})
    assert events == ["build", "check_ready", "initialize"]


def test_existing_store_never_reads_or_rotates_bootstrap(monkeypatch):
    events = []
    _install(monkeypatch, events, seed_result=False)
    monkeypatch.setenv("OC_ADMIN_INITIAL_PASSWORD", "invalid")
    start.initialize_storage({"admin_initial_password_file": "missing"})
    assert events == ["build", "check_ready", "initialize"]


def test_unreadable_file_error_does_not_include_path():
    with pytest.raises(SecurityPreflightError, match="Cannot read") as error:
        initial_admin_password({"admin_initial_password_file": "absent-private-path"})
    assert "absent-private-path" not in str(error.value)
