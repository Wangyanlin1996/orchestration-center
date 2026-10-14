<!--

> 历史方案，当前镜像不支持：以下步骤未适配账号首次引导、完整模型挂载、独立注册中心身份与 Secret Manager。`deploy-all.ps1` 已在云操作前拒绝执行。请使用当前 [Helm/Compose 部署契约](https://github.com/project-openan/openan-installation/blob/main/containerized/TRANSPORT_DEPLOYMENT.md)，不能将旧指南作为已验收的现行 GCP 部署步骤。
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

# 编排中心 - Google Cloud Platform 容器化部署指南

本指南帮你**一步一步**把编排中心服务部署到 Google Cloud Platform，无需任何技术背景。

---

## 前置条件

你需要一个 **Google Cloud 账号**（用 Gmail 注册即可），并且开通一个 **GCP 项目**并启用结算。

> 新用户有 $300 免费额度。编排中心需要一个 Cloud SQL 实例（约 $0.015/小时），如果和注册中心部署在同一个项目，共两个 Cloud SQL 实例约 $0.03/小时。

### 如何创建 GCP 项目？（如果还没有）

1. 浏览器打开 https://console.cloud.google.com
2. 登录你的 Gmail 账号
3. 顶部点 **"选择项目"** → **"新建项目"**
4. 项目名称随便填（比如 `openan-proj`），点 **"创建"**
5. 创建完成后，在左侧菜单 **"结算"** → 关联结算账号（需要绑定信用卡或 PayPal）
6. **记下你的项目 ID**（GCP 会自动在名称后追加数字，格式类似 `openan-proj-123456`，注意项目 ID 只能包含小写字母、数字和连字符）

---

## 部署步骤（只需 3 步）

### 第 1 步：安装 gcloud CLI

打开 PowerShell（右键开始菜单 → "Windows PowerShell" 或 "终端"），复制下面整段命令回车：

```powershell
(New-Object Net.WebClient).DownloadFile("https://dl.google.com/dl/cloudsdk/channels/rapid/GoogleCloudSDKInstaller.exe", "$env:TEMP\gcloud-installer.exe"); Start-Process "$env:TEMP\gcloud-installer.exe" -Wait
```

安装过程中：
- 全部默认选项，一路 **Next**
- **勾选** "安装完成后启动 shell" 或 "Run gcloud init" 的选项
- 如果弹出命令行窗口要求登录，用你的 Gmail 账号登录，选择刚才创建的项目

> 装完后 **关掉当前 PowerShell，重新打开一个新的**。

---

### 第 2 步：检查登录状态

在新开的 PowerShell 中执行：

```powershell
gcloud auth list
```

如果你看到你的 Gmail 账号显示出来，说明登录成功了。

如果没登录，执行 `gcloud auth login`，会弹浏览器让你登录。

---

### 第 3 步：先部署注册中心，再部署编排中心

编排中心依赖注册中心提供 Agent 信息，所以**必须先部署注册中心**。

#### 同项目部署（推荐）

两个服务部署在同一个 GCP 项目：

```powershell
# 先部署注册中心
cd 注册中心项目目录路径
.\deploy-all.ps1

# 再部署编排中心
cd 编排中心项目目录路径
.\deploy-all.ps1
```

> 把 `项目目录路径` 替换为实际路径。例如：
> ```powershell
> cd C:\Users\你的用户名\Desktop\registry-center
> cd C:\Users\你的用户名\Desktop\orchestration-center
> ```

运行编排中心部署脚本时会提示你输入：
1. **GCP Project ID** — 前面创建项目时记下的那个 ID（和注册中心用同一个）
2. **Registry Center** — 脚本会自动检测同项目内的注册中心，提示 "Link to this Registry Center? Y/n"，直接回车确认即可
3. **数据库密码** — 随便设一个，或者直接回车让系统自动生成
4. **LLM API Key** — 大模型（如 DeepSeek、OpenAI）的 API Key。也可以先跳过，后面再配置（但不配置的话 PSOP 生成等功能无法使用）

#### 跨项目部署

两个服务部署在不同 GCP 项目：

```powershell
# 先部署注册中心到项目A
cd 注册中心项目目录路径
.\deploy-all.ps1

# 再部署编排中心到项目B
cd 编排中心项目目录路径
.\deploy-all.ps1
```

运行编排中心脚本时：
1. 输入**项目B**的 Project ID
2. 脚本检测注册中心时 → 输入**项目A**的 Project ID → 脚本自动获取 URL → 确认链接

> **跨项目前提**：注册中心必须开启了 `--allow-unauthenticated`（部署脚本默认就会开启）。

然后脚本全自动完成：
- ✓ 创建数据库（Cloud SQL PostgreSQL）
- ✓ 构建 Docker 镜像
- ✓ 部署到 Cloud Run
- ✓ 配置注册中心联动

**全程大约 10-15 分钟**，看到 `DEPLOYMENT SUCCESSFUL!` 就成功了。

---

## 验证部署

脚本最后会输出一个 `https://xxxxx.run.app` 的地址，这是你的服务 URL。

用 PowerShell 测试：

```powershell
Invoke-RestMethod -Uri "https://你的服务URL/rest/v1/orchestrate/agent-cards"
```

| 返回结果 | 说明 |
|----------|------|
| Agent 列表 JSON | 正常，注册中心联动生效 |
| `404 "No available agents found"` | 正常，联动生效但注册中心暂无 Agent |
| `503 "Agent registry unavailable"` | 联动配置有问题，需要补配 |

> **404 ≠ 故障**，只是注册中心里还没有注册过 Agent。要验证注册中心本身是否正常，可以访问：
> `Invoke-RestMethod -Uri "https://注册中心URL/agent-cards"`

---

## 部署后补配

如果部署时跳过了某些配置，可以之后补上。

### 补配注册中心联动

```powershell
# 先获取注册中心URL
gcloud run services describe registry-center --region=asia-east1 --format="value(status.url)"

# 再将URL配置到编排中心（把YOUR_PROJECT_ID和注册中心URL替换成实际值）
gcloud run services update orchestration-center --region=asia-east1 --project="YOUR_PROJECT_ID" --update-env-vars="AGENT_REGISTRY_URL=https://注册中心URL"
```

也可以直接重新运行 `.\deploy-all.ps1`，已创建的资源会自动跳过。

### 补配 LLM

编排中心的 PSOP 生成、意图编排等功能依赖大模型，不配置无法使用：

```powershell
gcloud run services update orchestration-center --region=asia-east1 --project="YOUR_PROJECT_ID" --update-env-vars="LLM_CHAT_MODEL=deepseek-chat,LLM_CHAT_URL=https://api.deepseek.com/v1/chat/completions,A2AT_LLM_PROVIDER=openai,A2AT_LLM_MODEL=deepseek-chat,A2AT_LLM_BASE_URL=https://api.deepseek.com"
```

通过部署平台的密钥机制注入 `LLM_CHAT_API_KEY` 与 `A2AT_LLM_API_KEY`；不要把真实密钥直接写入命令或 Shell 历史。

`A2AT_LLM_PROVIDER` 选择的是 A2A-T SDK 的 LLM 客户端，不是模型厂商（实际端点由 `A2AT_LLM_BASE_URL` 决定）；请保持 `openai`，它是 SDK 在每个进程都注册的名字。其它名字只在特定进程内注册，示例 Agent 会因此报 `Unknown llm provider`。

这条部署路径通过环境变量提供模型参数，而 `etc/config/models.yaml` 刻意不打进镜像，因此容器
entrypoint 会在启动时把相关 `LLM_CHAT_*` 变量转成该文件：`LLM_CHAT_MODEL` 与
`LLM_CHAT_URL` 成为模型定义，`LLM_CHAT_API_KEY` 只按名字引用、不落盘。此简化方式使用
`openai_compatible` 协议 profile（也接受旧别名 `openai`），不限模型厂商；
`aoc_signed` 等其他 profile 需要提供完整 YAML。这种方式只生成 `chat` 能力；
需要 `embed` 或 `rerank` 时，请在容器内
`/opt/orchestration-center/etc/config/models.yaml` 提供完整文件。`LLM_CONFIG_HOST_FILE`
仅用于 Docker Compose，不适用于这条 Cloud Run 命令。已存在的 `models.yaml` 不会被覆盖。

### LLM 配置示例

| 提供商 | LLM_CHAT_MODEL | LLM_CHAT_URL | A2AT_LLM_BASE_URL |
|--------|----------------|--------------|-------------------|
| DeepSeek | `deepseek-chat` | `https://api.deepseek.com/v1/chat/completions` | `https://api.deepseek.com` |
| OpenAI | `gpt-4o` | `https://api.openai.com/v1/chat/completions` | `https://api.openai.com` |

---

## 常见问题

**Q: 脚本报错 "gcloud not found"？**

关掉 PowerShell 重新打开。如果还不行，说明 gcloud 没装好，回到第 1 步。

**Q: 看到 "API has not been used" 错误？**

等 1-2 分钟再运行 `.\deploy-all.ps1`，有些 API 启用需要时间。

**Q: 部署失败怎么重试？**

直接再跑一次 `.\deploy-all.ps1` 就行，已创建的资源会被自动跳过。

**Q: 验证返回 503 "Agent registry unavailable"？**

注册中心联动没有配置好。参考上方"补配注册中心联动"章节。

**Q: 跨项目部署时编排中心访问注册中心失败？**

确保注册中心部署时开启了 `--allow-unauthenticated`（部署脚本默认会开启）。

**Q: 如何更新服务？**

修改代码后，再跑一次 `.\deploy-all.ps1` 即可更新。

**Q: 如何关掉服务？**

```powershell
gcloud run services delete orchestration-center --region=asia-east1 --project="YOUR_PROJECT_ID"
gcloud sql instances delete orchestration-center-db --project="YOUR_PROJECT_ID"
```

**Q: 和注册中心部署在同一个项目会冲突吗？**

不会。Cloud Run 服务名、Cloud SQL 实例、Service Account 各自独立，仅共享 Artifact Registry 仓库。

**Q: 费用大概多少？**

- Cloud Run：无请求时不收费，按请求计费
- Cloud SQL（db-f1-micro）：约 $0.015/小时/实例
- 同项目两个 Cloud SQL 实例合计约 $0.03/小时

不使用时删除 Cloud SQL 实例即可节省费用。
