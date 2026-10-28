# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Internal role-execution endpoints: preview before execution, then
confirmed execution with a preview digest.

Contract (REQ74 v1.0.0, fixed at P0):
- ``POST /rest/v1/orchestrate/role-execution/preview``: read-only. Loads the
  saved template, the approved catalog, the instance registry and current
  cards; never creates a transport, signs in, calls an LLM, executes tasks
  or writes execution records.
- ``POST /rest/v1/orchestrate/role-execution/execute``: SSE like the legacy
  GET entries. Requires a preview confirmation digest for the interactive
  role flow; legacy entries stay compatible without one.

Both entries share one request model for scope, authorization subset,
overrides and tie-break. The claimed ``caller_id`` of any request is never
trusted; middleware-authenticated identity is bound instead.
"""

from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from common.util.config_util import get_conf
from orchestrate.core.catalog_gate import has_role_tasks
from orchestrate.core.shared_handlers import SharedHandlers
from orchestrate.persistence.errors import StorageError
from orchestrate.runtime.instance_projection import ResolutionRequest, bind_resolution_identity
from orchestrate.runtime.role_preview import build_role_preview
from orchestrate.server.middleware import RateLimiter
from orchestrate.server.response_utils import get_agent_cards, ok
from orchestrate.server.storage_error_response import storage_http_exception

config = get_conf()

router = APIRouter(prefix="/rest/v1/orchestrate")


class RoleResolutionInputs(BaseModel):
    """Shared scope/authorization/override inputs for preview and execution."""

    scope: Optional[str] = Field(None, max_length=512,
                                 description="Execution scope tenant/site/business_object")
    authorized_instance_ids: Optional[list[str]] = Field(
        None, max_length=64,
        description="Instance subset; may only narrow the server-authorized set")
    task_overrides: dict[str, str] = Field(
        default_factory=dict, max_length=256,
        description="task_id -> instance_id manual selections")
    group_overrides: dict[str, str] = Field(
        default_factory=dict, max_length=256,
        description="binding_group -> instance_id manual selections for whole groups")
    tie_break: Optional[Literal["error", "instance_id"]] = Field(
        None, description="Equal-priority policy; default is server policy (error)")


class RolePreviewBody(RoleResolutionInputs):
    psop_id: str = Field(min_length=1, max_length=256,
                         description="Saved role workflow template to preview")


@router.post("/role-execution/preview")
async def preview_role_execution(
    request: Request,
    body: RolePreviewBody,
    _: Any = Depends(RateLimiter(config, "role_execution_preview")),
):
    """Preview the role execution arrangement for one saved workflow.

    Returns the per-task/binding-group selection units with candidates and
    reasons, blocking issues, and -- when every unit resolves -- a
    confirmation digest for the execute call. Read-only: no transport,
    login, LLM call, task execution or execution record.
    """
    try:
        psop = SharedHandlers.retrieval().get_psop_by_id(body.psop_id)
        if psop is None:
            raise HTTPException(status_code=404, detail=f"Workflow {body.psop_id} not found")
        if not has_role_tasks(psop):
            raise HTTPException(status_code=422, detail="Workflow has no role tasks to preview")

        resolution = ResolutionRequest(
            scope=body.scope,
            authorized_instance_ids=body.authorized_instance_ids,
            task_overrides=dict(body.task_overrides),
            group_overrides=dict(body.group_overrides),
            tie_break=body.tie_break,
        )
        bind_resolution_identity(resolution, request)
        try:
            cards = await get_agent_cards()
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            # An empty registry is a previewable state: every instance is
            # simply not visible, which the unit diagnostics express.
            cards = []
        preview = build_role_preview(psop, resolution, cards)
        return ok(data=preview.model_dump(mode="json"))
    except HTTPException:
        raise
    except StorageError as e:
        raise storage_http_exception(e) from e
    except Exception as e:
        from loguru import logger

        logger.error(f"Role execution preview failed: {e}")
        raise HTTPException(status_code=500, detail="Role execution preview failed") from e
