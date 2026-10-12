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

"""Fail-closed startup policy for account authentication and explicit legacy modes.

HTTP and HTTPS without client verification use application credentials.
Verified mTLS remains available. Bind addresses never waive authentication.
"""

import os
from dataclasses import dataclass
from typing import Tuple

from loguru import logger
from orchestrate.server.external_auth import external_auth_configured, external_auth_mode

# First-boot credential sources named by section 5.3 of the design document.
ADMIN_INITIAL_PASSWORD_FILE_KEY = "admin_initial_password_file"
ADMIN_INITIAL_PASSWORD_ENV = "OC_ADMIN_INITIAL_PASSWORD"

PLAINTEXT_WARNING = (
    "enable_https=false: the external API (/api/v1/*) and the login request are served "
    "over plaintext. A credential is configured, so access is authenticated, but the "
    "password and the session token are readable on the wire."
)

class SecurityPreflightError(RuntimeError):
    """Raised when the deployment would start with no authentication at all."""


def initial_admin_password(conf: dict) -> str:
    """Resolve a first-boot secret; never fall back to a compiled-in password.

    Process environment wins, including an explicitly empty (invalid) value.
    Existing SQL users must be checked before calling this function so a
    bootstrap secret is not required again on restart and never resets users.
    """
    if ADMIN_INITIAL_PASSWORD_ENV in os.environ:
        password = os.environ[ADMIN_INITIAL_PASSWORD_ENV]
    else:
        from pathlib import Path
        filename = str(conf.get(ADMIN_INITIAL_PASSWORD_FILE_KEY, "")).strip()
        if not filename:
            raise SecurityPreflightError("Empty user store requires OC_ADMIN_INITIAL_PASSWORD or admin_initial_password_file")
        try:
            password = Path(filename).read_text(encoding="utf-8").rstrip("\r\n")
        except (OSError, UnicodeError):
            raise SecurityPreflightError("Cannot read initial admin password file") from None
    from common.util.password_util import validate_password_complexity
    valid, _ = validate_password_complexity(password)
    if not valid or len(password) > 256 or "\n" in password or "\r" in password:
        raise SecurityPreflightError("Invalid initial admin password; use a single password meeting login length and complexity requirements")
    return password


@dataclass(frozen=True)
class PreflightResult:
    """What the check decided, so the caller can log and audit it."""

    https_enabled: bool
    credential_configured: bool
    warnings: Tuple[str, ...] = ()


def credential_configured(conf: dict) -> bool:
    """Whether the deployment has named an application-layer credential source.

    An empty ``access_password`` means "authentication unconfigured", not
    "authentication disabled" (section 5.3), so it does not count here. Neither does
    the compiled-in default admin: the question is what the deployer configured, not
    what the process would create for itself.
    """
    if str(conf.get("access_password", "")).strip():
        return True

    from common.util.persistence_mode import is_db_mode
    if not is_db_mode(conf):
        return False  # File mode never consumes the database bootstrap password.

    initial_password_file = str(conf.get(ADMIN_INITIAL_PASSWORD_FILE_KEY, "")).strip()
    if initial_password_file and os.path.isfile(initial_password_file):
        return True

    if os.environ.get(ADMIN_INITIAL_PASSWORD_ENV, "").strip():
        return True

    return _user_store_populated(conf)


def _user_store_populated(conf: dict) -> bool:
    """True when database mode already holds a user to authenticate with."""
    try:
        from common.util.persistence_mode import is_db_mode

        if not is_db_mode(conf):
            return False

        from database.utils.user_store import has_any_user

        return bool(has_any_user())
    except Exception as e:  # noqa: BLE001 - any failure means "not configured"
        logger.warning(f"[Preflight] Could not read the user store: {e}")
        return False


def security_preflight(conf: dict) -> PreflightResult:
    """Require usable authentication before opening the listener.

    Raises:
        SecurityPreflightError: the server must not bind in this configuration.
    """
    https_enabled = str(conf.get("enable_https", True)).strip().lower() == "true"
    credential = credential_configured(conf)

    scheme = str(conf.get("public_scheme", "")).strip().lower()
    if scheme not in {"", "http", "https"}:
        raise SecurityPreflightError("public_scheme must be http or https")
    try:
        mode = external_auth_mode(conf)
        external_ready = credential if mode == "user" else external_auth_configured(conf)
        mtls = mode == "mtls" and external_ready
    except ValueError as exc:
        raise SecurityPreflightError(str(exc)) from exc

    if external_ready and (credential or mtls):
        warnings = () if https_enabled else (PLAINTEXT_WARNING,)
        return PreflightResult(https_enabled, credential, warnings)
    raise SecurityPreflightError(_refusal_message(conf, mode, external_ready))


def _refusal_message(conf: dict, mode: str, external_ready: bool) -> str:
    if mode != "user" and not external_ready:
        guidance = {
            "bearer": "Configure the selected static-token environment variable (at least 32 UTF-8 bytes).",
            "mtls": "Enable HTTPS and client-certificate verification for the selected mTLS provider.",
            "custom": "Register an AUTHENTICATE_EXTERNAL handler for the selected custom provider.",
        }[mode]
        return (f"Refusing to start: external.auth.mode={mode} is not configured. {guidance} "
                "For account login, remove external.auth.mode or set it to user.")
    from common.util.persistence_mode import is_db_mode
    if is_db_mode(conf):
        guidance = ("Check database connectivity and existing users. For an empty user store, set "
                    f"{ADMIN_INITIAL_PASSWORD_ENV} or admin_initial_password_file for first boot.")
    else:
        guidance = ("Set access_password using 'python generate_access_password.py', "
                    "or supply its password hash through ORCH_ACCESS_PASSWORD.")
    return ("Refusing to start: account authentication is not configured. " + guidance +
            " HTTP, HTTPS and loopback access use the same account login.")
