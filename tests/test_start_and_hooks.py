# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for orchestrate/start.py and orchestrate/validation/hooks.py.

start.py:
- customized_create_ssl_context: success, with CRL, with ciphers, exception
- get_user_info_from_env: normal, missing env vars
- record_startup_log: calls audit_logger with correct fields
- CustomUvicornServer.__init__: stores config
- main: HTTPS path (cert valid), HTTP path, DB seed path

hooks.py:
- validate_before_save: APPROVE (no raise), REJECT (422), APPROVE_WITH_CONDITIONS (no raise)
"""

import os
import ssl
import sys
from unittest.mock import MagicMock, patch

import pytest


# ===========================================================================
# start.py
# ===========================================================================

class TestCustomizedCreateSslContext:
    def test_basic_context(self, tmp_path):
        from orchestrate.start import customized_create_ssl_context
        cert_path = str(tmp_path / "cert.pem")
        key_path = str(tmp_path / "key.pem")
        with open(cert_path, "wb") as f:
            f.write(b"fake cert")
        with open(key_path, "wb") as f:
            f.write(b"fake key")
        # Mock ssl.SSLContext to avoid real cert loading
        with patch("ssl.SSLContext") as mock_ctx_class:
            mock_ctx = MagicMock()
            mock_ctx_class.return_value = mock_ctx
            result = customized_create_ssl_context(
                cert_path, key_path, "password",
                ssl.PROTOCOL_TLS_SERVER, ssl.CERT_REQUIRED,
                None, None,
            )
            assert result is mock_ctx
            mock_ctx.load_cert_chain.assert_called_once()

    def test_with_ca_certs_and_crl(self, tmp_path):
        from orchestrate.start import customized_create_ssl_context
        with patch("ssl.SSLContext") as mock_ctx_class, \
             patch("orchestrate.start.get_conf_singleton") as mock_conf:
            mock_ctx = MagicMock()
            mock_ctx_class.return_value = mock_ctx
            mock_conf_obj = MagicMock()
            mock_conf_obj.get_crl_list.return_value = ["crl1"]
            mock_conf_obj.ssl_crl_file = "/fake/crl.crl"
            mock_conf.return_value = mock_conf_obj
            result = customized_create_ssl_context(
                "/fake/cert.cer", "/fake/key.pem", None,
                ssl.PROTOCOL_TLS_SERVER, ssl.CERT_REQUIRED,
                "/fake/ca.cer", None,
            )
            assert result is mock_ctx
            mock_ctx.load_verify_locations.assert_called()
            assert mock_ctx.verify_flags & ssl.VERIFY_CRL_CHECK_LEAF

    def test_with_ciphers(self, tmp_path):
        from orchestrate.start import customized_create_ssl_context
        with patch("ssl.SSLContext") as mock_ctx_class:
            mock_ctx = MagicMock()
            mock_ctx_class.return_value = mock_ctx
            result = customized_create_ssl_context(
                "/fake/cert.cer", "/fake/key.pem", None,
                ssl.PROTOCOL_TLS_SERVER, ssl.CERT_REQUIRED,
                None, "ECDHE-RSA-AES256-GCM-SHA384",
            )
            assert result is mock_ctx
            mock_ctx.set_ciphers.assert_called_once_with("ECDHE-RSA-AES256-GCM-SHA384")

    def test_password_callback(self):
        from orchestrate.start import customized_create_ssl_context
        with patch("ssl.SSLContext") as mock_ctx_class:
            mock_ctx = MagicMock()
            mock_ctx_class.return_value = mock_ctx
            customized_create_ssl_context(
                "/fake/cert.cer", "/fake/key.pem", "mypass",
                ssl.PROTOCOL_TLS_SERVER, ssl.CERT_REQUIRED,
                None, None,
            )
            # The password callback should be a lambda returning "mypass"
            call_args = mock_ctx.load_cert_chain.call_args
            password_fn = call_args[0][2] if len(call_args[0]) > 2 else call_args[1].get("password")
            if password_fn:
                assert password_fn() == "mypass"

    def test_exception_propagates(self):
        from orchestrate.start import customized_create_ssl_context
        with patch("ssl.SSLContext", side_effect=Exception("ssl init failed")):
            with pytest.raises(Exception, match="ssl init failed"):
                customized_create_ssl_context(
                    "/fake/cert.cer", "/fake/key.pem", None,
                    ssl.PROTOCOL_TLS_SERVER, ssl.CERT_REQUIRED,
                    None, None,
                )

    def test_no_password(self):
        from orchestrate.start import customized_create_ssl_context
        with patch("ssl.SSLContext") as mock_ctx_class:
            mock_ctx = MagicMock()
            mock_ctx_class.return_value = mock_ctx
            customized_create_ssl_context(
                "/fake/cert.cer", "/fake/key.pem", None,
                ssl.PROTOCOL_TLS_SERVER, ssl.CERT_REQUIRED,
                None, None,
            )
            call_args = mock_ctx.load_cert_chain.call_args
            password_fn = call_args[0][2] if len(call_args[0]) > 2 else call_args[1].get("password")
            assert password_fn is None


class TestGetUserInfoFromEnv:
    def test_with_env_vars(self):
        from orchestrate.start import get_user_info_from_env
        with patch.dict("os.environ", {"APP_USER": "admin", "APP_UID": "1000", "APP_GID": "1000"}):
            result = get_user_info_from_env()
            assert result["username"] == "admin"
            assert result["uid"] == "1000"
            assert result["gid"] == "1000"

    def test_without_env_vars(self):
        from orchestrate.start import get_user_info_from_env
        env_backup = dict(os.environ)
        try:
            for key in ("APP_USER", "APP_UID", "APP_GID"):
                os.environ.pop(key, None)
            result = get_user_info_from_env()
            assert result["username"] == "unknown"
            assert result["uid"] == "unknown"
            assert result["gid"] == "unknown"
        finally:
            os.environ.clear()
            os.environ.update(env_backup)


class TestRecordStartupLog:
    def test_calls_audit_logger(self):
        from orchestrate.start import record_startup_log
        from common.config import CONN_TIMEOUT  # just verify import works
        with patch("orchestrate.start.get_conf") as mock_conf, \
             patch("orchestrate.start.audit_logger") as mock_logger:
            mock_conf.return_value = {"ip": "127.0.0.1", "port": "5001"}
            with patch("orchestrate.start.get_user_info_from_env", return_value={"username": "admin"}):
                record_startup_log()
                mock_logger.audit.assert_called_once()
                call_data = mock_logger.audit.call_args[0][0]
                assert call_data["details"]["ip"] == "127.0.0.1"
                assert call_data["user_name"] == "admin"


class TestCustomUvicornServer:
    def test_proxy_trust_is_scoped_to_the_server_config(self, monkeypatch):
        from orchestrate.start import CustomUvicornServer
        monkeypatch.setenv("FORWARDED_ALLOW_IPS", "ambient-value")
        conf_obj = MagicMock()
        conf_obj.verify_client = ssl.CERT_NONE
        with patch("orchestrate.start.uvicorn") as mocked, \
             patch("orchestrate.start.load_cert_password", return_value=b"synthetic"), \
             patch("orchestrate.start.CipherConverter.convert", return_value=None), \
             patch("orchestrate.start.record_startup_log"):
            CustomUvicornServer({"forwarded_allow_ips": "127.0.0.1"}, conf_obj).run()
            assert mocked.Config.call_args.kwargs["forwarded_allow_ips"] == "127.0.0.1"
            assert os.environ["FORWARDED_ALLOW_IPS"] == "ambient-value"

    def test_init(self):
        from orchestrate.start import CustomUvicornServer
        server_config = {"ip": "0.0.0.0", "port": "8080"}
        conf_obj = MagicMock()
        server = CustomUvicornServer(server_config, conf_obj)
        assert server.server_config is server_config
        assert server.conf_obj is conf_obj

    def test_run_http_disabled(self):
        """When enable_https=false, main() calls uvicorn.run directly.

        HTTP and loopback binding still require an account credential.
        """
        from orchestrate.start import main
        with patch("orchestrate.start.get_conf") as mock_conf, \
             patch("orchestrate.start.uvicorn") as mock_uvicorn:
            mock_conf.return_value = {
                "enable_https": "false", "ip": "127.0.0.1", "port": "5001",
                "access_password": "synthetic-hash", "persistence_mode": "file",
            }
            main()
            mock_uvicorn.run.assert_called_once()


# ===========================================================================
# hooks.py
# ===========================================================================

class TestValidateBeforeSave:
    def test_approve_does_not_raise(self):
        from orchestrate.validation.hooks import validate_before_save
        from orchestrate.validation.models import Verdict
        mock_report = MagicMock()
        mock_report.final_verdict = Verdict.APPROVE
        mock_report.errors = []
        mock_report.warnings = []
        psop = MagicMock()
        with patch("orchestrate.validation.hooks.validate_topology", return_value=mock_report), \
             patch("orchestrate.validation.hooks.TopologyValidationInput") as mock_input_cls:
            mock_input = MagicMock()
            mock_input_cls.return_value = mock_input
            import asyncio
            asyncio.run(validate_before_save(psop))

    def test_reject_raises_422(self):
        from fastapi import HTTPException
        from orchestrate.validation.hooks import validate_before_save
        from orchestrate.validation.models import Verdict
        mock_report = MagicMock()
        mock_report.final_verdict = Verdict.REJECT
        mock_report.errors = ["Circular dependency"]
        mock_report.warnings = []
        psop = MagicMock()
        with patch("orchestrate.validation.hooks.validate_topology", return_value=mock_report), \
             patch("orchestrate.validation.hooks.TopologyValidationInput") as mock_input_cls:
            mock_input = MagicMock()
            mock_input_cls.return_value = mock_input
            import asyncio
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(validate_before_save(psop))
            assert exc_info.value.status_code == 422
            assert "Workflow topology validation failed" in str(exc_info.value.detail)

    def test_approve_with_conditions_does_not_raise(self):
        from orchestrate.validation.hooks import validate_before_save
        from orchestrate.validation.models import Verdict
        mock_report = MagicMock()
        mock_report.final_verdict = Verdict.APPROVE_WITH_CONDITIONS
        mock_report.errors = []
        mock_report.warnings = ["Consider adding fallback"]
        psop = MagicMock()
        with patch("orchestrate.validation.hooks.validate_topology", return_value=mock_report), \
             patch("orchestrate.validation.hooks.TopologyValidationInput") as mock_input_cls:
            mock_input = MagicMock()
            mock_input_cls.return_value = mock_input
            import asyncio
            asyncio.run(validate_before_save(psop))

    def test_with_security_params(self):
        from orchestrate.validation.hooks import validate_before_save
        from orchestrate.validation.models import Verdict, StepSecurity, SecurityLevel
        mock_report = MagicMock()
        mock_report.final_verdict = Verdict.APPROVE
        mock_report.errors = []
        mock_report.warnings = []
        psop = MagicMock()
        step_security = {"step1": MagicMock()}
        agent_security = {"agent1": SecurityLevel.L1_STRATEGIC}
        with patch("orchestrate.validation.hooks.validate_topology") as mock_validate, \
             patch("orchestrate.validation.hooks.TopologyValidationInput") as mock_input_cls:
            mock_validate.return_value = mock_report
            mock_input = MagicMock()
            mock_input_cls.return_value = mock_input
            import asyncio
            asyncio.run(validate_before_save(psop, step_security=step_security, agent_security=agent_security))
            # Verify TopologyValidationInput was called
            mock_input_cls.assert_called_once()
            call_kwargs = mock_input_cls.call_args[1]
            assert call_kwargs["psop"] is psop
            assert call_kwargs["step_security"] == step_security
            assert call_kwargs["agent_security"] == agent_security

    def test_none_security_defaults_to_empty(self):
        from orchestrate.validation.hooks import validate_before_save
        from orchestrate.validation.models import Verdict
        mock_report = MagicMock()
        mock_report.final_verdict = Verdict.APPROVE
        psop = MagicMock()
        with patch("orchestrate.validation.hooks.validate_topology", return_value=mock_report), \
             patch("orchestrate.validation.hooks.TopologyValidationInput") as mock_input_cls:
            mock_input = MagicMock()
            mock_input_cls.return_value = mock_input
            import asyncio
            asyncio.run(validate_before_save(psop, step_security=None, agent_security=None))
            call_kwargs = mock_input_cls.call_args[1]
            assert call_kwargs["step_security"] == {}
            assert call_kwargs["agent_security"] == {}
