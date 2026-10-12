# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Real TLS backend + browser relay; nginx container acceptance is separate."""
import hashlib
import socket
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest
import uvicorn

from test_storage_http_transport import _tls_files
from orchestrate.server.gateway_policy import BROWSER_GATEWAY_HEADER


@pytest.fixture(params=[False, True], ids=["https-no-mtls", "https-mtls"])
def browser_gateway(request, tmp_path, monkeypatch):
    from orchestrate.server import auth, frontend_support_server as app_server
    from orchestrate.persistence import context, StorageContext
    from orchestrate.persistence.file_backend import FilePersistenceBackend
    from orchestrate.core.persistence import WorkflowStorage
    from orchestrate.core.model.execution_record import ExecutionRecord
    from orchestrate.handlers import file_handlers

    storage = WorkflowStorage(str(tmp_path / "data"))
    storage.save_execution_record(ExecutionRecord(psop_id="synthetic-workflow", psop_name="boundary-canary"))
    monkeypatch.setattr(context, "_persistence_context", StorageContext(FilePersistenceBackend(storage=storage)))
    monkeypatch.setattr(file_handlers, "get_workflow_storage", lambda: storage)
    conf = {"ip": "0.0.0.0", "enable_https": "true", "verify_client": str(request.param).lower(),
            "external.auth.mode": "auto", "persistence_mode": "file", "public_scheme": "http",
            "access_password": hashlib.sha256(b"SyntheticUser9!").hexdigest()}
    monkeypatch.setattr(auth, "get_conf", lambda: conf)
    monkeypatch.setattr(app_server, "get_conf", lambda: conf)
    monkeypatch.setattr(auth, "_session_store", auth._SessionStore())
    monkeypatch.delenv("TESTING", raising=False)
    from orchestrate.server import middleware
    monkeypatch.setattr(middleware, "limiter", middleware.strategies.MovingWindowRateLimiter(middleware.storage.MemoryStorage()))
    token = "synthetic-machine-token-000000000000000"
    monkeypatch.setenv("ORCH_API_TOKEN", token)
    cert, key = _tls_files(tmp_path)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(32)
    runner = uvicorn.Server(uvicorn.Config(
        app_server.app, lifespan="off", log_level="error", ssl_certfile=str(cert), ssl_keyfile=str(key),
        ssl_ca_certs=str(cert), ssl_cert_reqs=ssl.CERT_REQUIRED if request.param else ssl.CERT_NONE))
    thread = threading.Thread(target=runner.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not runner.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert runner.started
    backend = f"https://127.0.0.1:{listener.getsockname()[1]}"
    upstream = ssl.create_default_context(cafile=str(cert))
    upstream.load_cert_chain(str(cert), str(key))

    class Relay(BaseHTTPRequestHandler):
        def forward(self):
            path = "/" + self.path.removeprefix("/api/orchestrate/")
            headers = {name: value for name, value in self.headers.items()
                       if name.lower() not in {"host", BROWSER_GATEWAY_HEADER.lower()}}
            headers[BROWSER_GATEWAY_HEADER] = "1"  # Overwrite, do not trust the browser.
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            with httpx.Client(verify=upstream, trust_env=False) as client:
                response = client.request(self.command, backend + path, headers=headers, content=body)
            self.send_response(response.status_code)
            self.send_header("Content-Length", str(len(response.content)))
            if "set-cookie" in response.headers:
                self.send_header("Set-Cookie", response.headers["set-cookie"])
            self.end_headers()
            self.wfile.write(response.content)

        do_GET = forward
        do_POST = forward

        def log_message(self, *args):
            pass

    relay = ThreadingHTTPServer(("127.0.0.1", 0), Relay)
    relay_thread = threading.Thread(target=relay.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    relay_thread.start()
    try:
        yield f"http://127.0.0.1:{relay.server_port}/api/orchestrate", backend, upstream, conf, token
    finally:
        relay.shutdown()
        relay.server_close()
        relay_thread.join(5)
        runner.should_exit = True
        thread.join(10)
        listener.close()
        assert not thread.is_alive()


def test_removed_switches_do_not_open_a_real_tls_gateway(browser_gateway, monkeypatch):
    gateway, _, _, conf, _ = browser_gateway
    conf.update({"ip": "127.0.0.1", "security.dev_insecure_mode": "true"})
    monkeypatch.setenv("TESTING", "true")
    with httpx.Client(trust_env=False) as browser:
        assert browser.get(gateway + "/api/v1/executions").status_code == 401
        assert browser.get(gateway + "/rest/v1/orchestrate/workflows").status_code == 401
        issued = browser.post(gateway + "/api/v1/auth/token", json={"username": "admin", "password": "SyntheticUser9!"})
        assert issued.status_code == 200, issued.text
        bearer = {"Authorization": "Bearer " + issued.json()["access_token"]}
        assert browser.get(gateway + "/api/v1/executions", headers=bearer).status_code == 200


def test_proxy_certificate_cannot_authenticate_a_browser_for_machine_apis(browser_gateway):
    gateway, backend, upstream, conf, token = browser_gateway
    with httpx.Client(trust_env=False) as browser:
        for headers in ({}, {"Authorization": "Bearer " + token},
                        {"Cookie": "session_token=synthetic-session", BROWSER_GATEWAY_HEADER: ""}):
            response = browser.get(gateway + "/api/v1/executions", headers=headers)
            assert response.status_code == 401
            assert "boundary-canary" not in response.text
        issued = browser.post(gateway + "/api/v1/auth/token", json={"username": "admin", "password": "SyntheticUser9!"})
        assert issued.status_code == 200, issued.text
        bearer = {"Authorization": "Bearer " + issued.json()["access_token"]}
        assert browser.get(gateway + "/api/v1/executions", headers=bearer).status_code == 200
        assert browser.post(gateway + "/api/v1/auth/logout", headers=bearer).status_code == 200
        assert browser.get(gateway + "/api/v1/executions", headers=bearer).status_code == 401
    # TLS peer identity is no longer a default application account credential.
    with httpx.Client(verify=upstream, trust_env=False) as machine:
        response = machine.get(backend + "/api/v1/executions", headers={"Authorization": "Bearer " + token})
        assert response.status_code == 401
        if conf["verify_client"] == "true":
            assert machine.get(backend + "/api/v1/executions").status_code == 401
            conf["external.auth.mode"] = "mtls"
            assert machine.get(backend + "/api/v1/executions").status_code == 200
            with httpx.Client(trust_env=False) as browser:
                assert browser.get(gateway + "/api/v1/executions").status_code == 401
                issued = browser.post(gateway + "/api/v1/auth/token", json={"username": "admin", "password": "SyntheticUser9!"})
                assert issued.status_code == 200
                assert browser.get(gateway + "/api/v1/executions", headers={"Authorization": "Bearer " + issued.json()["access_token"]}).status_code == 200


def test_browser_gateway_requires_independent_user_authentication(browser_gateway):
    gateway, _, _, conf, _ = browser_gateway
    with httpx.Client(trust_env=False) as browser:
        path = gateway + "/rest/v1/orchestrate/execution-records"
        conf.pop("access_password")
        response = browser.get(path)
        assert response.status_code == 503 and "boundary-canary" not in response.text
        assert browser.post(gateway + "/api/v1/auth/token", json={"username": "admin", "password": "SyntheticUser9!"}).status_code == 503
        conf["access_password"] = hashlib.sha256(b"SyntheticUser9!").hexdigest()
        assert browser.get(path).status_code == 401
        response = browser.post(gateway + "/rest/v1/orchestrate/auth/login",
                                json={"username": "admin", "password": "SyntheticUser9!"})
        assert response.status_code == 200, response.text
        response = browser.get(path)
        assert response.status_code == 200 and "boundary-canary" in response.text
        assert browser.get(gateway + "/api/v1/executions").status_code == 401
        bearer = {"Authorization": "Bearer " + browser.cookies.get("session_token")}
        assert browser.get(gateway + "/api/v1/executions", headers=bearer).status_code == 200


def test_verify_false_only_disables_server_certificate_verification(browser_gateway):
    _, backend, upstream, conf, token = browser_gateway
    with httpx.Client(verify=upstream, trust_env=False) as authenticated_transport:
        issued = authenticated_transport.post(backend + "/api/v1/auth/token", json={"username": "admin", "password": "SyntheticUser9!"})
        assert issued.status_code == 200
        token = issued.json()["access_token"]
    with httpx.Client(verify=False, trust_env=False) as client:
        if conf["verify_client"] == "true":
            # A valid Bearer cannot bypass the server's TLS client certificate gate.
            with pytest.raises(httpx.TransportError):
                client.get(backend + "/api/v1/executions", headers={"Authorization": "Bearer " + token})
        else:
            assert client.get(backend + "/api/v1/executions").status_code == 401
            assert client.get(backend + "/api/v1/executions",
                              headers={"Authorization": "Bearer invalid-token"}).status_code == 401
            response = client.get(backend + "/api/v1/executions",
                                  headers={"Authorization": "Bearer " + token})
            assert response.status_code == 200 and "boundary-canary" in response.text
    upstream.check_hostname = False
    upstream.verify_mode = ssl.CERT_NONE
    with httpx.Client(verify=upstream, trust_env=False) as client:
        assert client.get(backend + "/api/v1/executions",
                          headers={"Authorization": "Bearer " + token}).status_code == 200
