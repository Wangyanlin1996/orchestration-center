<!--

> Legacy / not supported with current service images: the instructions below are historical. `deploy-all.ps1` now fails before any cloud operation. It lacks current account bootstrap, complete model mounts, independent registry identity and Secret Manager injection. Use the current [Helm/Compose deployment contract](https://github.com/project-openan/openan-installation/blob/main/containerized/TRANSPORT_DEPLOYMENT.md); no current GCP acceptance is claimed.
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

# Orchestration Center - Google Cloud Platform Containerized Deployment Guide

This guide helps you deploy the Orchestration Center to Google Cloud Platform **step by step**, no technical background required.

---

## Prerequisites

You need a **Google Cloud account** (sign up with Gmail), and a **GCP project** with billing enabled.

> New users get $300 free credit. Orchestration Center requires one Cloud SQL instance (~$0.015/hour); if deployed alongside Registry Center in the same project, two Cloud SQL instances total ~$0.03/hour.

### How to create a GCP project (if you don't have one)

1. Open https://console.cloud.google.com in your browser
2. Log in with your Gmail account
3. Click **"Select project"** → **"New project"** at the top
4. Pick any project name (e.g. `openan-proj`), click **"Create"**
5. After creation, go to **"Billing"** in the left menu → link a billing account (credit card or PayPal)
6. **Note your project ID** (GCP auto-appends digits, format like `openan-proj-123456`)

---

## Deployment steps (just 3 steps)

### Step 1: Install gcloud CLI

Open PowerShell (right-click Start menu → "Windows PowerShell" or "Terminal"), copy and run:

```powershell
(New-Object Net.WebClient).DownloadFile("https://dl.google.com/dl/cloudsdk/channels/rapid/GoogleCloudSDKInstaller.exe", "$env:TEMP\gcloud-installer.exe"); Start-Process "$env:TEMP\gcloud-installer.exe" -Wait
```

During installation:
- Accept all defaults, click **Next**
- **Check** "Run gcloud init" or "Start shell after installation"
- If a command-line window asks you to log in, use your Gmail account and select the project you just created

> After installation, **close PowerShell and open a new one**.

---

### Step 2: Check login status

In the new PowerShell window, run:

```powershell
gcloud auth list
```

If you see your Gmail account listed, you're logged in.

If not, run `gcloud auth login` — it will open a browser for you to log in.

---

### Step 3: Deploy Registry Center first, then Orchestration Center

Orchestration Center depends on Registry Center for Agent information, so **deploy Registry Center first**.

#### Same project (recommended)

Both services in one GCP project:

```powershell
# Deploy Registry Center first
cd PATH_TO_REGISTRY_CENTER
.\deploy-all.ps1

# Then deploy Orchestration Center
cd PATH_TO_ORCHESTRATION_CENTER
.\deploy-all.ps1
```

> Replace `PATH_TO_...` with actual paths. For example:
> ```powershell
> cd C:\Users\YourName\Desktop\registry-center
> cd C:\Users\YourName\Desktop\orchestration-center
> ```

When running the Orchestration Center deploy script, it will prompt for:
1. **GCP Project ID** — the one you noted earlier (use the same one as Registry Center)
2. **Registry Center** — the script auto-detects the Registry Center in the same project and prompts "Link to this Registry Center? Y/n" — just press Enter to confirm
3. **Database password** — pick any password, or press Enter to auto-generate one
4. **LLM API Key** — your LLM provider's API key (DeepSeek, OpenAI, etc.). You can skip this and configure later, but PSOP generation won't work without it

#### Cross-project deployment

Services in separate GCP projects:

```powershell
# Deploy Registry Center to project A
cd PATH_TO_REGISTRY_CENTER
.\deploy-all.ps1

# Deploy Orchestration Center to project B
cd PATH_TO_ORCHESTRATION_CENTER
.\deploy-all.ps1
```

When running the Orchestration Center script:
1. Enter **project B's** Project ID
2. When prompted for Registry Center → enter **project A's** Project ID → script auto-fetches the URL → confirm linkage

> **Cross-project prerequisite**: Registry Center must have `--allow-unauthenticated` enabled (the deploy script enables this by default).

The script then handles everything automatically:
- ✓ Creates database (Cloud SQL PostgreSQL)
- ✓ Builds Docker image
- ✓ Deploys to Cloud Run
- ✓ Configures Registry Center linkage

**About 10-15 minutes total**. You'll see `DEPLOYMENT SUCCESSFUL!` when done.

---

## Verify deployment

The script outputs a `https://xxxxx.run.app` URL at the end — that's your service URL.

Test with PowerShell:

```powershell
Invoke-RestMethod -Uri "https://YOUR_SERVICE_URL/rest/v1/orchestrate/agent-cards"
```

| Response | Meaning |
|----------|---------|
| Agent list JSON | Working, Registry Center linked |
| `404 "No available agents found"` | Working, but no Agents registered yet |
| `503 "Agent registry unavailable"` | Registry Center linkage needs configuration |

> **404 ≠ failure** — it just means no Agents are registered yet. To verify the Registry Center itself:
> `Invoke-RestMethod -Uri "https://REGISTRY_URL/agent-cards"`

---

## Post-deployment configuration

If you skipped some configuration during deployment, you can add it later.

### Configure Registry Center linkage

```powershell
# Get Registry Center URL
gcloud run services describe registry-center --region=asia-east1 --format="value(status.url)"

# Configure Orchestration Center (replace YOUR_PROJECT_ID and the URL)
gcloud run services update orchestration-center --region=asia-east1 --project="YOUR_PROJECT_ID" --update-env-vars="AGENT_REGISTRY_URL=https://REGISTRY_CENTER_URL"
```

Or just re-run `.\deploy-all.ps1` — existing resources are skipped automatically.

### Configure LLM

PSOP generation and intent orchestration require an LLM — won't work without it:

```powershell
gcloud run services update orchestration-center --region=asia-east1 --project="YOUR_PROJECT_ID" --update-env-vars="LLM_CHAT_MODEL=deepseek-chat,LLM_CHAT_URL=https://api.deepseek.com/v1/chat/completions,A2AT_LLM_PROVIDER=openai,A2AT_LLM_MODEL=deepseek-chat,A2AT_LLM_BASE_URL=https://api.deepseek.com"
```

Inject `LLM_CHAT_API_KEY` and `A2AT_LLM_API_KEY` through your deployment's secret mechanism. Do not put real keys into this command or shell history.

`A2AT_LLM_PROVIDER` selects the A2A-T SDK's LLM client, not the model vendor (the endpoint is whatever `A2AT_LLM_BASE_URL` points at); keep it at `openai`, the one name the SDK registers in every process. Other names are registered only inside specific processes and make the sample agents fail with `Unknown llm provider`.

This deployment path supplies model settings as environment variables, and `etc/config/models.yaml` is
deliberately not part of the image, so the container entrypoint turns the
`LLM_CHAT_*` variables into that file at startup: `LLM_CHAT_MODEL` and
`LLM_CHAT_URL` become the model definition, and `LLM_CHAT_API_KEY` is referenced
by name rather than written to disk. This shortcut uses the `openai_compatible`
protocol profile (the legacy `openai` alias is also accepted), regardless of
model vendor. Other profiles, such as `aoc_signed`, require a complete YAML file.
Only the `chat` capability is generated this way —
provide a complete `models.yaml` at `/opt/orchestration-center/etc/config/models.yaml` when
`embed` or `rerank` is needed. `LLM_CONFIG_HOST_FILE` applies only to Docker Compose,
not to this Cloud Run command. An existing `models.yaml` is never overwritten.

### LLM configuration examples

| Provider | LLM_CHAT_MODEL | LLM_CHAT_URL | A2AT_LLM_BASE_URL |
|----------|----------------|--------------|-------------------|
| DeepSeek | `deepseek-chat` | `https://api.deepseek.com/v1/chat/completions` | `https://api.deepseek.com` |
| OpenAI | `gpt-4o` | `https://api.openai.com/v1/chat/completions` | `https://api.openai.com` |

---

## Troubleshooting

**Q: "gcloud not found" error?**

Close PowerShell and reopen. If it still doesn't work, gcloud wasn't installed properly — go back to Step 1.

**Q: "API has not been used" error?**

Wait 1-2 minutes and re-run `.\deploy-all.ps1`. Some APIs take time to activate.

**Q: Deployment failed — how to retry?**

Just re-run `.\deploy-all.ps1`. Already-created resources are skipped automatically.

**Q: 503 "Agent registry unavailable" when verifying?**

Registry Center linkage wasn't configured. See "Configure Registry Center linkage" above.

**Q: Cross-project deployment — Orchestration Center can't reach Registry Center?**

Make sure Registry Center was deployed with `--allow-unauthenticated` (the deploy script does this by default).

**Q: How to update the service?**

After modifying code, just re-run `.\deploy-all.ps1`.

**Q: How to shut down the service?**

```powershell
gcloud run services delete orchestration-center --region=asia-east1 --project="YOUR_PROJECT_ID"
gcloud sql instances delete orchestration-center-db --project="YOUR_PROJECT_ID"
```

**Q: Will it conflict with Registry Center in the same project?**

No. Cloud Run service names, Cloud SQL instances, and Service Accounts are all separate. Only the Artifact Registry repo is shared.

**Q: How much does it cost?**

- Cloud Run: free when idle, billed per request
- Cloud SQL (db-f1-micro): ~$0.015/hour per instance
- Two Cloud SQL instances in the same project: ~$0.03/hour total

Delete Cloud SQL instances when not in use to save costs.
