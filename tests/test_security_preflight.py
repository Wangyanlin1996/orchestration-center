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

"""Account startup is fail-closed on HTTP/HTTPS and all bind addresses."""

import os
from unittest.mock import Mock, patch

import pytest

from orchestrate.server.security_preflight import (
    ADMIN_INITIAL_PASSWORD_ENV,
    SecurityPreflightError,
    credential_configured,
    security_preflight,
)


@pytest.fixture(autouse=True)
def _no_ambient_bootstrap_credential(monkeypatch):
    """The check reads the process environment; keep the ambient one out of it."""
    monkeypatch.delenv(ADMIN_INITIAL_PASSWORD_ENV, raising=False)
    # Explicit legacy bearer tests must not depend on a real credential.
    monkeypatch.setenv("ORCH_API_TOKEN", "test-only-machine-token-at-least-32-bytes")


def _conf(**overrides):
    conf = {
        "enable_https": "false",
        "ip": "127.0.0.1",
        "persistence_mode": "file",
        "access_password": "",
    }
    conf.update(overrides)
    return conf


class TestCredentialConfigured:
    def test_empty_access_password_is_not_a_credential(self):
        assert credential_configured(_conf(access_password="")) is False

    def test_access_password_counts(self):
        assert credential_configured(_conf(access_password="deadbeef")) is True

    def test_named_initial_password_file_counts(self, tmp_path):
        path = tmp_path / "admin_pw"
        path.write_text("secret")
        assert credential_configured(_conf(persistence_mode="postgresql", admin_initial_password_file=str(path))) is True

    def test_missing_initial_password_file_does_not_count(self, tmp_path):
        assert credential_configured(_conf(admin_initial_password_file=str(tmp_path / "absent"))) is False

    def test_environment_bootstrap_counts(self, monkeypatch):
        monkeypatch.setenv(ADMIN_INITIAL_PASSWORD_ENV, "secret")
        assert credential_configured(_conf(persistence_mode="postgresql")) is True
        assert credential_configured(_conf()) is False

    def test_database_user_counts(self, monkeypatch):
        conf = _conf(persistence_mode="postgresql")
        with patch("database.utils.user_store.has_any_user", return_value=True) as has_any:
            assert credential_configured(conf) is True
        has_any.assert_called_once()

    def test_unreachable_user_store_does_not_count(self, monkeypatch):
        """Fail closed: "cannot tell" must not read as "a credential exists"."""
        conf = _conf(persistence_mode="postgresql")
        with patch("database.utils.user_store.has_any_user", side_effect=RuntimeError("db down")):
            assert credential_configured(conf) is False


class TestPreflightMatrix:
    """TLS and bind address never substitute for account authentication."""

    def test_explicit_mtls_starts_anywhere(self):
        result = security_preflight(_conf(enable_https="true", ip="0.0.0.0", **{"external.auth.mode": "mtls"}))
        assert result.https_enabled is True
        assert result.warnings == ()

    def test_explicit_mtls_without_user_credential_still_starts(self):
        result = security_preflight(_conf(enable_https="true", ip="0.0.0.0", **{"external.auth.mode": "mtls"}))
        assert result.credential_configured is False

    def test_default_https_requires_account_credential(self):
        with pytest.raises(SecurityPreflightError):
            security_preflight(_conf(enable_https="true", ip="0.0.0.0"))

    def test_plaintext_with_credential_starts_with_a_warning(self):
        result = security_preflight(_conf(access_password="deadbeef", ip="0.0.0.0"))
        assert result.credential_configured is True
        assert len(result.warnings) == 1
        assert "plaintext" in result.warnings[0]

    def test_credentialless_loopback_is_refused(self):
        with pytest.raises(SecurityPreflightError):
            security_preflight(_conf(ip="127.0.0.1"))

    @pytest.mark.parametrize("ip", ["127.0.0.1", "::1", "0.0.0.0"])
    def test_removed_dev_flag_never_permits_credentialless_startup(self, ip):
        with pytest.raises(SecurityPreflightError):
            security_preflight(_conf(ip=ip, **{"security.dev_insecure_mode": "true"}))

    def test_missing_account_names_its_actual_configuration(self):
        with pytest.raises(SecurityPreflightError) as exc:
            security_preflight(_conf(ip="0.0.0.0"))
        message = str(exc.value)
        assert "Refusing to start" in message
        assert "access_password" in message
        assert "ORCH_ACCESS_PASSWORD" in message
        assert "dev_insecure_mode" not in message
        assert "OC_ADMIN_INITIAL_PASSWORD" not in message

    @pytest.mark.parametrize("ip", ["0.0.0.0", "::", "", "192.168.1.10", "orchestration-center"])
    def test_every_non_loopback_bind_refuses_without_a_credential(self, ip):
        with pytest.raises(SecurityPreflightError):
            security_preflight(_conf(ip=ip))

    @pytest.mark.parametrize("ip", ["0.0.0.0", "::", "", "192.168.1.10", "orchestration-center"])
    def test_a_credential_makes_every_bind_startable(self, ip):
        result = security_preflight(_conf(ip=ip, access_password="deadbeef"))
        assert result.credential_configured is True


class TestPreciseRefusal:
    def test_missing_legacy_bearer_does_not_blame_configured_account(self, monkeypatch):
        monkeypatch.delenv("ORCH_API_TOKEN", raising=False)
        with pytest.raises(SecurityPreflightError) as exc:
            security_preflight(_conf(access_password="hash", **{"external.auth.mode": "bearer"}))
        assert "external.auth.mode=bearer" in str(exc.value)
        assert "static-token" in str(exc.value)
        assert "access_password" not in str(exc.value)

    def test_database_message_distinguishes_bootstrap_from_file_password(self):
        with patch("database.utils.user_store.has_any_user", return_value=False):
            with pytest.raises(SecurityPreflightError) as exc:
                security_preflight(_conf(persistence_mode="mysql"))
        assert "database connectivity" in str(exc.value)
        assert "OC_ADMIN_INITIAL_PASSWORD" in str(exc.value)


class TestShippedServerConf:
    """Reads the shipped file, not a fixture: the default must stay fail-closed."""

    _PATH = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "etc", "conf", "server.conf.example"
    )

    @staticmethod
    def _parse(path):
        conf = {}
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                conf[key.strip()] = value.strip()
        return conf

    def test_redundant_authentication_settings_are_not_shipped(self):
        conf = self._parse(self._PATH)
        assert "security.dev_insecure_mode" not in conf
        assert "external.auth.mode" not in conf
        assert "external.auth.token_env" not in conf

    def test_shipped_conf_is_refused_on_a_non_loopback_bind(self):
        """The shipped file configures no credential, so exposing it must fail."""
        conf = {**self._parse(self._PATH), "persistence_mode": "file", "ip": "0.0.0.0"}
        with pytest.raises(SecurityPreflightError):
            security_preflight(conf)

    def test_shipped_loopback_requires_an_account(self):
        conf = {**self._parse(self._PATH), "persistence_mode": "file"}
        with pytest.raises(SecurityPreflightError):
            security_preflight(conf)


class TestMainUsesThePreflight:
    def test_main_refuses_to_bind_in_the_unsafe_cell(self, monkeypatch, capsys):
        from orchestrate import start

        conf = _conf(ip="0.0.0.0")
        monkeypatch.setattr(start, "get_conf", lambda: conf)
        run = Mock(side_effect=AssertionError("the server must not bind"))
        monkeypatch.setattr(start.uvicorn, "run", run)

        with pytest.raises(SystemExit) as exc:
            start.main()

        assert "Refusing to start" in str(exc.value)
        run.assert_not_called()

    def test_main_starts_with_an_account_on_loopback(self, monkeypatch):
        from orchestrate import start

        conf = _conf(ip="127.0.0.1", access_password="synthetic-hash")
        monkeypatch.setattr(start, "get_conf", lambda: conf)
        run = Mock()
        audit = Mock()
        monkeypatch.setattr(start.uvicorn, "run", run)
        monkeypatch.setattr(start.audit_logger, "audit", audit)

        start.main()

        run.assert_called_once()
        audit.assert_not_called()


class TestHealthEndpoint:
    def test_health_is_public_and_does_not_expose_configuration(self, monkeypatch):
        from fastapi.testclient import TestClient

        from orchestrate.server import frontend_support_server as server

        monkeypatch.setattr(
            server, "get_conf", lambda: {"security.dev_insecure_mode": "true"}
        )
        client = TestClient(server.app)
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_health_has_only_minimal_liveness(self, monkeypatch):
        from fastapi.testclient import TestClient

        from orchestrate.server import frontend_support_server as server

        monkeypatch.setattr(server, "get_conf", lambda: {})
        client = TestClient(server.app)
        assert client.get("/health").json() == {"status": "ok"}
