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

import threading
from unittest.mock import patch

import pytest

from orchestrate.server.frontend_support_server import _update_access_password_in_conf


CONF_TEMPLATE = """ip=127.0.0.1
port=5001
enable_https=false
access_password={password}
persistence_mode=file
"""


@pytest.fixture
def conf_file(tmp_path):
    path = tmp_path / "server.conf"
    path.write_text(CONF_TEMPLATE.format(password="old-hash"), encoding="utf-8")
    return path


class TestUpdateAccessPasswordInConf:
    """Regression coverage for #13: atomic, serialized server.conf rewrite."""

    def test_updates_access_password_line(self, conf_file):
        assert _update_access_password_in_conf(str(conf_file), "new-hash") is True
        content = conf_file.read_text(encoding="utf-8")
        assert "access_password=new-hash\n" in content
        # Every other line and the line count are preserved.
        assert "ip=127.0.0.1\n" in content
        assert "persistence_mode=file\n" in content
        assert content.count("\n") == CONF_TEMPLATE.count("\n")

    def test_returns_false_when_key_missing(self, tmp_path):
        path = tmp_path / "server.conf"
        path.write_text("ip=127.0.0.1\nport=5001\n", encoding="utf-8")
        assert _update_access_password_in_conf(str(path), "new-hash") is False
        # Untouched: no key to rewrite, so nothing should have been written.
        assert path.read_text(encoding="utf-8") == "ip=127.0.0.1\nport=5001\n"

    def test_no_temp_file_left_behind_on_success(self, conf_file):
        _update_access_password_in_conf(str(conf_file), "new-hash")
        leftovers = [p for p in conf_file.parent.iterdir() if p.name != "server.conf"]
        assert leftovers == []

    def test_original_file_untouched_and_temp_cleaned_up_on_write_failure(self, conf_file):
        original = conf_file.read_text(encoding="utf-8")
        with patch("os.replace", side_effect=OSError("disk full")):
            with pytest.raises(OSError):
                _update_access_password_in_conf(str(conf_file), "new-hash")
        # os.replace never ran: the original file is exactly as it was before.
        assert conf_file.read_text(encoding="utf-8") == original
        leftovers = [p for p in conf_file.parent.iterdir() if p.name != "server.conf"]
        assert leftovers == []

    def test_concurrent_writers_are_serialized_not_interleaved(self, conf_file):
        """Two racing writers must never interleave into a corrupted file --
        the lock should serialize them, leaving exactly one well-formed
        access_password= line with one of the two candidate values."""
        results = []

        def _write(password):
            results.append(_update_access_password_in_conf(str(conf_file), password))

        t1 = threading.Thread(target=_write, args=("password-a",))
        t2 = threading.Thread(target=_write, args=("password-b",))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert results == [True, True]
        content = conf_file.read_text(encoding="utf-8")
        access_password_lines = [l for l in content.splitlines() if l.startswith("access_password=")]
        assert len(access_password_lines) == 1
        assert access_password_lines[0] in ("access_password=password-a", "access_password=password-b")
        assert content.count("\n") == CONF_TEMPLATE.count("\n")
