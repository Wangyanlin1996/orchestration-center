<!--
Copyright (c) 2026 Huawei Technologies Co., Ltd.
All Rights Reserved.

SPDX-License-Identifier: Apache-2.0

   Licensed under the Apache License, Version 2.0 (the "License"); you may
   not use this file except in compliance with the License. You may obtain
   a copy of the License at

        http://www.apache.org/licenses/LICENSE-2.0

   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
   WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
   License for the specific language governing permissions and limitations
   under the License.
-->

# Orchestration Center Development Guide

## 1. Feature Introduction
The Orchestration Center is a visual orchestration platform for multi-agent collaboration, supporting the definition of invocation relationships and execution flows between agents through a graphical workflow designer. The backend parses workflows and drives agent collaboration using a Python framework, helping users efficiently build, manage, and run complex Agent collaboration workflows.

This feature allows users to define custom implementations for different operations while providing default implementations for common operations. Through a unified abstract base class and handler registration mechanism, developers can flexibly extend system functionality without modifying core code.
In addition to the above custom implementations, this feature provides an extensible LLM integration framework configured through environment variables or the repository-root `.env`.

## 2. Constraints and Limitations
- **Operational Constraints**:
  - Custom handler registration should be completed during application startup. Avoid registering during business processing.
  - LLM settings are environment-driven. A new wire protocol requires registering a provider profile.

## 3. Environment Requirements
- Python 3.12+

### 3.1 Setting Up the Environment

This module is designed to be part of a Python project. Ensure the following files are present in the project directory:

**Custom Handler Module:**
- `default_handle.py` - Contains base classes, registry, and default handlers
- `custom_handle.py` - Custom handler extension module (if needed)

**LLM Module:**
- `common/llm/__init__.py` - Module export file
- `common/llm/llm.py` - Unified factory functions
- `common/llm/config/model_sources.py` - Environment settings source and provider profiles
- `common/llm/config/llm_config.py` - ModelConfig dataclass
- `common/llm/provider/auth_strategies.py` - Header signing strategies
- `common/llm/provider/generic_llm.py` - Generic LLM Provider
- `.env` - Local LLM configuration (not committed)

### 3.2 Verifying the Environment

Verify default handlers:
```python
from common.custom.default_handle import HandlerRegistry, InterfaceType

# Verify that default handlers are available
handler = HandlerRegistry.get_handler(InterfaceType.SAVE_PSOP)
print(f"Handler loaded successfully: {type(handler).__name__}")
```
Verify LLM configuration:
```python
from common.llm import get_llm_instance

# Verify that LLM configuration loaded successfully
llm = get_llm_instance()  # Uses the "chat" capability by default
print(f"LLM loaded successfully: {llm.to_dict()}")
```

## 4. Usage Scenarios
### 4.1 Custom Handler Usage Guide
#### 4.1.1 Feature Introduction
**Core Capabilities:**
- **Abstract Base Class**: Defines a unified interface for all handlers
- **Default Implementations**: Provides built-in handlers for common operations
- **Custom Extensions**: Supports user-registered custom handlers

**System Architecture:**
The system adopts a registry pattern. The core components include:

| Component | Responsibility |
|-----------|----------------|
| BaseHandler | Defines the unified abstract interface for all handlers |
| HandlerRegistry | Manages handler registration and retrieval, providing default implementations as fallback |
| InterfaceType | Defines the enumeration of supported interface types |
| Default Handlers | Provide built-in implementations for common operations |
| Custom Handlers | User-extended implementations that override default behavior |

```
┌──────────────────────┐
│   Business Caller    │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│   HandlerRegistry    │◄──── Register custom handlers
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│     BaseHandler       │
│  (Abstract Base)     │
└──────────┬───────────┘
      ┌────┴────┬───────────────┐
      ▼         ▼               ▼
┌──────────┐ ┌──────────┐ ┌──────────────┐
│ Default  │ │ Default  │ │   Custom     │
│ Handler1 │ │ Handler2 │ │   Handler3   │
└──────────┘ └──────────┘ └──────────────┘
```
#### 4.1.2 When to Use Custom Handlers

The following scenarios require users to implement custom handlers:

| Scenario | Description | Example |
|----------|-------------|---------|
| Database Persistence | `persistence_mode=postgresql` or `mysql` selects the bundled SQL handlers | PSOP and execution records in PostgreSQL/MySQL |
| Custom Storage Media | A backend not bundled by this service requires custom storage handlers | MongoDB or Redis storage integration |
| Storage Logic Customization | When additional business logic needs to be added to save/query/delete operations, a custom handler is needed to extend default behavior | Adding audit logging when saving PSOP |

**Configuration Notes:**

Configure the `persistence_mode` parameter in `etc/conf/server.conf`:

```properties
persistence_mode=file  # Uses default file storage; no custom handler needed
persistence_mode=postgresql  # Uses bundled PostgreSQL handlers
persistence_mode=mysql       # Uses bundled MySQL handlers (8.0.19+)
```

Database modes select registered SQL handlers; unsupported mode values are rejected at startup. MySQL setup and storage boundaries: [MySQL persistence](MySQL%20Persistence.md).

#### 4.1.3 Development Steps
Step 1: Import required modules
```python
from common.custom.default_handle import BaseHandler, HandlerRegistry, InterfaceType
```

Step 2: Create a custom handler

Create a custom class inheriting from BaseHandler and implement the handle method:
```python
class MyCustomHandle(BaseHandler):
    """Custom handler example"""
    
    def handle(self, *args, **kwargs):
        """
        Custom processing logic
        
        Args:
            *args: Positional arguments
            **kwargs: Keyword arguments
            
        Returns:
            Processing result
        """
        # Custom implementation
        # Recommendation: add specific business logic here
        # Storage handler.handle is synchronous; async auth hooks are a different interface.
        result = "Custom result"
        return result
```
Step 3: Register the custom handler

Register the custom handler at application startup:
```python
# Register custom handler
# Note: Registration should be completed before business processing begins
HandlerRegistry.register(InterfaceType.GET_PSOP_BY_ID, MyCustomHandle)
```
Warning: A later-registered handler will overwrite a previous handler of the same type. Ensure the registration order matches expectations.

Step 4: Use the handler

Retrieve and use the handler in business code:
```python
# Get handler instance
# HandlerRegistry will automatically return the registered custom handler or default implementation
handle = HandlerRegistry.get_handler(InterfaceType.GET_PSOP_BY_ID)

# Use the handler for business execution
result = handle.handle(...)
```
Step 5: Complete example

Below is a complete custom handler implementation example:
```python
from common.custom.default_handle import BaseHandler, HandlerRegistry, InterfaceType

class SaveCustomHandle(BaseHandler):
    """Custom query handler"""
    
    def handle(self, query_params=None):
        """
        Custom query logic
        
        Args:
            query_params: Query parameter dictionary
            
        Returns:
            List of query results
        """
        # Example: implement custom query logic
        if not query_params:
            return []
        
        # Custom query implementation
        results = []
        # ... business logic
        return results

# Register
HandlerRegistry.register(InterfaceType.SAVE_PSOP, SaveCustomHandle)

# Use
handler = HandlerRegistry.get_handler(InterfaceType.SAVE_PSOP)
data = handler.handle({"id": 1})
print(data)
```
#### 4.1.4 Default Handler Reference

If no custom handler is registered, the system will use the following default implementations:

| Handler | Corresponding Interface Type | Functional Description |
|---------|-----------------------------|------------------------|
| SavePsopHandler | SAVE_PSOP | Save PSOP |
| GetAllPsopsHandler | GET_ALL_PSOP | Query all PSOPs |
| GetPsopHandler | GET_PSOP_BY_ID | Query the corresponding PSOP by its ID |
| DeletePsopHandler | DELETE_PSOP | Delete PSOP |

#### 4.1.5 Testing and Verification
Verify default handlers:
```python
from common.custom.default_handle import HandlerRegistry, InterfaceType

# Verify default handler
handler = HandlerRegistry.get_handler(InterfaceType.GET_PSOP_BY_ID)
assert handler is not None, "Handler retrieval failed"
print(f"Currently used handler: {type(handler).__name__}")
```
Verify custom handler registration:
```python
from common.custom.default_handle import HandlerRegistry, InterfaceType

class TestHandle(BaseHandler):
    def handle(self, *args, **kwargs):
        return "test_success"

# Before registration
handler_before = HandlerRegistry.get_handler(InterfaceType.SAVE_PSOP)
print(f"Before registration: {type(handler_before).__name__}")

# Register
HandlerRegistry.register(InterfaceType.SAVE_PSOP, TestHandle)

# After registration
handler_after = HandlerRegistry.get_handler(InterfaceType.SAVE_PSOP)
print(f"After registration: {type(handler_after).__name__}")

# Verify functionality
result = handler_after.handle()
assert result == "test_success", "Custom handler did not take effect"
print("Verification passed")
```

### 4.2 LLM Module Configuration Guide

The Chat, Embedding, and Reranker clients read model definitions from `etc/config/models.yaml` and secrets from the process environment or the repository-root `.env` file. Process environment values take precedence; empty values do not mask `.env`. See [LLM configuration](../../etc/config/README_en.md) and [`.env.example`](../../.env.example).

Each key under `models:` is a capability (`chat`, `embed`, `rerank`, or any name a registered profile supports) and must set `model` and `url`. `provider` defaults to `openai_compatible` (the legacy alias `openai` is also accepted); `aoc_signed` supports signed AOC requests through `auth.app_key_env` and `auth.app_secret_env`. `description`, `timeout`, `verify_ssl`, and `enable_thinking` are optional, and `api_key_env` names the variable that holds the key. The file is gitignored and holds no secrets, since every secret field names an environment variable; `LLM_CONFIG_FILE` selects a different path. A new wire format is implemented as a registered provider profile in `common/llm/config/model_sources.py`, without changing the configuration loader.

Restart the process after changing settings; model clients are cached per process. For a one-time migration from env-only settings, run `python -m scripts.migrate_llm_config`; for legacy JSON, run `python -m scripts.migrate_legacy_llm_json`. The tools reject conflicts and never print secrets; custom legacy request templates require a registered profile first.

## 5. FAQ
### 5.1 Custom Handler Not Taking Effect
**Symptom**: A custom handler was registered, but the default handler is still used when invoked.

**Possible Causes**:
- 1. The registration was performed after the handler was retrieved
- 2. The registered interface type does not match the one actually used
- 3. The custom handler did not properly inherit from BaseHandler

**Solutions**:
- 1. Ensure registration is completed at application startup, before any business processing
- 2. Check that the InterfaceType used during registration and retrieval is consistent
- 3. Confirm that the custom handler properly inherits from BaseHandler and implements the handle method

### 5.2 New Model Configuration Not Taking Effect?

**Symptom**: Modified `models.yaml` or `.env` but the changes did not take effect.

**Possible Causes**:
- 1. The capability has no entry under `models:`.
- 2. `model` or `url` is missing for that capability.
- 3. A process environment variable overrides `.env`.
- 4. The service was not restarted after editing settings.

**Solutions**:
- 1. Verify the capability name and the `provider` profile selected for it.
- 2. Restart the service; model clients are cached per process.
- 3. Check the selected profile against the endpoint protocol.

### 5.3 Model Invocation Error "Unable to extract..."

**Symptom**: `ValueError: Unable to extract ...` when calling `embed()` or `rerank()`.

**Possible Causes**: The selected provider profile does not match the endpoint response protocol.

**Solutions**:
- 1. Inspect the actual response shape without logging credentials or prompt content.
- 2. Register a profile with the correct response mapping in `common/llm/config/model_sources.py`.
- 3. Add a response parsing test for the new profile.


### Host Agent Runtime

The top-level `host_agent` package provides the workflow execution host. It handles the A2A server, Workflow Engine invocation, execution-event wrapping, and lifecycle management. Runtime configuration, AgentCard loading, engine-client creation, and business policy are injected at the sample composition root. Task content, conditional routing, SelfLoop processing, and negotiation replies are supplied by ControlPoint implementations; the sample SPN policy is under `samples/spn_host_agent`. Start it with:

```bash
python -m samples.start_agents_server
```

The Orchestration Center owns PSOP data submitted by the UI. When the Execution Center dispatches a workflow, it puts a PSOP snapshot into A2A metadata; direct intent execution falls back to the configured Workflow Repository.

### Sandbox Verification

Sandbox verification is independent from formal execution. Static validation checks the DAG, `context_from`, Agent/Skill matching, and Task-T/Negotiation-T declarations. Stub execution reuses the real Workflow Engine scheduling path but replaces remote task-content generation and A2A calls with local sandbox input and Stub responses. A saved workflow is loaded by ID; an unsaved or imported editor workflow can submit the current canvas as a `psop` snapshot, which the backend validates with the `PSOP` model. Reports record pass/warning/fail checks, execution path, context trace, Stub interactions, risks, and suggestions.

A sandbox `pass` means workflow structure and engine scheduling were verified with Stub Agents. It does not prove that real Agents will produce correct business output. Sandbox reports and formal execution records are stored separately, and the frontend marks sandbox results with a `SANDBOX` badge. Deleting an active verification cancels its background task before removing its report.

Backend report text is loaded from `orchestrate/sandbox/locales/{zh,en}.json`. The frontend sends `zh` / `en` when starting a run and maps fixed enum values through `workflow-designer/src/locales/*.json`. Do not concatenate user-visible sentences in business code; maintain both resource files when adding checks or suggestions.


## 6. Security and TLS Configuration

### 6.1 Frontend Login Authentication

The internal API (`/rest/v1/orchestrate/*`) supports token-based authentication with two modes:

**Database mode (`persistence_mode=postgresql` or `mysql`)**:
- **User store**: `database/utils/user_store.py` -- CRUD operations on PostgreSQL/MySQL `users` table with versioned bcrypt password hashes
- **First boot**: an empty SQL user store requires `OC_ADMIN_INITIAL_PASSWORD` or `admin_initial_password_file`; `seed_admin_if_empty()` creates `admin` from that secret. Existing users are not reset. Change the initial password in the UI and log in again.
- **Registration**: `POST /auth/register` endpoint available, username format validated, password complexity enforced by the backend (the UI also validates input)
- **User management**: `GET /auth/users` (list), `DELETE /auth/users/{username}` (delete, admin protected)
- **Auth module**: `orchestrate/server/auth.py` -- `SessionStore` maps token to (username, expiry), `auth_middleware`
- **Auth endpoints**: `POST /auth/login`, `POST /auth/register`, `POST /auth/logout`, `GET /auth/check`, `GET /auth/users`, `DELETE /auth/users/{username}`
- **is_auth_enabled()**: Checks `persistence_mode` -- PostgreSQL/MySQL mode queries `has_any_user()`, file mode checks `access_password` config

**File mode (`persistence_mode=file`)**:
- **Configuration**: Set `access_password` (SHA-256 hash) and `access_token_ttl` in `etc/conf/server.conf`
- Single `admin` user with password from config, no registration or user management
- Account storage does not fall back on database failure; unavailable authentication fails closed.

**Common to both modes**:
- **Token delivery**: internal APIs accept an HttpOnly, SameSite=Lax cookie or Bearer header. Secure follows `public_scheme` or the trusted public request scheme, not backend TLS alone. EventSource uses the cookie. Public `/api/v1/*` requires an explicit Bearer from `POST /api/v1/auth/token`; cookies and URL tokens do not authenticate it.
- **Password hashing**: the frontend sends the plaintext password over TLS; the backend hashes it (per-user salt in DB mode, or against the configured SHA-256 in file mode)
- **Required**: no anonymous mode, loopback exemption or TESTING bypass. Missing account configuration rejects startup; runtime unavailability returns 503. Password changes, deletion and logout revoke sessions; API tokens have the same TTL.

### 6.2 TLS/HTTPS Configuration

Server-side HTTPS is configured via `etc/conf/server.conf`:

| Key | Description |
|-----|-------------|
| `enable_https` | Enable HTTPS for the backend |
| `verify_client` | Require client certificate (mTLS) |
| `ssl_certfile` | Server certificate |
| `ssl_keyfile` | Server private key (encrypted) |
| `ssl_keyfile_password` | Password file for private key |
| `ssl_ca_certs` | CA trust store |

Certificate validation requirements (in `common/cert/cert_validator.py`):
- RSA: key size >= 3072 bits
- ECDSA: key size >= 256 bits

> **Development, testing, and demos only:** this tool is intended for quick startup. Do not use any CA, server certificate, client certificate, or private key it generates in production. Production deployments must use a trusted public or enterprise CA and follow the organization's certificate-management policy.

Generate compliant self-signed certificates:
```bash
python -m generate_selfsign_cert etc/ssl serverAuth
```

New TLS certificates include SANs for `DNS:localhost`, `IP:127.0.0.1` and `IP:::1` by default.
For other endpoints, repeat `--dns` / `--ip` for the actual client-facing names; explicit options replace the default SAN list:

```bash
python -m generate_selfsign_cert etc/ssl-new serverAuth --dns orch.example.test --ip 192.0.2.10
```

SANs must match the host in the client URL; IP addresses require `--ip`. Setting CN or trusting a certificate does not fix missing SANs.
Existing certificates are not updated automatically, and the tool refuses to overwrite certificates or private keys.
For an existing deployment, generate into a new directory, back up and deploy the matching certificate/key pair, then restart.
Update client trust material where required; do not overwrite the CA store used to authenticate clients.
`dataSigning` does not add TLS SANs and rejects CLI SAN options.

**Enabling HTTPS (step by step):**

1. Generate certificates (see above). For `serverAuth` the command already produces the deployment
   files expected by `server.conf` (`server.cer`, `trust.cer`, `server_key.pem`, `cert_pwd`);
   `--plain-key` additionally writes the unencrypted `server_key_nopass.pem` for nginx — no manual
   copying or password file creation needed. The default password path is `etc/ssl/cert_pwd`.
   All existing outputs, including passwords and client credentials, are protected from overwrite.
   Rotate into a new directory, reissue client certificates and redistribute trust.
   Protect the plaintext password together with the keys; use service-account ACLs on Windows.
   For separate signing test material run `python -m generate_selfsign_cert etc/sign_cert dataSigning`:
   it exports `sign.cer`, `sign_key.pem` and `cert_pwd`, without enabling business signing.

2. Set `enable_https=true` in `etc/conf/server.conf`. Set `verify_client=true` for mTLS.

3. Set `client_verify_server=false` in `etc/conf/server.conf` to skip remote cert verification (self-signed certs).

4. Restart the backend service.

**Issuing client certificates (when `verify_client=true`):**

The self-signed server certificate doubles as its own CA (`trust.cer` is a copy of it, carrying
`CA:TRUE` and `keyCertSign`). Issue a client certificate for each client that needs to connect:

```bash
python -m generate_selfsign_cert etc/ssl serverAuth --issue-client dev-proxy
```

- Writes `etc/ssl/dev-proxy-client.cer` and `dev-proxy-client.key` (unencrypted, owner-only
  permissions on Linux); the password is read from `cert_pwd` automatically — no interaction.
- `dev-proxy` is the convention used by the Vite dev proxy: `workflow-designer/vite.config.js`
  reads this pair at startup to present a client certificate to this service. Restart
  `npm run dev` after issuing.
- For a local or demo Nginx proxy: browsers cannot present client certificates, so Nginx presents
  one on their behalf — configure `proxy_ssl_certificate` / `proxy_ssl_certificate_key` with this
  pair and `proxy_ssl_trusted_certificate` pointing at `trust.cer` (see the commented block in
  `workflow-designer/nginx.conf.template`).

Chain requirement: client certificates must be issued by a CA in the `ssl_ca_certs` trust store.
The server certificate generated by this tool already satisfies that; with an external CA, issue
client certificates from that CA instead.

### 6.3 Client-Side SSL Context

Outbound HTTPS calls (e.g., orchestration center -> registry center) use a shared SSL context factory:

- **Module**: `workflow_engine.client.ssl_context` -- `create_ssl_context()` (provided by the workflow-engine SDK)
- **Config**: `client_verify_server` in `server.conf` (default: `true` in the public template and main-service factories)
- **Features**: CA trust store verification, optional mTLS client cert, CRL checking, cipher suite enforcement
- **Usage**: Called as `create_ssl_context(verify_server=...)` and passed to `httpx.AsyncClient(verify=...)` in `orchestrate/registry_client/client.py`

When verification is disabled, an mTLS client identity is still loaded into an SSLContext; only server chain/hostname verification is disabled. Without client identity the client may use `verify=False`. Conflicting CA/CRL settings are rejected. Keep verification enabled with the correct CA in production; see [transport runtime](../transport-runtime.md).

### 6.4 External API Protection

Public `/api/v1/*` uses the same configured account as web login. Obtain a Bearer from `POST /api/v1/auth/token` and send it in `Authorization`; cookies/URL tokens do not authenticate public APIs. HTTP and HTTPS both require application authentication. `verify_client=true` adds an independent mTLS handshake requirement; a proxy certificate or a client's `verify=False` never substitutes for an account Token. See section 6.1 for bootstrap, expiry and revocation.
