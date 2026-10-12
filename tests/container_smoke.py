# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Linux Docker packaging and real entrypoint HTTP/HTTPS smoke; no live credentials."""
import hashlib
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import tempfile
import time

import httpx

ROOT = Path(__file__).resolve().parents[1]
CANARY = "OC_BUILD_SECRET_CANARY_MUST_NOT_SHIP"


def command(*args, check=True):
    result = subprocess.run(args, text=True, capture_output=True, timeout=900)
    if check and result.returncode:
        raise RuntimeError(result.stdout[-4000:] + result.stderr[-4000:])
    return result


def run():
    if os.name == "nt" or not shutil.which("docker"):
        raise SystemExit("Requires a Linux Docker daemon; run the CI job.")
    image = f"oc-transport-smoke:{os.getpid()}"
    containers = []
    volumes = []
    with tempfile.TemporaryDirectory(prefix="oc-container-contract-") as temp:
        root = Path(temp)
        context = root / "context"
        context.mkdir()
        for name in command("git", "-C", str(ROOT), "ls-files", "-z").stdout.split("\0"):
            if not name or name.startswith(("etc/ssl/", "etc/sign_cert/")) or Path(name).suffix in {".pem", ".key", ".cer"}:
                continue
            if name in {"etc/conf/server.conf", "etc/conf/cipher.key", "common/config/llm_config.json", "etc/config/models.yaml"}:
                continue
            target = context / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
        for name in [".env", "etc/conf/server.conf", "etc/conf/cipher.key", "etc/ssl/server_key.pem",
                     "etc/config/models.yaml", "common/config/llm_config.json", "common/auth.local.json",
                     "orchestrate/data/private.json"]:
            target = context / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(CANARY)
        try:
            command("docker", "build", "-t", image, str(context))
            command("docker", "run", "--rm", "--entrypoint", "python", image, "-c",
                    f"from pathlib import Path; r=Path('/opt/orchestration-center'); "
                    f"leaks=[str(p.relative_to(r)) for p in r.rglob('*') "
                    f"if p.is_file() and b'{CANARY}' in p.read_bytes()]; assert not leaks, leaks")
            bad = command("docker", "run", "--rm", image, check=False)
            assert bad.returncode != 0  # No anonymous production default.
            pki = root / "pki"
            pki.mkdir(mode=0o700)
            command("openssl", "req", "-x509", "-newkey", "rsa:3072", "-sha256", "-days", "1",
                    "-subj", "/CN=localhost", "-passout", "pass:Container#2026",
                    "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1",
                    "-keyout", str(pki / "server_key.pem"), "-out", str(pki / "server.cer"))
            shutil.copyfile(pki / "server.cer", pki / "trust.cer")
            # Keep a host-owned CA for the test client after mounted PKI chown.
            client_ca = root / "client-ca.pem"
            shutil.copyfile(pki / "trust.cer", client_ca)
            (pki / "cert_pwd").write_text("Container#2026")
            for file in pki.iterdir():
                file.chmod(0o600)
            command("docker", "run", "--rm", "--user", "0", "--entrypoint", "chown",
                    "-v", f"{pki}:/fixtures", image, "-R", "10001:10001", "/fixtures")
            for secure in (False, True):
                # A fresh named volume hides /data; bundled immutable templates
                # must remain available outside that mount.
                volume = f"oc-template-smoke-{os.getpid()}-{int(secure)}"
                command("docker", "volume", "create", volume)
                volumes.append(volume)
                args = ["docker", "run", "-d", "-p", "127.0.0.1::5001",
                        "-v", f"{volume}:/opt/orchestration-center/data",
                        "-e", "ORCH_VERIFY_CLIENT=false", "-e", f"ORCH_ENABLE_HTTPS={str(secure).lower()}",
                        "-e", "ORCH_ACCESS_PASSWORD=" + hashlib.sha256(b"ContainerUser9!").hexdigest()]
                if secure:
                    args += ["-v", f"{pki}:/opt/orchestration-center/etc/ssl:ro"]
                container = command(*args, image).stdout.strip()
                containers.append(container)
                mapping = command("docker", "port", container, "5001/tcp").stdout.strip()
                verify = ssl.create_default_context(cafile=str(client_ca)) if secure else True
                with httpx.Client(base_url=("https" if secure else "http") + "://" + mapping,
                                  verify=verify, trust_env=False, timeout=5) as client:
                    deadline = time.monotonic() + 60
                    while True:
                        try:
                            if client.get("/health").status_code == 200:
                                break
                        except httpx.TransportError:
                            pass
                        if time.monotonic() > deadline:
                            raise RuntimeError(command("docker", "logs", container).stdout[-4000:])
                        time.sleep(0.2)
                    command("docker", "exec", container, "python", "-m", "orchestrate.server.healthcheck")
                    login = client.post("/rest/v1/orchestrate/auth/login",
                                        json={"username": "admin", "password": "ContainerUser9!"})
                    assert login.status_code == 200, login.text
                    templates = client.get("/rest/v1/orchestrate/templates")
                    assert templates.status_code == 200, templates.text
                    template = next(t for t in templates.json()["data"] if t["id"] == "template_spn_cross_city_diagnosis")
                    assert template["step_count"] == 3
                    imported = client.post("/rest/v1/orchestrate/templates/" + template["id"] + "/import")
                    assert imported.status_code == 201, imported.text
                    assert len(imported.json()["data"]["steps"]) == 3
                    assert client.get("/rest/v1/orchestrate/workflows").status_code == 200
                    assert client.get("/api/v1/does-not-exist").status_code == 401
                    issued = client.post("/api/v1/auth/token", json={"username": "admin", "password": "ContainerUser9!"})
                    assert issued.status_code == 200, issued.text
                    assert "set-cookie" not in issued.headers
                    bearer = {"Authorization": "Bearer " + issued.json()["access_token"]}
                    assert client.get("/api/v1/does-not-exist", headers=bearer).status_code == 404
                    assert client.post("/api/v1/auth/logout", headers=bearer).status_code == 200
                    assert client.get("/api/v1/does-not-exist", headers=bearer).status_code == 401
            print("PASS: secret-free image, fail-closed startup, HTTP/HTTPS, account Bearer, readonly PKI, probes")
        finally:
            for container in containers:
                command("docker", "rm", "-f", container, check=False)
            for volume in volumes:
                command("docker", "volume", "rm", volume, check=False)
            if (root / "pki").exists():
                command("docker", "run", "--rm", "--user", "0", "--entrypoint", "chown",
                        "-v", f"{root / 'pki'}:/fixtures", image, "-R",
                        f"{os.getuid()}:{os.getgid()}", "/fixtures", check=False)
            command("docker", "image", "rm", image, check=False)


if __name__ == "__main__":
    run()
