# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""The composition root: one decision point and one explicit startup order.

The order is the contract. Storage must be proven reachable before any schema is
written, and the operator account is only bootstrapped after the schema exists.
These tests drive ``initialize_storage`` with a fake context so the order can be
asserted directly instead of inferred from log lines.
"""

import pytest
from types import SimpleNamespace

from orchestrate import start
from orchestrate.core.persistence import WorkflowStorage
from orchestrate.persistence import StorageContext, StorageUnavailableError
from orchestrate.persistence.file_backend import FilePersistenceBackend


class _FakeStorage:
    """Records what the composition root asks of a backend, in order."""

    def __init__(self, events, mode="postgresql", has_users=True, ready=True):
        self._events = events
        self.mode = mode
        self.has_users = has_users
        self._ready = ready

    def check_ready(self):
        self._events.append("check_ready")
        if not self._ready:
            raise StorageUnavailableError("database is not reachable")

    def initialize(self):
        self._events.append("initialize")

    def close(self):
        self._events.append("close")


def _install(monkeypatch, events, **kwargs):
    seed_result = kwargs.pop("seed_result", True)
    storage = _FakeStorage(events, **kwargs)
    storage.users = SimpleNamespace(has_any=lambda: not seed_result)
    # A fake composition root must not replace other API tests' real context.
    monkeypatch.setattr(start, "configure_context", lambda context: context)
    monkeypatch.setattr(start, "build_context", lambda conf=None: (events.append("build"), storage)[1])
    monkeypatch.setattr(
        start, "seed_admin_if_empty",
        lambda password: (events.append(("seed", password, seed_result)), seed_result)[1],
    )
    return storage


def test_startup_order_is_reachability_then_schema_then_seed(monkeypatch):
    events = []
    storage = _install(monkeypatch, events)
    monkeypatch.setenv("OC_ADMIN_INITIAL_PASSWORD", "ConfiguredAdmin9!")

    result = start.initialize_storage({"persistence_mode": "postgresql"})

    assert result is storage
    assert events == ["build", "check_ready", "initialize", ("seed", "ConfiguredAdmin9!", True)]


def test_existing_users_skip_the_seed(monkeypatch):
    events = []
    _install(monkeypatch, events, seed_result=False)

    # Users already exist: the seed reports that and startup continues.
    start.initialize_storage({})

    assert events == ["build", "check_ready", "initialize"]


def test_unreachable_storage_aborts_before_the_schema_is_touched(monkeypatch):
    events = []
    _install(monkeypatch, events, ready=False)

    with pytest.raises(StorageUnavailableError):
        start.initialize_storage({})

    # No DDL, no seed: an unreachable database must stop the process, not let it
    # serve traffic that silently answers "no data".
    assert events == ["build", "check_ready"]


def test_file_mode_has_no_user_store_to_seed(monkeypatch):
    events = []
    _install(monkeypatch, events, mode="file", has_users=False)

    storage = start.initialize_storage({})

    assert storage.mode == "file"
    assert events == ["build", "check_ready", "initialize"]


def test_the_real_file_backend_survives_the_whole_startup_sequence(tmp_path, monkeypatch):
    # No fake here: the default backend must really pass check_ready(),
    # initialize() and close(), and really report that it has no user store.
    context = StorageContext(FilePersistenceBackend(storage=WorkflowStorage(str(tmp_path))))
    monkeypatch.setattr(start, "build_context", lambda conf=None: context)

    storage = start.initialize_storage({"persistence_mode": "file"})
    storage.close()

    assert storage.has_users is False
    assert (tmp_path / "workflow_storage" / "psop").is_dir()
