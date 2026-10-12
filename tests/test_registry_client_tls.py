# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: Apache-2.0
"""Real registry-client mTLS sockets, including released SDK TLS behavior."""
import json
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from common.cert.certificate_generator import CertificateGenerator
from orchestrate.registry_client.client import AgentRegistryClient
import orchestrate.registry_client.client as registry_client


@pytest.fixture
def mutual_tls_endpoint(tmp_path, monkeypatch, request):
    import generate_selfsign_cert as cli

    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    password = "Synthetic-Tls9!"
    assert CertificateGenerator().generate_self_signed_cert(str(tmp_path), "serverAuth", password)
    cli._write_deploy_files(str(tmp_path), password, plain_key=False)
    certificate, key = cli.issue_client_cert(str(tmp_path), "synthetic-registry-client")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(tmp_path / "server.cer", tmp_path / "server_key.pem", password)
    context.load_verify_locations(cafile=tmp_path / "trust.cer")
    require_client = getattr(request, "param", True)
    context.verify_mode = ssl.CERT_REQUIRED if require_client else ssl.CERT_NONE

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"agentCards": [{"name": "synthetic"}]}).encode()
            if require_client:
                assert self.connection.getpeercert()
            assert self.headers["Authorization"] == "Bearer synthetic-token"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        yield f"https://127.0.0.1:{server.server_port}", certificate, key, tmp_path / "trust.cer"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        assert not thread.is_alive()


@pytest.mark.asyncio
@pytest.mark.parametrize("verify_server", [False, True])
async def test_real_registry_mtls_retains_identity_with_released_sdk(mutual_tls_endpoint, monkeypatch, verify_server):
    url, cert, key, ca = mutual_tls_endpoint
    builder = registry_client.create_client_ssl_context

    def released_builder(verify_server=True, **options):
        # Exact released 0.0.9/0.1.0 behavior; local editable SDK fixes must not
        # conceal a deployment regression in wheels installed by Docker.
        return builder(verify_server=True, **options) if verify_server else False

    monkeypatch.setattr(registry_client, "create_client_ssl_context", released_builder)
    options = {"cert_path": cert, "key_path": key}
    if verify_server:
        options["ca_certs_path"] = str(ca)
    client = AgentRegistryClient(url, timeout=3, ssl_verify=verify_server,
                                headers={"Authorization": "Bearer synthetic-token"}, tls_options=options)
    try:
        assert await client.list_all() == [{"name": "synthetic"}]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_disabled_verification_does_not_invent_client_identity(mutual_tls_endpoint):
    client = AgentRegistryClient(mutual_tls_endpoint[0], timeout=3, ssl_verify=False)
    try:
        with pytest.raises((httpx.HTTPError, ssl.SSLError)):
            await client.list_all()
    finally:
        await client.close()


@pytest.mark.parametrize("options,exception", [
    ({"cert_path": "missing-client.cer"}, ValueError),
    ({"key_path": "missing-client.key"}, ValueError),
    ({"cert_path": "missing-client.cer", "key_path": "missing-client.key"}, FileNotFoundError),
    ({"ca_certs_path": "unused-ca.cer"}, ValueError),
    ({"crl_path": "unused-crl.pem"}, ValueError),
])
def test_disabled_verification_still_rejects_invalid_material(options, exception):
    client = AgentRegistryClient("https://registry.invalid", ssl_verify=False, tls_options=options)
    with pytest.raises(exception):
        client._create_tls_context()


@pytest.mark.asyncio
@pytest.mark.skipif(not os.environ.get("OPENAN_INSTALLATION_ROOT") or not (os.environ.get("HELM_BIN") or shutil.which("helm")),
                    reason="Cross-repository integration requires OPENAN_INSTALLATION_ROOT and Helm")
@pytest.mark.parametrize("verify_server", [False, True])
@pytest.mark.parametrize("mutual_tls_endpoint", [False, True], indirect=True)
async def test_rendered_helm_environment_reaches_real_registry(mutual_tls_endpoint, monkeypatch, verify_server, request):
    """Optional cross-repo integration: real Helm -> alias mapping -> factory -> TLS socket."""
    import yaml
    from common.util.config_util import apply_env_overrides
    import orchestrate.registry_client.client_factory as factory_module

    source = os.environ.get("OPENAN_INSTALLATION_ROOT")
    helm = os.environ.get("HELM_BIN") or shutil.which("helm")
    if not source or not helm:
        pytest.skip("Set OPENAN_INSTALLATION_ROOT and HELM_BIN for cross-repository integration")
    url, cert, key, ca = mutual_tls_endpoint
    mtls = request.node.callspec.params["mutual_tls_endpoint"]
    settings = {"postgresql.existingSecret": "synthetic-db", "registry.runtimeSecret": "synthetic-rc",
                "registry.credentialSecret": "synthetic-credentials", "orchestration.runtimeSecret": "synthetic-oc",
                "registry.signing.mode": "off", "registry.tls.enabled": "true",
                "registry.tls.existingSecret": "synthetic-tls", "registry.ingressClientSecret": "synthetic-ingress",
                "registry.tls.verifyClient": str(mtls).lower(), "orchestration.registryClientSecret": "synthetic-client",
                "orchestration.clientVerifyServer": str(verify_server).lower()}
    command = [helm, "template", "cross-contract", str(Path(source) / "containerized/online-install/openan-chart")]
    for name, value in settings.items():
        command += ["--set", name + "=" + value]
    rendered = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert rendered.returncode == 0, rendered.stderr
    env = next(doc["data"] for doc in yaml.safe_load_all(rendered.stdout)
               if doc and doc["kind"] == "ConfigMap" and doc["metadata"]["name"] == "orchestration-center-config")
    assert ("REGISTRY_CA_FILE" in env) is verify_server
    assert ("REGISTRY_CLIENT_CERT" in env) is mtls
    for name in ("REGISTRY_CA_FILE", "REGISTRY_CLIENT_CERT", "REGISTRY_CLIENT_KEY"):
        monkeypatch.delenv(name, raising=False)
    files = {"REGISTRY_CA_FILE": str(ca), "REGISTRY_CLIENT_CERT": cert, "REGISTRY_CLIENT_KEY": key}
    for name, value in env.items():
        monkeypatch.setenv(name, files.get(name, value))
    monkeypatch.setenv("AGENT_REGISTRY_URL", url)
    monkeypatch.setenv("REGISTRY_ACCESS_TOKEN", "synthetic-token")
    conf = {}
    apply_env_overrides(conf)
    monkeypatch.setattr(factory_module, "get_conf", lambda: conf)
    client = factory_module.AgentRegistryClientFactory().create_client(timeout=3)
    try:
        assert await client.list_all() == [{"name": "synthetic"}]
    finally:
        await client.close()
