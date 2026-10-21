# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Save-time authorization gate for role-bound workflows.

Workflows without role tasks pass unchanged. A workflow with role tasks may
only be persisted when its exact catalog release is configured and every
(role, version, skill) reference is approved there: drafts never authorize,
and a missing catalog must never fail open.
"""

from typing import Callable

from orchestrate.core.model.psop import PSOP
from orchestrate.core.model.role_catalog import load_role_catalog
from orchestrate.persistence.errors import RoleReferenceError


def configured_catalog_path() -> str | None:
    """server.conf key ``role_catalog_path``; unset means no catalog release."""
    from common.util.config_util import get_conf

    value = get_conf().get("role_catalog_path")
    if value is None:
        return None
    return str(value).strip() or None


def has_role_tasks(psop: PSOP) -> bool:
    return any(task.binding == "role" for step in psop.steps for task in step.subtasks)


def ensure_role_references_authorized(psop: PSOP, catalog_path: str | None) -> None:
    """Reject persistence of role workflows that no approved release authorizes."""
    if not has_role_tasks(psop):
        return
    if not catalog_path:
        raise RoleReferenceError(
            "CATALOG_VERSION_UNAVAILABLE: no role catalog configured "
            "(server.conf key role_catalog_path)"
        )
    try:
        catalog = load_role_catalog(catalog_path, psop.catalog_version)
    except (OSError, ValueError) as error:
        # Missing/unreadable file, corrupt JSON and invalid catalog structure
        # are all "the requested release is unavailable"; the original error
        # stays as the internal cause instead of leaking local paths or full
        # validation payloads to callers.
        raise RoleReferenceError(
            "CATALOG_VERSION_UNAVAILABLE: requested catalog cannot be loaded"
        ) from error
    try:
        catalog.validate_workflow(psop)
    except ValueError as error:
        raise RoleReferenceError(str(error)) from error


class CatalogGate:
    """Handler wrapper: authorize before delegating to the storage handler.

    ``path_resolver`` defaults to a call-time lookup of
    ``configured_catalog_path`` so configuration changes and test overrides
    take effect without rebuilding the (cached) gate.
    """

    def __init__(self, storage, path_resolver: Callable[[], str | None] | None = None):
        self._storage = storage
        self._path_resolver = path_resolver

    def handle(self, psop: PSOP):
        # Only real PSOP instances can carry role references; storage-layer
        # probes and internal plumbing pass other payloads straight through.
        if isinstance(psop, PSOP):
            resolver = self._path_resolver or configured_catalog_path
            ensure_role_references_authorized(psop, resolver())
        return self._storage.handle(psop)
