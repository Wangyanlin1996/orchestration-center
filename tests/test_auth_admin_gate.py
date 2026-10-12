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

import time

import pytest
from fastapi import HTTPException, Request

from orchestrate.server import auth as auth_module
from orchestrate.server.auth import _SessionStore, require_admin


def _make_request(token: str | None = None) -> Request:
    headers = []
    if token:
        headers.append((b"authorization", f"Bearer {token}".encode()))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/rest/v1/orchestrate/auth/users",
        "headers": headers,
        "query_string": b"",
    }
    return Request(scope)


class TestSessionStoreRole:
    def test_create_stores_role(self):
        store = _SessionStore()
        token, _ = store.create("alice", "admin")
        assert store.get_role(token) == "admin"

    def test_default_role_is_user(self):
        store = _SessionStore()
        token, _ = store.create("bob")
        assert store.get_role(token) == "user"

    def test_get_role_unknown_token(self):
        store = _SessionStore()
        assert store.get_role("does-not-exist") is None

    def test_get_role_expired_token(self):
        store = _SessionStore()
        token, _ = store.create("carol", "admin")
        username, role, _ = store._tokens[token]
        store._tokens[token] = (username, role, time.time() - 1)
        assert store.get_role(token) is None
        # Expired lookups also evict the entry.
        assert token not in store._tokens


class TestRequireAdmin:
    """Regression coverage for #7: admin-only gate on /auth/users*."""

    def test_admin_token_passes(self, monkeypatch):
        monkeypatch.setattr(auth_module, "is_auth_enabled", lambda: True)
        store = auth_module.get_session_store()
        token, _ = store.create("admin_user", "admin")
        try:
            require_admin(_make_request(token))  # must not raise
        finally:
            store.revoke(token)

    def test_non_admin_token_rejected(self, monkeypatch):
        monkeypatch.setattr(auth_module, "is_auth_enabled", lambda: True)
        store = auth_module.get_session_store()
        token, _ = store.create("regular_user", "user")
        try:
            with pytest.raises(HTTPException) as exc_info:
                require_admin(_make_request(token))
            assert exc_info.value.status_code == 403
        finally:
            store.revoke(token)

    def test_missing_token_rejected(self, monkeypatch):
        monkeypatch.setattr(auth_module, "is_auth_enabled", lambda: True)
        with pytest.raises(HTTPException) as exc_info:
            require_admin(_make_request(None))
        assert exc_info.value.status_code == 403

    def test_invalid_token_rejected(self, monkeypatch):
        monkeypatch.setattr(auth_module, "is_auth_enabled", lambda: True)
        with pytest.raises(HTTPException) as exc_info:
            require_admin(_make_request("not-a-real-token"))
        assert exc_info.value.status_code == 403

    def test_unconfigured_auth_fails_closed_without_middleware(self, monkeypatch):
        monkeypatch.setattr(auth_module, "is_auth_enabled", lambda: False)
        with pytest.raises(HTTPException) as exc_info:
            require_admin(_make_request(None))
        assert exc_info.value.status_code == 503
