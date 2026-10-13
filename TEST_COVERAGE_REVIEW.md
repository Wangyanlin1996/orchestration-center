# 编排中心测试代码覆盖检视报告

> 检视时间: 2026-09-21 | 代码库: `E:\Project\orchestration-center`

---

## 一、总体概览

| 维度 | 后端 (Python) | 前端 (React/JSX) |
|------|---------------|-----------------|
| 源文件数 | ~121 | ~38 |
| 测试文件数 | 46 (+ conftest.py) | 3 |
| 测试代码行数 | ~8,566 | — |
| 源代码行数 | ~14,499 | ~11,682 |
| 测试通过 | 572 passed | 47 passed |
| 测试失败 | 2 failed | 0 failed |
| 测试跳过 | 22 skipped | 0 skipped |
| 整体覆盖率 | **70%** (5716 stmts, 1708 missed) | **38.4%** (报告值，实际更低) |

### 测试运行结果

- **后端**: 572 passed / 2 failed / 22 skipped / 74 errors (Windows tmp 权限问题)
  - 2 个真实失败: `test_server_conf_defaults.py` — `etc/conf/server.conf` 中 `verify_client=false` 导致安全回归
  - 22 个跳过: 14 个 `external_api` 需要活服务器, 7 个 `frontend_support_server` 需要活服务器, 1 个 POSIX-only
  - 74 个 errors: Windows 沙箱环境下 `%TEMP%` 不可写, 非代码问题
- **前端**: 47 passed / 0 failed / 0 skipped — 全部通过但覆盖极薄

---

## 二、后端覆盖率分层

### 优秀覆盖 (>70%) — 21 个模块

| 模块 | 覆盖率 | 测试文件 | 说明 |
|------|--------|---------|------|
| `orchestrate/core/prompts.py` | 100% | `test_prompts.py` | 5 个 prompt builder 全覆盖 |
| `orchestrate/validation/topology_validator.py` | 99.2% | `test_topology_validator.py` | 环检测/孤儿/安全边界全覆盖 |
| `orchestrate/solution_package/parse_flow.py` | 95.9% | `test_parse_flow.py` | 28 个测试, PDF/Markdown 解析 |
| `orchestrate/validation/sandbox_validator.py` | 95.7% | `test_sandbox_validator.py` | 5 类检查全覆盖 |
| `orchestrate/server/middleware.py` | 94.8% | `test_middleware.py` | 20 个测试, 连接限制+超时+限流 |
| `orchestrate/server/auth.py` | 93% | 4 个测试文件 | 47 个测试, 认证/会话/密码全覆盖 |
| `common/llm/provider/generic_llm.py` | 92.9% | `test_llm.py` | 48 个测试 |
| `common/cert/certificate_generator.py` | 98.2% | `test_certificate_*.py` | 含真实 mTLS 握手测试 |
| `database/utils/user_store.py` | 89.8% | `test_user_store.py` | 35 个测试, 含 hash 升级 |
| `common/util/authenticate_util.py` | 88.2% | `test_authenticate_util.py` | |
| `host_agent/execution.py` | 97.3% | `test_host_execution.py` | 仅缺 1 行 |
| `orchestrate/sandbox/stub_runtime.py` | 88.1% | `test_sandbox_stub.py` | |
| `orchestrate/sandbox/i18n.py` | 97% | `test_sandbox_i18n.py` | |
| `orchestrate/sandbox/service.py` | 84.1% | `test_sandbox_api.py` | 并发/超时/取消全覆盖 |
| `orchestrate/core/persistence.py` | 81.4% | `test_persistence_retrieval.py` | **所有 except 分支未测** |
| `orchestrate/solution_package/manager.py` | 80.8% | `test_solution_package_manager.py` | 异常分支未测 |
| `host_agent/runtime.py` | 81.5% | `test_host_agent_runtime.py` | start/aclose/shutdown 未测 |
| `database/utils/table_creation.py` | 90% | `test_table_creation.py` | |
| `common/llm/config/llm_config.py` | 94.1% | 2 个测试文件 | |
| `common/llm/config/model_sources.py` | 新增 | `test_llm_model_sources.py` | 模型来源解析与协议 Profile |
| `common/util/json_utils.py` / `semaphore_utils.py` / `cipher_util.py` | 100% | 各自专用测试 | |

### 部分覆盖 (30-70%) — 13 个模块

| 模块 | 覆盖率 | 测试文件 | 主要缺失 |
|------|--------|---------|---------|
| `frontend_support_server.py` | 70% | 多个测试文件 | **7 个 @pytest.mark.skip 移除了 PSOP CRUD 和 /generate-from-preflow 流程**; user-admin/execution-record/template 端点错误路径未测 |
| `sandbox_api.py` | 63% | `test_sandbox_api.py` | 404/验证分支未测 |
| `retrieval.py` | 68.4% | `test_persistence_retrieval.py` | **整个 LLM intent 检索路径未测** |
| `sandbox/store.py` | 65.6% | `test_sandbox_api.py` | list_reports/save_templates 及 I/O 错误路径 |
| `sandbox/control_point.py` | 56.2% | 无专用测试 | 四个 on_* 回调体全部未测 |
| `agentcard_loader.py` | 58.4% | 无专用测试 | security_schemes/requirements 规范化未测 |
| `common/util/conf_util.py` | 68.9% | `test_conf_obj.py` | load_cert_password/set_ssl_folder_permissions |
| `common/log/audit_logger.py` | 67.4% | 无测试 | _rotate_logs/_write_log 未测 |
| `common/util/password_util.py` | 55.6% | 无测试 | CLI 输入验证完全未测 |
| `host_agent/workflow_repository.py` | 60% | 无测试 | HTTP 仓库逻辑被 mock 替代 |
| `common/llm/llm.py` | 58.5% | `test_llm.py` | |
| `common/custom/default_handle.py` | 67% | 无测试 | HandlerRegistry 注册/查找/错误路径 |
| `response_utils.py` | 53.6% | `test_response_utils.py` | |

### 覆盖不足 (<30%) — 10 个模块

| 模块 | 覆盖率 | 测试文件 | 说明 |
|------|--------|---------|------|
| `external_api.py` | **24.9%** | `test_external_apis.py` (14 个全部 skip) | **公开 API 8 个端点全无离线测试**, 仅函数签名被执行 |
| `sse_executor.py` | **15.9%** | 无 | SSE 流式管道: heartbeat/drain/event mapping/execution-record 持久化全部未测 |
| `registry_client/client.py` | **21.2%** | 无 | AgentRegistryClient 所有 HTTP 方法仅被 mock 替代 |
| `registry_client/client_factory.py` | **46.2%** | 无 | create_client/create_from_env 未测 |
| `cert_parse.py` | **17.5%** | 无 | 证书解析: parse_cer_certificate/parse_pem_files/parse_crl_list |
| `psop_processor.py` | **24.1%** | 无 | custom_save_psop/custom_delete_psop/get_all_psops |
| `execution_record_processor.py` | **11.8%** | 无 | 四个 DB 函数全部未测 |
| `query_execution.py` | **11.1%** | 无 | 唯一的 SQL 执行辅助函数 |
| `intent_psop_generator.py` | **30.4%** | 无 | generate_psop_from_intent 核心功能未测 |
| `host_agent/service.py` | **40.6%** | `test_host_agent_service.py` (2 个) | start_agent_server 1/40, 服务器引导未测 |

### 完全未测 (0%) — 2 个模块

| 模块 | 行数 | 说明 |
|------|------|------|
| `orchestrate/validation/hooks.py` | 10 | `validate_before_save` 完全未测且为**死代码** — 无任何调用方 |
| `orchestrate/start.py` | 98 | 应用入口: SSL 上下文创建 (证书链/CRL/密码列表)、用户环境解析、启动日志 |

---

## 三、前端覆盖率分析

### 测试文件 (3 个)

| 测试文件 | 测试数 | 覆盖目标 | 结果 |
|---------|-------|---------|------|
| `src/service/api.test.js` | 40 | `api.js` (74% stmts) | 全部通过 |
| `src/components/sandbox/__tests__/sandbox.test.jsx` | 4 | `SandboxDialog.jsx` (38%) | 全部通过 |
| `src/components/execution_center/a2atEvents.test.js` | 3 | `a2atEvents.js` (85%) | 全部通过 |

### 未测源文件 (35/38 = 92%)

**全部无测试的目录:**
- `orchestration_center/` — 15 个文件 (工作流设计器核心 UI, 包括 CustomNodes, CustomEdges, property_panel, sidebar, toolbar, kv_editor)
- `common/` — 7 个文件 (error_boundary, header, login, password_change, pop_confirm, setting, tooltip)
- `execution_center/` — 3 个文件 (index, execution_statistics, timeline)
- `registry_center/` — 3 个文件 (index, agentcard_visualization, code_inspector)
- `skill_center/` — 3 个文件 (index, mock_data, skill_detail)
- 根级别 — 4 个文件 (App, i18n, index, main)

### 覆盖率配置问题

`vite.config.js` 中未设置 `coverage.include` 和 `coverage.all: true`, 导致未导入的文件不会显示为 0%, 报告的 38% 覆盖率严重高估。

---

## 四、缺失的测试类别

### P0 — 安全关键

1. **公开 API 无离线测试** — `external_api.py` 8 个 `/api/v1/*` 端点只有活服务器测试 (全部 skip), 无 TestClient/mock 测试
2. **SSE 流式管道零覆盖** — `sse_executor.py` 的 heartbeat/drain/event mapping/record 持久化全部未测
3. **证书解析/验证管道未测** — `cert_parse.py` + `cert_validator.py` 的实际信任决策 (CerContentValidator/PrivateKeyValidator/CRLValidator/CertValidator.validate) 全部未测
4. **SSL 上下文创建未测** — `start.py` 中 `customized_create_ssl_context` 加载证书链/CRL/密码列表, 零覆盖
5. **安全回归失败未修复** — `etc/conf/server.conf` 仍 `verify_client=false`, 外部 API 在 HTTPS 下无认证

### P1 — 核心功能

6. **LLM 意图检索与生成未测** — `retrieval._retrieve_names_by_intent` / `retrieve_psop_by_intent` / `IntentPsopGenerator.generate_psop_from_intent`, 核心产品功能零覆盖
7. **PSOP 组装未测** — `psop_generator.build_psop_structure` (1/17) 和 `generate_psop_workflow` (1/37)
8. **注册中心客户端未测** — `AgentRegistryClient` 所有 HTTP 行为仅被 mock 替代
9. **编排引擎未测** — `exec_engine._find_target_card`/`_get_engine_client`/`_shape_psop_update` 及所有错误分支
10. **7 个跳过测试需恢复** — `frontend_support_server` 中 PSOP CRUD 和 /generate-from-preflow 流程

### P2 — 健壮性

11. **DB 错误路径全未测** — persistence (12 个 except 块)、manager (7 个)、store、query_execution、psop_processor、execution_record_processor 的所有异常/回滚/None 分支
12. **host_agent 服务器引导未测** — `start_agent_server` 1/40
13. **AgentCard 规范化未测** — security_schemes/requirements 规范化逻辑
14. **审计日志轮转未测** — `audit_logger._rotate_logs` 3/29
15. **前端工作流设计器 UI 零测试** — 15 个核心 UI 组件完全无测试

### P3 — 工程

16. **hooks.py 死代码** — `validate_before_save` 无调用方, 应接入或删除
17. **Windows 临时目录兼容** — 74 个 errors 因 `%TEMP%` 不可写, 需配置 `--basetemp`
18. **前端覆盖率配置** — 需添加 `coverage.include` 和 `coverage.all: true`
19. **deprecated API 使用** — `on_event` 在 FastAPI 中已废弃, 应迁移至 lifespan

---

## 五、改进建议优先级排序

### 第一优先级 (安全 + 核心功能)

| # | 行动 | 目标文件 | 预期效果 |
|---|------|---------|---------|
| 1 | 修复 `verify_client=false` 安全回归 | `etc/conf/server.conf` | 恢复 2 个失败测试 |
| 2 | 为 `external_api.py` 8 个端点写 TestClient 离线测试 | 新建 `test_external_api_offline.py` | 覆盖率 25%→70%+ |
| 3 | 为 `sse_executor.py` 写 async generator 测试 | 新建 `test_sse_executor.py` | 覆盖率 16%→60%+ |
| 4 | 为 `cert_parse.py` + `cert_validator` 验证器写测试 | 新建 `test_cert_parse.py` | 覆盖率 18%→70%+ |
| 5 | 为 `retrieval.py` intent 路径 + `intent_psop_generator` 写测试 | 扩展 `test_persistence_retrieval.py` | 覆盖核心 LLM 功能 |
| 6 | 恢复 7 个 skipped 测试 | `test_frontend_support_server.py` | PSOP CRUD + /plan 流程恢复覆盖 |

### 第二优先级 (核心模块)

| # | 行动 | 目标文件 | 预期效果 |
|---|------|---------|---------|
| 7 | 为 `registry_client/client.py` 写 mock HTTP 测试 | 新建 `test_registry_client.py` | 覆盖率 21%→70%+ |
| 8 | 为 `exec_engine.py` 写边界+错误测试 | 扩展 `test_exec_engine_sdk_boundary.py` | 覆盖率 44%→70%+ |
| 9 | 为 `psop_generator.py` 组装函数写测试 | 扩展 `test_psop_generator.py` | 覆盖率 46%→70%+ |
| 10 | 为 `start.py` SSL 上下创建写测试 | 新建 `test_start.py` | 覆盖率 0%→50%+ |
| 11 | 为 `host_agent/service.py` 引导写测试 | 扩展 `test_host_agent_service.py` | 覆盖率 41%→70%+ |

### 第三优先级 (健壮性 + 前端)

| # | 行动 | 目标文件 | 预期效果 |
|---|------|---------|---------|
| 12 | 为 DB 层 except/rollback 分支写测试 | 扩展各 DB 测试文件 | 错误路径覆盖 |
| 13 | 为 `query_execution.py` 写测试 | 新建 `test_query_execution.py` | 覆盖率 11%→70%+ |
| 14 | 为 `execution_record_processor.py` 写测试 | 新建 `test_execution_record_processor.py` | 覆盖率 12%→70%+ |
| 15 | 删除或接入 `validation/hooks.py` 死代码 | `hooks.py` | 消除 0% 死代码 |
| 16 | 前端: 配置 `coverage.include` + `coverage.all: true` | `vite.config.js` | 真实覆盖率暴露 |
| 17 | 前端: 为 `orchestration_center/` 核心组件写测试 | 新建测试文件 | 前端覆盖率 38%→50%+ |
| 18 | 配置 pytest `--basetemp` 或 `addopts` | `pyproject.toml` | 消除 74 个 Windows errors |
| 19 | 迁移 `on_event` → lifespan | `frontend_support_server.py` | 消除 deprecation 警告 |

---

## 六、各模块覆盖率详细对照表

| 源模块 | 覆盖率 | 测试文件 | 测试类型 |
|--------|--------|---------|---------|
| `orchestrate/core/prompts.py` | 100% | `test_prompts.py` | unit |
| `orchestrate/validation/topology_validator.py` | 99.2% | `test_topology_validator.py` | unit |
| `common/cert/certificate_generator.py` | 98.2% | `test_certificate_*.py` | unit + real TLS |
| `orchestrate/solution_package/parse_flow.py` | 95.9% | `test_parse_flow.py` | unit |
| `orchestrate/validation/sandbox_validator.py` | 95.7% | `test_sandbox_validator.py` | unit |
| `orchestrate/server/middleware.py` | 94.8% | `test_middleware.py` | unit |
| `orchestrate/server/auth.py` | 93% | 4 files | unit |
| `common/llm/provider/generic_llm.py` | 92.9% | `test_llm.py` | unit |
| `host_agent/execution.py` | 97.3% | `test_host_execution.py` | unit |
| `orchestrate/sandbox/i18n.py` | 97% | `test_sandbox_i18n.py` | unit |
| `database/utils/table_creation.py` | 90% | `test_table_creation.py` | unit |
| `common/util/authenticate_util.py` | 88.2% | `test_authenticate_util.py` | unit |
| `orchestrate/sandbox/stub_runtime.py` | 88.1% | `test_sandbox_stub.py` | integration |
| `orchestrate/sandbox/service.py` | 84.1% | `test_sandbox_api.py` | unit + API |
| `host_agent/runtime.py` | 81.5% | `test_host_agent_runtime.py` | unit + integration |
| `orchestrate/core/persistence.py` | 81.4% | `test_persistence_retrieval.py` | unit + integration |
| `orchestrate/solution_package/manager.py` | 80.8% | `test_solution_package_manager.py` | unit |
| `database/utils/user_store.py` | 89.8% | `test_user_store.py` | unit |
| `orchestrate/server/frontend_support_server.py` | 70% | multiple | unit + API (7 skipped) |
| `orchestrate/sandbox/store.py` | 65.6% | `test_sandbox_api.py` | integration |
| `orchestrate/core/retrieval.py` | 68.4% | `test_persistence_retrieval.py` | unit |
| `common/util/conf_util.py` | 68.9% | `test_conf_obj.py` | unit |
| `common/custom/default_handle.py` | 67% | — | none |
| `common/log/audit_logger.py` | 67.4% | — | none |
| `orchestrate/server/sandbox_api.py` | 63% | `test_sandbox_api.py` | unit + API |
| `host_agent/workflow_repository.py` | 60% | — | mocked |
| `orchestrate/agentcard_loader.py` | 58.4% | — | indirect |
| `common/util/password_util.py` | 55.6% | — | indirect |
| `orchestrate/server/response_utils.py` | 53.6% | `test_response_utils.py` | unit |
| `orchestrate/sandbox/control_point.py` | 56.2% | — | none |
| `common/llm/llm.py` | 58.5% | `test_llm.py` | unit |
| `orchestrate/registry_client/client_factory.py` | 46.2% | — | none |
| `orchestrate/core/psop_generator.py` | 45.8% | `test_psop_generator.py` | unit |
| `orchestrate/runtime/exec_engine.py` | 43.9% | `test_exec_engine_sdk_boundary.py` | boundary (1 test) |
| `common/cert/cert_validator.py` | 47% | `test_cert_validator.py` | unit (partial) |
| `host_agent/service.py` | 40.6% | `test_host_agent_service.py` | smoke (2 tests) |
| `orchestrate/core/intent_psop_generator.py` | 30.4% | — | none |
| `orchestrate/server/external_api.py` | 24.9% | `test_external_apis.py` | live-only (all skip) |
| `common/custom/psop_processor.py` | 24.1% | — | none |
| `orchestrate/registry_client/client.py` | 21.2% | — | none |
| `common/cert/cert_parse.py` | 17.5% | — | none |
| `orchestrate/server/sse_executor.py` | 15.9% | — | none |
| `common/custom/execution_record_processor.py` | 11.8% | — | none |
| `database/utils/query_execution.py` | 11.1% | — | none |
| `orchestrate/validation/hooks.py` | **0%** | — | dead code |
| `orchestrate/start.py` | **0%** | — | none |

---

## 七、结论

**后端**整体覆盖率 70%, 数量上看似尚可, 但存在严重的结构性问题:
- **公开 API (`external_api.py`) 和 SSE 管道 (`sse_executor.py`) 几乎零覆盖** — 这是对外契约的核心
- **安全关键代码 (证书解析/验证/SSL 上下文) 基本未测** — 信任决策无验证
- **核心 LLM 功能 (intent 检索/PSOP 生成) 未测** — 产品核心能力无保障
- **DB 层错误路径全未测** — 静默失败风险高
- **7 个测试被 skip** — PSOP CRUD 和 /plan 流程从覆盖中消失
- **2 个安全回归测试失败** — `verify_client=false` 未修复
- **死代码** (`hooks.py`) 存在且无调用方

**前端**覆盖率极度不足: 38 个源文件仅 3 个有测试 (8%), 工作流设计器核心 UI、注册中心、技能中心全部无测试, 且覆盖率配置导致真实缺口被隐藏。

**建议优先处理**: 修复安全回归 → 公开 API 离线测试 → SSE 管道测试 → 证书管道测试 → LLM intent 路径测试 → 恢复跳过测试 → 补齐 DB 错误路径 → 前端核心组件测试。

## 快照适用范围（2026-10-13 补注）

本文保留 2026-09-21 的历史检视证据，不代表当前测试数量、未修问题或当前发布门禁。
其中 server.conf 默认值用例现已针对公开 server.conf.example；用当前源码和实际测试结果判断是否仍有缺陷。
当前套件清单用 `git ls-files tests/` 获取，不能复用本快照计数。
