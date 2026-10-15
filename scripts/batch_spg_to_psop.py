# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
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

"""
Batch SPG (Solution Package PDF) -> PSOP workflow converter.

Reuses the orchestration center's own SPG orchestration capability:

    SolutionPackageParser.parse_pdf_chapter(pdf, chapter)  -> PreFlow steps (markdown, via LLM)
    PsopGenerator.generate_psop_workflow(preflow, cards)   -> PSOP (via LLM)
    HandlerRegistry.get_handler(SAVE_PSOP).handle(psop)    -> persistence (file JSON or PostgreSQL)

All 20 SPG PDFs can be converted in one run. The script is resumable:
successful conversions are recorded in a state file and skipped on re-run
unless --force is given. Every generated PSOP (and its PreFlow markdown) is
also exported as JSON/MD files for offline review.

Usage (run from the repository root):

    # Generate only, skip DB save (no persistence_mode change needed)
    python -m scripts.batch_spg_to_psop --dry-run

    # Generate and save through the configured storage backend
    python -m scripts.batch_spg_to_psop

    # Custom directory / chapter / single file re-run
    python -m scripts.batch_spg_to_psop --pdf-dir D:\\spgs --chapter "5. Interaction Flow"
    python -m scripts.batch_spg_to_psop --pdf IG1501_AN_L4_Fault_Management_Solution_Package.pdf --force

Requirements:
    - LLM connectivity configured in common/config/llm_config.json (chat section)
    - For DB save: persistence_mode=postgresql in etc/conf/server.conf and a
      reachable PostgreSQL configured in etc/conf/db_config.json
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from loguru import logger

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from a2a.types import AgentCard  # noqa: E402

from common.custom import HandlerRegistry, InterfaceType  # noqa: E402  (registers DB handlers)
from orchestrate.agentcard_loader import AgentCardLoader  # noqa: E402
from orchestrate.core.model.preflow import PreFlow  # noqa: E402
from orchestrate.core.model.psop import PSOP  # noqa: E402
from orchestrate.core.psop_generator import PsopGenerator, WorkflowGeneratorError  # noqa: E402
from orchestrate.solution_package.parse_flow import (  # noqa: E402
    PDFParsingError,
    SolutionPackageParser,
)

DEFAULT_PDF_DIR = Path(r"D:\OpenAN\solution_package_pdfs\solution_package_pdfs")
DEFAULT_CHAPTER = "5. Interaction Flow"
DEFAULT_EXPORT_DIR = REPO_ROOT / "data" / "spg_import"
STATE_FILE_NAME = "import_state.json"


class SPGImportResult:
    """Outcome of one SPG PDF conversion attempt series."""

    def __init__(self, pdf_filename: str):
        self.pdf_filename = pdf_filename
        self.status: str = "pending"          # success | failed | skipped
        self.psop_id: Optional[str] = None
        self.psop_name: Optional[str] = None
        self.step_count: int = 0
        self.attempts: int = 0
        self.error: Optional[str] = None
        self.saved_to: Optional[str] = None   # "database" / "dry-run" / storage path

    def to_dict(self) -> Dict:
        return {
            "pdf_filename": self.pdf_filename,
            "status": self.status,
            "psop_id": self.psop_id,
            "psop_name": self.psop_name,
            "step_count": self.step_count,
            "attempts": self.attempts,
            "error": self.error,
            "saved_to": self.saved_to,
        }


def load_state(export_dir: Path) -> Dict:
    state_path = export_dir / STATE_FILE_NAME
    if state_path.exists():
        try:
            return json.loads(state_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"Cannot read state file {state_path}: {e}")
    return {}


def save_state(export_dir: Path, state: Dict) -> None:
    state_path = export_dir / STATE_FILE_NAME
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def precheck_llm() -> bool:
    """Fail fast when the chat LLM is unreachable or misconfigured."""
    from common.llm import get_llm_instance

    try:
        _, answer = get_llm_instance().ask_llm("Reply with exactly: OK")
    except Exception as e:  # defensive: ask_llm normally swallows errors
        logger.error(f"LLM precheck raised: {e}")
        return False
    if not answer:
        logger.error("LLM precheck returned empty answer - check common/config/llm_config.json")
        return False
    logger.info(f"LLM precheck OK (answer={answer.strip()[:20]!r})")
    return True


def convert_one_pdf(
        pdf_path: Path,
        chapter: str,
        agent_cards: List[AgentCard],
        retries: int,
        dry_run: bool,
) -> SPGImportResult:
    """Run the full SPG -> PreFlow -> PSOP -> save pipeline for one PDF."""
    result = SPGImportResult(pdf_path.name)
    stem = pdf_path.stem

    for attempt in range(1, retries + 1):
        result.attempts = attempt
        try:
            # 1. SPG PDF -> PreFlow markdown (orchestration center's SPG parsing)
            parser = SolutionPackageParser()
            pre_md = parser.parse_pdf_chapter(str(pdf_path), chapter)
            if not pre_md or not pre_md.strip():
                raise PDFParsingError(
                    f"chapter '{chapter}' produced empty markdown (LLM call failed?)"
                )
            logger.info(f"[{stem}] attempt {attempt}: chapter markdown {len(pre_md)} chars")

            preflow = PreFlow(
                name=stem,
                description=f"Workflow parsed from SPG {pdf_path.name}",
                steps_md=pre_md,
            )

            # 2. PreFlow -> PSOP (orchestration center's orchestration capability)
            psop: PSOP = PsopGenerator().generate_psop_workflow(preflow, agent_cards)
            psop.user_intent = pre_md[:200]
            psop.description = f"Auto-generated from SPG {pdf_path.name}, chapter '{chapter}'"
            psop.tags = ["spg", "solution-package"]
            psop.related_preflow = preflow.id
            logger.info(f"[{stem}] attempt {attempt}: PSOP generated id={psop.id} steps={len(psop.steps)}")

            # 3. Persist through the orchestration center's storage layer
            if dry_run:
                result.saved_to = "dry-run"
            else:
                save_handler = HandlerRegistry.get_handler(InterfaceType.SAVE_PSOP)
                save_handler.handle(psop)
                from common.util.config_util import get_conf
                result.saved_to = get_conf().get("persistence_mode", "file")
                logger.info(f"[{stem}] PSOP saved via storage backend ({result.saved_to}): {psop.id}")

            # 4. Export artifacts for offline review (always, incl. dry-run)
            export_psop(psop, pre_md, stem)

            result.status = "success"
            result.psop_id = psop.id
            result.psop_name = psop.name
            result.step_count = len(psop.steps)
            result.error = None
            return result
        except Exception as e:
            result.error = f"{type(e).__name__}: {e}"
            logger.error(f"[{stem}] attempt {attempt}/{retries} failed: {result.error}")
            if attempt < retries:
                time.sleep(min(15, 5 * attempt))

    result.status = "failed"
    return result


def export_psop(psop: PSOP, pre_md: str, stem: str) -> None:
    psop_dir = DEFAULT_EXPORT_DIR / "psop"
    preflow_dir = DEFAULT_EXPORT_DIR / "preflow"
    psop_dir.mkdir(parents=True, exist_ok=True)
    preflow_dir.mkdir(parents=True, exist_ok=True)
    (psop_dir / f"{stem}.json").write_text(psop.model_dump_json(indent=2), encoding="utf-8")
    (preflow_dir / f"{stem}.md").write_text(pre_md, encoding="utf-8")


def print_summary(results: List[SPGImportResult], elapsed: float) -> None:
    ok = [r for r in results if r.status == "success"]
    failed = [r for r in results if r.status == "failed"]
    skipped = [r for r in results if r.status == "skipped"]
    logger.info("=" * 78)
    logger.info(f"SPG -> PSOP batch finished in {elapsed / 60:.1f} min: "
                f"{len(ok)} ok, {len(skipped)} skipped, {len(failed)} failed")
    for r in results:
        mark = {"success": "✓", "skipped": "·", "failed": "✗"}.get(r.status, "?")
        line = f" {mark} {r.pdf_filename[:58]:<58} {r.status}"
        if r.psop_id:
            line += f"  id={r.psop_id} steps={r.step_count}"
        if r.error:
            line += f"  err={r.error[:120]}"
        logger.info(line)
    logger.info("=" * 78)


def main() -> int:
    ap = argparse.ArgumentParser(description="Batch convert SPG solution package PDFs to PSOP workflows")
    ap.add_argument("--pdf-dir", default=str(DEFAULT_PDF_DIR), help="Directory containing SPG PDFs")
    ap.add_argument("--pdf", action="append", default=[],
                    help="Only convert the given PDF filename(s); repeatable")
    ap.add_argument("--chapter", default=DEFAULT_CHAPTER, help="TOC chapter to parse as flow source")
    ap.add_argument("--agent-cards-dir", default=str(REPO_ROOT / "samples" / "agentcard"),
                    help="AgentCard YAML/JSON directory used for skill matching")
    ap.add_argument("--retries", type=int, default=3, help="Attempts per PDF")
    ap.add_argument("--limit", type=int, default=0, help="Max PDFs to process this run (0 = all)")
    ap.add_argument("--force", action="store_true", help="Re-convert PDFs already marked success in state")
    ap.add_argument("--dry-run", action="store_true", help="Generate PSOPs but skip the storage save")
    args = ap.parse_args()

    pdf_dir = Path(args.pdf_dir)
    if not pdf_dir.is_dir():
        logger.error(f"PDF directory not found: {pdf_dir}")
        return 2

    pdfs = sorted({p for p in pdf_dir.glob("*.pdf") if not args.pdf or p.name in args.pdf})
    if not pdfs:
        logger.error(f"No PDF found in {pdf_dir} (filter={args.pdf or 'none'})")
        return 2
    if args.limit > 0:
        pdfs = pdfs[:args.limit]
    logger.info(f"Found {len(pdfs)} SPG PDF(s) to convert (chapter={args.chapter!r}, dry_run={args.dry_run})")

    agent_cards = AgentCardLoader(Path(args.agent_cards_dir)).get_all_agent_cards()
    logger.info(f"Loaded {len(agent_cards)} AgentCards for skill matching: "
                f"{[c.name for c in agent_cards]}")
    if not agent_cards:
        logger.error("No AgentCards available - PSOP generation requires agents to match skills")
        return 2

    if not precheck_llm():
        return 2

    state = load_state(DEFAULT_EXPORT_DIR)
    results: List[SPGImportResult] = []
    started = time.time()

    for pdf_path in pdfs:
        previous = state.get(pdf_path.name, {})
        if previous.get("status") == "success" and not args.force:
            r = SPGImportResult(pdf_path.name)
            r.status = "skipped"
            r.psop_id = previous.get("psop_id")
            r.step_count = previous.get("step_count", 0)
            r.saved_to = previous.get("saved_to")
            logger.info(f"[{pdf_path.stem}] already imported (psop_id={r.psop_id}), skipping (--force to redo)")
            results.append(r)
            continue

        result = convert_one_pdf(pdf_path, args.chapter, agent_cards, args.retries, args.dry_run)
        results.append(result)
        state[pdf_path.name] = result.to_dict()
        state["_meta"] = {"last_run": datetime.now(tz=timezone.utc).isoformat(), "chapter": args.chapter}
        save_state(DEFAULT_EXPORT_DIR, state)

    print_summary(results, time.time() - started)
    failed_ids = [r.pdf_filename for r in results if r.status == "failed"]
    return 1 if failed_ids else 0


if __name__ == "__main__":
    sys.exit(main())
