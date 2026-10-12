# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: Apache-2.0
"""Full start.main in a fresh child process; real HTTP/HTTPS file-mode APIs."""
import hashlib
import os
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import sys
import time

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("protocol,client_verify", [("http", True), ("https", True), ("https", False)])
@pytest.mark.parametrize("public_scheme", ["", "http", "https"])
def test_fresh_service_login_cookie_and_workflow_crud(protocol, client_verify, public_scheme, tmp_path, sample_psop_dict):
    workspace = tmp_path / "service"
    for package in ("orchestrate", "host_agent", "database", "common"):
        for path in (ROOT / package).rglob("*.py"):
            target = workspace / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
    template_source = ROOT / "samples/workflow_templates"
    if not template_source.exists():  # Also exercise pre-fix source snapshots.
        template_source = ROOT / "data/workflow_templates"
    shutil.copytree(template_source, workspace / "samples/workflow_templates")
    conf_dir = workspace / "etc/conf"
    conf_dir.mkdir(parents=True)
    shutil.copyfile(ROOT / "etc/conf/server.conf.example", conf_dir / "server.conf")
    for name in ("server.properties", "log_config.conf"):
        shutil.copyfile(ROOT / "etc/conf" / name, conf_dir / name)
    if protocol == "https":
        from common.cert.certificate_generator import CertificateGenerator
        import generate_selfsign_cert as cli
        ssl_dir = workspace / "etc/ssl"
        ssl_dir.mkdir(parents=True)
        assert CertificateGenerator().generate_self_signed_cert(str(ssl_dir), "serverAuth", "Process#2026")
        cli._write_deploy_files(str(ssl_dir), "Process#2026", plain_key=False)
        verify = ssl.create_default_context(cafile=str(ssl_dir / "trust.cer"))
    else:
        verify = True
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("ORCH_", "OC_", "DB_", "MYSQL_", "PERSISTENCE_", "REGISTRY_", "LLM_"))}
    env.pop("TESTING", None)
    env.pop("PORT", None)
    # Preserve the SDK selected by the parent test (including a released wheel),
    # not a different editable SDK discovered by the child's site initialization.
    import workflow_engine
    sdk_root = str(Path(workflow_engine.__file__).resolve().parents[1])
    env.update(PYTHONPATH=os.pathsep.join((str(workspace), sdk_root)), PYTHON_DOTENV_DISABLED="1",
               ORCH_IP="127.0.0.1", ORCH_PORT=str(port), PERSISTENCE_MODE="file",
               ORCH_ENABLE_HTTPS=str(protocol == "https").lower(), ORCH_VERIFY_CLIENT="false",
               ORCH_PUBLIC_SCHEME=public_scheme,
               TESTING="true", ORCH_DEV_INSECURE_MODE="true",
               ORCH_ACCESS_PASSWORD=hashlib.sha256(b"ProcessUser9!").hexdigest())
    with (tmp_path / "service.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen([sys.executable, "-m", "orchestrate.start"], cwd=workspace,
                                   env=env, stdout=log, stderr=log)
        try:
            with httpx.Client(base_url=f"{protocol}://127.0.0.1:{port}", verify=verify if client_verify else False, trust_env=False) as client:
                deadline = time.monotonic() + 30
                while True:
                    if process.poll() is not None:
                        pytest.fail((tmp_path / "service.log").read_text(encoding="utf-8")[-4000:])
                    try:
                        if client.get("/health").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    if time.monotonic() > deadline:
                        pytest.fail("Isolated service readiness timeout; see service.log")
                    time.sleep(0.1)
                base = "/rest/v1/orchestrate"
                assert client.get(base + "/workflows").status_code == 401
                login = client.post(base + "/auth/login", json={"username": "admin", "password": "ProcessUser9!"})
                assert login.status_code == 200, login.text
                assert ("; secure" in login.headers["set-cookie"].lower()) == ((public_scheme or protocol) == "https")
                if protocol == "http" and public_scheme == "https":
                    # The client here connects directly, not through the public
                    # HTTPS gateway. Real browsers send the cookie to that gateway;
                    # preserve that header while exercising the plain backend.
                    client.headers["Cookie"] = login.headers["set-cookie"].split(";", 1)[0]
                # A fresh runtime data directory contains no bundled resources.
                templates = client.get(base + "/templates")
                assert templates.status_code == 200, templates.text
                assert any(t["id"] == "template_spn_cross_city_diagnosis" for t in templates.json()["data"]), "Bundled template was lost behind runtime data"
                template = next(t for t in templates.json()["data"] if t["id"] == "template_spn_cross_city_diagnosis")
                assert template["step_count"] == 3
                imported = client.post(base + "/templates/" + template["id"] + "/import")
                assert imported.status_code == 201, imported.text
                assert imported.json()["data"]["id"] != template["id"]
                assert len(imported.json()["data"]["steps"]) == 3
                response = client.post(base + "/workflows", json={"psop": sample_psop_dict})
                assert response.status_code == 201, response.text
                workflow_id = response.json()["data"]["workflow_id"]
                target = base + "/workflows/" + workflow_id
                assert client.get(target).status_code == 200
                external = "/api/v1/orchestrate/psop/" + workflow_id
                assert client.get(external).status_code == 401  # Public API requires explicit Bearer.
                issued = client.post("/api/v1/auth/token", json={"username": "admin", "password": "ProcessUser9!"})
                assert issued.status_code == 200, issued.text
                assert "set-cookie" not in issued.headers
                bearer = {"Authorization": "Bearer " + issued.json()["access_token"]}
                assert client.get(external, headers=bearer).status_code == 200
                assert client.post("/api/v1/auth/logout", headers=bearer).status_code == 200
                assert client.get(external, headers=bearer).status_code == 401
                assert client.get(target).status_code == 200  # API logout does not revoke browser session.
                assert client.delete(target).status_code == 200
                assert client.get(target).status_code == 404
                assert client.post(base + "/auth/logout").status_code == 200
                client.headers.pop("Cookie", None)
                assert client.get(base + "/workflows").status_code == 401
        finally:
            process.terminate()
            try:
                process.wait(10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(5)
