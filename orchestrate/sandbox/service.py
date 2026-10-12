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

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any
from uuid import uuid4

from loguru import logger
from pydantic import ValidationError

from common.util.config_util import get_conf
from orchestrate.core.model.psop import PSOP
from orchestrate.sandbox.i18n import translate
from orchestrate.sandbox.models import SandboxRunReport, StubScenario, StubTemplate
from orchestrate.sandbox.runner import run_sandbox
from orchestrate.sandbox.store import SandboxStore
from orchestrate.validation.sandbox_validator import SandboxCheckStatus


class SandboxService:
    """Start and observe sandbox verification runs."""

    def __init__(
        self,
        control_point_factory,
        store: SandboxStore | None = None,
        *,
        max_concurrent_runs: int = 4,
        run_timeout_seconds: float = 60,
    ) -> None:
        if max_concurrent_runs < 1:
            raise ValueError("max_concurrent_runs must be positive")
        if run_timeout_seconds <= 0:
            raise ValueError("run_timeout_seconds must be positive")
        self.store = store or SandboxStore()
        self.control_point_factory = control_point_factory
        self._semaphore = asyncio.Semaphore(max_concurrent_runs)
        self._run_timeout_seconds = run_timeout_seconds
        self._tasks: dict[str, asyncio.Task] = {}
        self._status: dict[str, str] = {}
        self._events: dict[str, list[dict[str, Any]]] = {}

    async def start(
        self,
        psop: PSOP,
        agent_cards: list[Any],
        scenario: StubScenario = StubScenario.SUCCESS,
        runtime_intent: str = "",
        templates: list[StubTemplate] | None = None,
        lang: str = "zh",
    ) -> str:
        verification_id = str(uuid4())
        self._status[verification_id] = "queued"
        self._events[verification_id] = []

        async def run() -> None:
            try:
                async with self._semaphore:
                    self._status[verification_id] = "running"
                    conf = get_conf()
                    # Defaults must mirror the server's own (enable_https and
                    # client_verify_server default to on), or a deployment that
                    # omits both keys would point the sandbox at http:// while
                    # the orchestration center only answers on https://.
                    scheme = "https" if conf.get("enable_https", "true").lower() == "true" else "http"
                    orch_port = conf.get("port", "5001")
                    control_point = self.control_point_factory(
                        orch_url=f"{scheme}://127.0.0.1:{orch_port}",
                        ssl_verify=str(conf.get("client_verify_server", "true")).lower() == "true",
                        lang=lang,
                    )
                    async with asyncio.timeout(self._run_timeout_seconds):
                        report = await run_sandbox(
                            psop,
                            agent_cards,
                            control_point,
                            verification_id=verification_id,
                            scenario=scenario,
                            templates=templates,
                            runtime_intent=runtime_intent,
                            lang=lang,
                            event_sink=lambda event: self._events[verification_id].append(event),
                        )
                self.store.save_report(report, self._events[verification_id])
                self._status[verification_id] = "completed"
            except asyncio.CancelledError:
                self._status[verification_id] = "cancelled"
                report = self._failure_report(
                    verification_id,
                    psop,
                    scenario,
                    lang,
                    "Sandbox verification was cancelled",
                )
                self.store.save_report(
                    report,
                    self._events[verification_id],
                    status="cancelled",
                )
                raise
            except TimeoutError:
                self._status[verification_id] = "timed_out"
                report = self._failure_report(
                    verification_id,
                    psop,
                    scenario,
                    lang,
                    f"Sandbox verification exceeded {self._run_timeout_seconds:g} seconds",
                )
                self.store.save_report(
                    report,
                    self._events[verification_id],
                    status="timed_out",
                )
            except Exception as exc:
                logger.exception(f"[Sandbox] Verification {verification_id} failed: {exc}")
                self._status[verification_id] = "failed"
                report = self._failure_report(
                    verification_id,
                    psop,
                    scenario,
                    lang,
                    str(exc) or type(exc).__name__,
                )
                self.store.save_report(
                    report,
                    self._events[verification_id],
                    status="failed",
                )
            finally:
                self._events.pop(verification_id, None)

        task = asyncio.create_task(
            run(),
            name=f"sandbox-{verification_id}",
        )
        self._tasks[verification_id] = task
        task.add_done_callback(lambda _task: self._tasks.pop(verification_id, None))
        return verification_id

    async def wait(self, verification_id: str) -> None:
        task = self._tasks.get(verification_id)
        if task is not None:
            await task

    async def cancel_and_delete(self, verification_id: str) -> bool:
        task = self._tasks.get(verification_id)
        existed = task is not None or self.store.load_report(verification_id) is not None
        if not existed:
            return False
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        self.store.delete_report(verification_id)
        self._tasks.pop(verification_id, None)
        self._status.pop(verification_id, None)
        self._events.pop(verification_id, None)
        return True

    async def aclose(self) -> None:
        active = [task for task in self._tasks.values() if not task.done()]
        for task in active:
            task.cancel()
        if active:
            await asyncio.gather(*active, return_exceptions=True)

    @staticmethod
    def _failure_report(
        verification_id: str,
        psop: PSOP,
        scenario: StubScenario,
        lang: str,
        error: str,
    ) -> SandboxRunReport:
        return SandboxRunReport(
            verification_id=verification_id,
            workflow_id=psop.id,
            workflow_name=psop.name,
            scenario=scenario,
            verdict=SandboxCheckStatus.FAIL,
            error=error,
            risks=[translate(lang, "report.risk_service_failed")],
            suggestions=[translate(lang, "report.suggestion_check_log")],
        )

    def status(self, verification_id: str) -> dict[str, Any] | None:
        if verification_id not in self._status:
            stored = self.store.load_report(verification_id)
            if stored is None:
                return None
            return {
                "verification_id": verification_id,
                "status": stored.get("status", "completed"),
                "verdict": stored.get("report", {}).get("verdict"),
            }
        return {
            "verification_id": verification_id,
            "status": self._status[verification_id],
            "verdict": self.store.load_report(verification_id).get("report", {}).get("verdict")
            if self.store.load_report(verification_id) else None,
        }

    def events(self, verification_id: str) -> list[dict[str, Any]]:
        return list(self._events.get(verification_id, []))

    def delete_report(self, verification_id: str) -> bool:
        deleted = self.store.delete_report(verification_id)
        if deleted:
            self._status.pop(verification_id, None)
            self._events.pop(verification_id, None)
        return deleted

    def validate_templates(self, payload: Any) -> list[StubTemplate]:
        if not isinstance(payload, list):
            raise ValueError("templates must be a JSON array")
        if len(payload) > 200:
            raise ValueError("templates must contain at most 200 entries")
        try:
            return [StubTemplate.model_validate(item) for item in payload]
        except ValidationError as exc:
            raise ValueError(f"Invalid stub template: {exc}") from exc
