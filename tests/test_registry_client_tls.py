# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: Apache-2.0
"""Real registry-client mTLS sockets, including released SDK TLS behavior."""
import json
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from common.cert.certificate_generator import CertificateGenerator
from orchestrate.registry_client.client import AgentRegistryClient
import orchestrate.registry_client.client as registry_client


@pytest.fixture
def mutual_tls_endpoint(tmp_path, monkeypatch):
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
    context.verify_mode = ssl.CERT_REQUIRED

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"agentCards": [{"name": "synthetic"}]}).encode()
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
