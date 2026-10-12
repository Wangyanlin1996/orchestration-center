# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Shared account authentication; synthetic credentials and isolated storage only."""
import hashlib
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi.testclient import TestClient
import pytest

from orchestrate.server import account_api, auth, frontend_support_server as server, middleware
from orchestrate.server.external_auth import external_auth_mode
from orchestrate.server.gateway_policy import BROWSER_GATEWAY_HEADER
from orchestrate.persistence.errors import StorageUnavailableError

CREDENTIALS = {"username": "admin", "password": "AccountUser9!"}


@pytest.fixture
def accounts(monkeypatch):
    conf = {"ip": "0.0.0.0", "enable_https": "false", "persistence_mode": "file",
            "access_password": hashlib.sha256(CREDENTIALS["password"].encode()).hexdigest(),
            "access_token_ttl": "60"}
    context = SimpleNamespace(has_users=False)
    monkeypatch.delenv("TESTING", raising=False)
    monkeypatch.setattr(auth, "get_conf", lambda: conf)
    monkeypatch.setattr(server, "get_conf", lambda: conf)
    for module in (auth, server, account_api):
        monkeypatch.setattr(module, "current_context", lambda: context)
    monkeypatch.setattr(auth, "_session_store", auth._SessionStore())
    monkeypatch.setattr(auth, "_pending_password_change", set())
    monkeypatch.setattr(middleware, "limiter", middleware.strategies.MovingWindowRateLimiter(middleware.storage.MemoryStorage()))
    # Avoid coupling this account contract test to workflow/engine side effects.
    client = TestClient(server.app)
    yield client, conf, context
    client.close()


def issue(client):
    response = client.post("/api/v1/auth/token", json=CREDENTIALS)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert set(payload) == {"access_token", "token_type", "expires_in"}
    assert payload["token_type"] == "Bearer" and payload["expires_in"] == 60
    assert len(payload["access_token"]) >= 32
    assert response.headers["cache-control"] == "no-store"
    assert "set-cookie" not in response.headers
    return {"Authorization": "Bearer " + payload["access_token"]}


@pytest.mark.parametrize("https", ["false", "true"])
def test_removed_dev_flag_cannot_bypass_login(accounts, https):
    client, conf, _ = accounts
    conf.update({"ip": "127.0.0.1", "enable_https": https, "security.dev_insecure_mode": "true"})
    assert auth.is_auth_enabled() is True
    assert client.get("/api/v1/no-such-route").status_code == 401
    assert client.get("/rest/v1/orchestrate/no-such-route").status_code == 401
    assert client.get("/api/v1/no-such-route", headers=issue(client)).status_code == 404


def test_testing_env_does_not_disable_configured_authentication(accounts, monkeypatch):
    client, _, _ = accounts
    monkeypatch.setenv("TESTING", "true")
    assert auth.is_auth_enabled() is True
    assert client.get("/rest/v1/orchestrate/no-such-route").status_code == 401


@pytest.mark.parametrize("path", ["/api/v1/no-such-route", "/rest/v1/orchestrate/no-such-route", "/psops"])
def test_unconfigured_account_never_opens_business_routes(accounts, path):
    client, conf, _ = accounts
    conf.update({"ip": "127.0.0.1", "access_password": "", "security.dev_insecure_mode": "true"})
    assert client.get(path).status_code == 503


def test_account_token_is_shared_with_frontend_identity(accounts):
    client, _, _ = accounts
    bearer = issue(client)
    check = client.get("/rest/v1/orchestrate/auth/check", headers=bearer).json()["data"]
    assert check["authenticated"] and check["username"] == "admin" and check["role"] == "admin"
    assert client.get("/api/v1/no-such-route", headers=bearer).status_code == 404
    assert client.post("/api/v1/auth/logout", headers=bearer).status_code == 200
    assert client.get("/api/v1/no-such-route", headers=bearer).status_code == 401
    assert not client.get("/rest/v1/orchestrate/auth/check", headers=bearer).json()["data"]["authenticated"]


def test_web_login_token_is_accepted_only_as_explicit_bearer_by_public_api(accounts):
    client, _, _ = accounts
    login = client.post("/rest/v1/orchestrate/auth/login", json=CREDENTIALS)
    assert login.status_code == 200 and "access_token" not in login.json()["data"]
    assert "httponly" in login.headers["set-cookie"].lower()
    token = client.cookies.get(auth.SESSION_COOKIE_NAME)
    assert token
    assert client.get("/api/v1/no-such-route").status_code == 401
    assert client.get("/api/v1/no-such-route", headers={"Authorization": "Bearer " + token}).status_code == 404
    assert not client.get("/rest/v1/orchestrate/auth/check", headers={"Authorization": "Bearer invalid"}).json()["data"]["authenticated"]
    assert client.post("/api/v1/auth/logout").status_code == 401
    assert client.get("/rest/v1/orchestrate/auth/check").json()["data"]["authenticated"]


def test_expiration_and_user_revocation(accounts, monkeypatch):
    client, _, _ = accounts
    bearer = issue(client)
    store = auth.get_session_store()
    token = bearer["Authorization"].split()[1]
    username, role, expiry = store._tokens[token]
    monkeypatch.setattr(auth.time, "time", lambda: expiry)
    assert client.get("/api/v1/no-such-route", headers=bearer).status_code == 401
    assert token not in store._tokens
    first, _ = store.create(username, role)
    second, _ = store.create(username, role)
    other, _ = store.create("another-user", "user")
    store.revoke_user(username)
    assert store.identity(first) is None and store.identity(second) is None
    assert store.identity(other).username == "another-user"


@pytest.mark.parametrize("header", ["Basic ignored", "Bearer", "Bearer a b", "Bearer invalid"])
def test_malformed_authorization_cannot_fall_back_to_cookie(accounts, header):
    client, _, _ = accounts
    bearer = issue(client)
    client.cookies.set(auth.SESSION_COOKIE_NAME, bearer["Authorization"].split()[1])
    assert client.get("/api/v1/no-such-route", headers={"Authorization": header}).status_code == 401
    assert client.get("/rest/v1/orchestrate/workflows", headers={"Authorization": header}).status_code == 401


def test_no_query_or_duplicate_header_fallback(accounts):
    client, _, _ = accounts
    bearer = issue(client)
    token = bearer["Authorization"].split()[1]
    assert client.get("/api/v1/no-such-route?access_token=" + token).status_code == 401
    assert client.get("/api/v1/no-such-route", headers=[("Authorization", bearer["Authorization"]),
                                                       ("Authorization", bearer["Authorization"])]).status_code == 401


def test_wrong_credentials_and_precise_anonymous_exception(accounts):
    client, _, _ = accounts
    assert client.post("/api/v1/auth/token", json={**CREDENTIALS, "password": "wrong"}).status_code == 401
    assert client.get("/api/v1/auth/token").status_code == 401
    assert client.post("/api/v1/auth/unknown", json=CREDENTIALS).status_code == 401
    assert client.post("/api/v1/auth/token", json={"username": "admin"}).status_code == 422


def test_login_channels_share_bruteforce_limit(accounts):
    client, _, _ = accounts
    for path in ("/api/v1/auth/token", "/rest/v1/orchestrate/auth/login",
                 "/api/v1/auth/token", "/rest/v1/orchestrate/auth/login", "/api/v1/auth/token"):
        assert client.post(path, json={**CREDENTIALS, "password": "wrong"}).status_code == 401
    assert client.post("/rest/v1/orchestrate/auth/login", json=CREDENTIALS).status_code == 429
    assert client.post("/api/v1/auth/token", json=CREDENTIALS).status_code == 429


def test_disabled_account_and_store_failure_are_not_anonymous_access(accounts):
    client, conf, context = accounts
    conf["access_password"] = ""
    assert client.post("/api/v1/auth/token", json=CREDENTIALS).status_code == 503
    assert client.get("/api/v1/no-such-route").status_code == 503
    context.has_users = True
    context.users = SimpleNamespace(has_any=Mock(side_effect=StorageUnavailableError("secret backend address")))
    for method, path in ((client.get, "/api/v1/no-such-route"), (client.post, "/api/v1/auth/token")):
        response = method(path, **({"json": CREDENTIALS} if method == client.post else {}))
        assert response.status_code == 503 and "secret backend" not in response.text


def test_database_accounts_use_same_verifier_and_forced_change_policy(accounts):
    client, _, context = accounts
    context.has_users = True
    user = {"username": "operator", "role": "user", "must_change_password": True}
    context.users = SimpleNamespace(has_any=lambda: True, authenticate=Mock(return_value=user))
    assert client.post("/api/v1/auth/token", json=CREDENTIALS).status_code == 403
    login = client.post("/rest/v1/orchestrate/auth/login", json=CREDENTIALS)
    assert login.status_code == 200 and login.json()["data"]["must_change_password"]
    bearer = {"Authorization": "Bearer " + client.cookies.get(auth.SESSION_COOKIE_NAME)}
    assert client.get("/api/v1/no-such-route", headers=bearer).status_code == 403
    assert client.post("/api/v1/auth/logout", headers=bearer).status_code == 200
    user["role"] = "unexpected-role"
    assert client.post("/api/v1/auth/token", json=CREDENTIALS).status_code == 403


@pytest.mark.parametrize("path", ["/api/v1/auth/token", "/rest/v1/orchestrate/auth/login"])
def test_store_failure_after_readiness_cannot_issue_token(accounts, path):
    client, _, context = accounts
    context.has_users = True
    context.users = SimpleNamespace(has_any=lambda: True,
        authenticate=Mock(side_effect=StorageUnavailableError("synthetic-private-dsn")))
    response = client.post(path, json=CREDENTIALS)
    assert response.status_code == 503 and "synthetic-private-dsn" not in response.text
    assert "set-cookie" not in response.headers and not auth.get_session_store()._tokens


def test_password_change_and_user_deletion_revoke_all_user_tokens(accounts, monkeypatch):
    client, _, context = accounts
    context.has_users = True
    context.users = SimpleNamespace(has_any=lambda: True,
        authenticate=lambda u, p: {"username": u, "role": "admin"}, update_password=lambda u, p: True)
    first, second = issue(client), issue(client)
    response = client.post("/rest/v1/orchestrate/auth/change-password", headers=first,
                           json={"old_password": CREDENTIALS["password"], "new_password": "ChangedUser9!"})
    assert response.status_code == 200, response.text
    assert client.get("/api/v1/no-such-route", headers=second).status_code == 401
    monkeypatch.setattr("database.utils.user_store.delete_user", lambda username: True)
    operator, _ = auth.get_session_store().create("operator", "user")
    admin = issue(client)
    assert client.delete("/rest/v1/orchestrate/auth/users/operator", headers=admin).status_code == 200
    assert auth.get_session_store().identity(operator) is None


@pytest.mark.parametrize("https,verify", [(False, False), (True, False), (True, True)])
def test_default_is_account_auth_independent_of_tls(https, verify):
    assert external_auth_mode({"enable_https": str(https), "verify_client": str(verify)}) == "user"


@pytest.mark.parametrize("path", ["/api/v1/auth/token", "/rest/v1/orchestrate/auth/login"])
def test_account_change_during_verification_cannot_mint_stale_session(accounts, path):
    client, _, context = accounts
    context.has_users = True
    def verify(username, password):
        # Deterministic concurrent-delete/password-change interleaving: verification
        # read the old credential, then the account changed before issuance.
        auth.get_session_store().revoke_user(username)
        return {"username": username, "role": "admin", "must_change_password": False}
    context.users = SimpleNamespace(has_any=lambda: True, authenticate=verify)
    response = client.post(path, json=CREDENTIALS)
    assert response.status_code == 401 and "set-cookie" not in response.headers
    assert not auth.get_session_store()._tokens


def test_unrelated_account_change_does_not_block_token_issuance(accounts):
    _, _, _ = accounts
    store = auth.get_session_store()
    revision = store.login_revision()
    store.revoke_user("another-user")
    token, _ = store.create("admin", "admin", login_revision=revision)
    assert store.identity(token).username == "admin"


def test_gateway_marker_cannot_bypass_explicit_legacy_provider(accounts, monkeypatch):
    client, conf, _ = accounts
    conf["external.auth.mode"] = "bearer"
    machine_token = "synthetic-static-machine-token-000000000"
    monkeypatch.setenv("ORCH_API_TOKEN", machine_token)
    user = issue(client)
    assert client.get("/api/v1/no-such-route", headers=user).status_code == 401
    assert client.get("/api/v1/no-such-route", headers={**user, BROWSER_GATEWAY_HEADER: "1"}).status_code == 401
    machine = {"Authorization": "Bearer " + machine_token}
    assert client.get("/api/v1/no-such-route", headers=machine).status_code == 404
    assert client.get("/api/v1/no-such-route", headers={**machine, BROWSER_GATEWAY_HEADER: "1"}).status_code == 401


@pytest.mark.parametrize("ttl", ["0", "-1", "invalid"])
def test_invalid_lifetime_never_issues_expired_token(accounts, ttl):
    _, conf, _ = accounts
    conf["access_token_ttl"] = ttl
    token, lifetime = auth.get_session_store().create("admin", "admin")
    assert lifetime == 43200 and auth.get_session_store().identity(token)
