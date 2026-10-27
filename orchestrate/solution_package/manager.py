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

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any, Union
from loguru import logger


class SolutionPackageManager:
    """Manage storage and retrieval of solution packages."""

    def __init__(self, storage_dir: Optional[str] = None):
        """
        Initialize SolutionPackageManager.

        Args:
            storage_dir: Storage directory path, defaults to data/solution_packages under the repository root
        """
        # manager.py -> solution_package/ -> orchestrate/ -> repo root; runtime
        # data lives next to data/workflow_storage at the repository root.
        current_file = Path(__file__).resolve()
        project_root = current_file.parents[2]
        self.storage_dir = (
            Path(storage_dir) if storage_dir
            else project_root / "data" / "solution_packages"
        )
        self.seed_dir = project_root / "samples" / "solution_packages"

        self.storage_dir.mkdir(parents=True, exist_ok=True)
        if storage_dir is None:
            # Seeding belongs to the default deployment directory. A caller that
            # passes its own directory (tests, custom deployments) gets exactly
            # the contents it manages itself.
            self._seed_demo_packages()
        logger.info(f"SolutionPackageManager initialized with storage directory: {self.storage_dir}")

    def _seed_demo_packages(self) -> None:
        """Copy the default packages shipped in samples/solution_packages/ into
        the default storage directory.

        Gives a fresh deployment packages to explore without needing the
        original PDFs, and keeps existing deployments current as new default
        packages ship (the prebuilt AN L4 SPG set links to the seeded default
        PSOP workflows). Seeding is per file: a storage file that already
        exists - user-imported or previously seeded - is never overwritten.
        Deleting a seeded package therefore only removes it until the next
        restart. Test runs never seed, so importing the application cannot
        write into the working tree.
        """
        if os.environ.get("TESTING", "").lower() in ("true", "1", "yes"):
            return
        if not self.seed_dir.is_dir():
            return
        seeded = 0
        for seed_file in sorted(self.seed_dir.glob("*.json")):
            target = self.storage_dir / seed_file.name
            if target.exists():
                continue
            shutil.copyfile(seed_file, target)
            seeded += 1
            logger.info(f"Seeded default solution package: {seed_file.name}")
        if seeded:
            logger.info(f"Seeded {seeded} default solution package(s) from {self.seed_dir}")

    def _get_storage_path(self, pdf_filename: str) -> Path:
        """
        Get storage path based on PDF filename.

        Args:
            pdf_filename: PDF filename

        Returns:
            Path: Storage file path
        """
        # Remove file extension, use base filename as storage filename
        filename_without_ext = Path(pdf_filename).stem
        storage_filename = f"{filename_without_ext}.json"
        return self.storage_dir / storage_filename

    def store_solution_package(self, pdf_filename: str, chapters_dict: Dict[str, str]) -> bool:
        """
        Store solution package data.

        Args:
            pdf_filename: PDF filename
            chapters_dict: Chapter dictionary extracted via extract_all_chapters method

        Returns:
            bool: Whether storage succeeded
        """
        try:
            storage_path = self._get_storage_path(pdf_filename)

            # Prepare storage data
            storage_data = {
                "pdf_filename": pdf_filename,
                "chapters": chapters_dict,
                "chapter_count": len(chapters_dict),
                "chapter_titles": list(chapters_dict.keys()),
                "created_at": datetime.now(timezone.utc).isoformat()
            }

            # Re-parsing the same PDF replaces the chapter content, not the
            # workflows already generated from an earlier parse; otherwise a
            # parse that never reaches generation would silently drop links.
            existing = None
            if storage_path.exists():
                try:
                    with open(storage_path, 'r', encoding='utf-8') as f:
                        existing = json.load(f)
                except Exception as e:
                    logger.warning(f"Failed to read existing package for '{pdf_filename}': {e}")
            if isinstance(existing, dict):
                for link_key in ("workflow_id", "workflow_bindings"):
                    if link_key in existing:
                        storage_data[link_key] = existing[link_key]

            # Write JSON file
            with open(storage_path, 'w', encoding='utf-8') as f:
                json.dump(storage_data, f, ensure_ascii=False, indent=2)

            logger.info(f"Successfully stored solution package for '{pdf_filename}' at {storage_path}")
            logger.info(f"Stored {len(chapters_dict)} chapters")
            return True

        except Exception as e:
            logger.error(f"Failed to store solution package for '{pdf_filename}': {e}")
            return False

    def retrieve_by_filename(self, pdf_filename: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve solution package data by PDF filename.

        Args:
            pdf_filename: PDF filename

        Returns:
            Optional[Dict[str, Any]]: Retrieved data including chapter dictionary and other information
        """
        try:
            storage_path = self._get_storage_path(pdf_filename)

            if not storage_path.exists():
                logger.warning(f"No solution package found for '{pdf_filename}' at {storage_path}")
                return None

            # Read JSON file
            with open(storage_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            logger.info(f"Successfully retrieved solution package for '{pdf_filename}'")
            logger.info(f"Retrieved {data.get('chapter_count', 0)} chapters")
            return data

        except Exception as e:
            logger.error(f"Failed to retrieve solution package for '{pdf_filename}': {e}")
            return None

    def retrieve_all(self) -> List[Dict[str, Any]]:
        """
        Retrieve all stored solution package data.

        Returns:
            List[Dict[str, Any]]: List of all stored solution package data
        """
        try:
            all_packages = []

            # Iterate through all JSON files in the storage directory
            for file_path in self.storage_dir.glob("*.json"):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        all_packages.append(data)
                except Exception as e:
                    logger.warning(f"Failed to read file {file_path}: {e}")
                    continue

            logger.info(f"Retrieved {len(all_packages)} solution packages in total")
            return all_packages

        except Exception as e:
            logger.error(f"Failed to retrieve all solution packages: {e}")
            return []

    def link_workflow(self, pdf_filename: str, workflow_id: str, binding: str = "instance") -> bool:
        """
        Record the workflow generated from this solution package.

        Role-catalog and instance workflows occupy separate
        ``workflow_bindings`` slots, so generating one never hides the other.
        ``workflow_id`` keeps the most recently linked id for backward
        compatibility with records and consumers predating the split.

        Args:
            pdf_filename: PDF filename the package was stored under
            workflow_id: Workflow id produced by generate-from-preflow
            binding: Generation binding of the workflow ("role" or "instance")

        Returns:
            bool: Whether the link was recorded
        """
        if binding not in ("role", "instance"):
            logger.error(f"Unknown workflow binding '{binding}' for solution package '{pdf_filename}'")
            return False
        try:
            data = self.retrieve_by_filename(pdf_filename)
            if data is None:
                logger.warning(f"No solution package found for '{pdf_filename}' to link workflow '{workflow_id}'")
                return False
            data["workflow_id"] = workflow_id
            bindings = data.get("workflow_bindings")
            if not isinstance(bindings, dict):
                bindings = {}
            bindings[binding] = workflow_id
            data["workflow_bindings"] = bindings
            storage_path = self._get_storage_path(pdf_filename)
            with open(storage_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(f"Linked {binding} workflow '{workflow_id}' to solution package '{pdf_filename}'")
            return True
        except Exception as e:
            logger.error(f"Failed to link workflow to '{pdf_filename}': {e}")
            return False

    def get_all_filenames(self) -> List[str]:
        """
        Get list of all stored PDF filenames.

        Returns:
            List[str]: PDF filename list
        """
        try:
            filenames = []

            for file_path in self.storage_dir.glob("*.json"):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        if "pdf_filename" in data:
                            filenames.append(data["pdf_filename"])
                except Exception as e:
                    logger.warning(f"Failed to read file {file_path}: {e}")
                    continue

            return filenames

        except Exception as e:
            logger.error(f"Failed to get all filenames: {e}")
            return []

    def delete_by_filename(self, pdf_filename: str) -> bool:
        """
        Delete solution package data for specified PDF filename.

        Args:
            pdf_filename: PDF filename

        Returns:
            bool: Whether deletion succeeded
        """
        try:
            storage_path = self._get_storage_path(pdf_filename)

            if not storage_path.exists():
                logger.warning(f"No solution package found for '{pdf_filename}' to delete")
                return False

            storage_path.unlink()
            logger.info(f"Successfully deleted solution package for '{pdf_filename}'")
            return True

        except Exception as e:
            logger.error(f"Failed to delete solution package for '{pdf_filename}': {e}")
            return False

    def get_chapter_content(self, pdf_filename: str, chapter_title: str) -> Optional[str]:
        """
        Get content of specific chapter in specified PDF file.

        Args:
            pdf_filename: PDF filename
            chapter_title: Chapter title

        Returns:
            Optional[str]: Chapter content, None if not exists
        """
        try:
            data = self.retrieve_by_filename(pdf_filename)
            if not data or "chapters" not in data:
                return None

            chapters = data["chapters"]
            return chapters.get(chapter_title)

        except Exception as e:
            logger.error(f"Failed to get chapter content for '{chapter_title}' in '{pdf_filename}': {e}")
            return None

    def search_chapters_by_keyword(self, keyword: str) -> List[Dict[str, Any]]:
        """
        Search chapters containing keyword across all stored solution packages.

        Args:
            keyword: Search keyword

        Returns:
            List[Dict[str, Any]]: List of matching results, each containing PDF filename and matching chapters
        """
        try:
            all_packages = self.retrieve_all()
            results = []

            for package in all_packages:
                pdf_filename = package.get("pdf_filename", "")
                chapters = package.get("chapters", {})

                matching_chapters = {}
                for chapter_title, chapter_content in chapters.items():
                    if keyword.lower() in chapter_content.lower():
                        matching_chapters[chapter_title] = chapter_content

                if matching_chapters:
                    results.append({
                        "pdf_filename": pdf_filename,
                        "matching_chapters": matching_chapters,
                        "match_count": len(matching_chapters)
                    })

            logger.info(f"Found {len(results)} packages with chapters containing keyword '{keyword}'")
            return results

        except Exception as e:
            logger.error(f"Failed to search chapters by keyword '{keyword}': {e}")
            return []

    def get_storage_stats(self) -> Dict[str, Any]:
        """
        Get storage statistics.

        Returns:
            Dict[str, Any]: Storage statistics
        """
        try:
            all_packages = self.retrieve_all()
            total_packages = len(all_packages)
            total_chapters = sum(package.get("chapter_count", 0) for package in all_packages)

            return {
                "storage_directory": str(self.storage_dir),
                "total_packages": total_packages,
                "total_chapters": total_chapters,
                "package_filenames": [p.get("pdf_filename", "") for p in all_packages]
            }

        except Exception as e:
            logger.error(f"Failed to get storage stats: {e}")
            return {
                "storage_directory": str(self.storage_dir),
                "total_packages": 0,
                "total_chapters": 0,
                "package_filenames": []
            }
