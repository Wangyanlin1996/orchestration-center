# 容器传输与认证配置

HTTP、HTTPS、是否验证客户端证书、业务认证与 AgentCard 签名是独立职责。模板没有秘密；.env 与实际 server.conf/PKI 不作为镜像输入。Python 直接解析环境覆盖，不改写挂载的配置文件。

## 编排中心

- SQL 模式：PERSISTENCE_MODE=mysql/postgresql，DB_HOST/PORT/NAME/USERNAME/PASSWORD 注入；空用户库初次启动用 OC_ADMIN_INITIAL_PASSWORD（优先）或 admin_initial_password_file，按服务端口令长度/复杂度规则校验，不再使用硬编码管理员密码。密码文件末尾换行会移除，密码本身不裁剪；已存在用户时不再读取初始化口令，也不重置账号。文件模式用户认证使用 ORCH_ACCESS_PASSWORD（版本化密码哈希），数据库初始化密码在文件模式无效。
- 外部机器 API：默认 auto；验证客户端证书的 HTTPS 使用 mTLS，否则使用 ORCH_API_TOKEN（至少 32 字节）的 Authorization: Bearer。用户 Cookie 不作为机器认证；旧的匿名机器客户端需要升级。
- 自定义认证：external.auth.mode=custom，通过 HandlerRegistry.register(InterfaceType.AUTHENTICATE_EXTERNAL, ...) 注册 BaseHandler 扩展，async handle(Request) 返回 MachineIdentity；异常/空结果失败关闭。插件必须在 startup preflight 前显式加载。
- ORCH_ENABLE_HTTPS 与 ORCH_VERIFY_CLIENT 分开设置；ORCH_CLIENT_VERIFY_SERVER 控制访问 RC 的服务端校验。RC 主端口 Token 模式需要 REGISTRY_ACCESS_TOKEN，私有 CA/mTLS 使用 REGISTRY_CA_FILE、REGISTRY_CLIENT_CERT、REGISTRY_CLIENT_KEY，加密客户端 key 的口令通过 REGISTRY_CLIENT_KEY_PASSWORD 注入。
- ORCH_CLIENT_VERIFY_SERVER=false 只关闭远端服务证书/主机名校验，不丢弃 REGISTRY_CLIENT_CERT/KEY；mTLS 身份仍加载和校验。此模式不配置 REGISTRY_CA_FILE（也不接受 CRL），缺一侧身份文件、不可读密钥或错误口令仍失败关闭。注册中心适配器保持此合同，即使当前安装的 SDK 发布版本在关闭校验时直接返回 verify=False；本地 editable SDK 的行为不作为发布镜像能力证明。
- ORCH_PUBLIC_SCHEME 指公共浏览器入口（http/https），与后端协议不一定一致。可信代理地址使用 ORCH_FORWARDED_ALLOW_IPS，不应默认 *；不会直接读取未受信的 X-Forwarded-Proto。
- Compose 默认浏览器入口为 HTTP，因此公共协议默认 http，即使后端使用 HTTPS。外部 HTTPS 网关或直接使用后端 HTTPS 登录时，显式设置 ORCH_PUBLIC_SCHEME=https；这控制 Cookie Secure，不改变后端监听协议。
- Compose 前端根据 ORCH_ENABLE_HTTPS 推导 upstream 协议；默认验证 HTTPS，需要 BACKEND_CA_FILE，mTLS 还需 BACKEND_CLIENT_CERT/KEY。BACKEND_VERIFY_SERVER=false 是显式跳过服务端校验，不会取消客户端证书要求。
- 浏览器代理不暴露 `/api/v1/*` 机器 API，Nginx 默认拒绝 `/api/orchestrate/api/*`。Nginx/Vite 设置 `X-OpenAN-Browser-Gateway: 1`，后端据此进一步限制访问，不把该头当身份凭证：机器 API 拒绝该路径，用户接口必须有独立用户认证。文件模式未配用户口令时代理用户接口返回 503，不会借用代理证书开放匿名访问。自定义浏览器代理必须同样覆盖该标记并禁止机器 API；该头即使被伪造也只会减少权限。直连机器客户端仍支持 mTLS，或 Bearer/业务扩展认证。
- 独立 HostAgent 接入使用显式 HostTlsConfig；HTTPS 声明缺材料会失败，不再降级 HTTP。独立 HostAgent 的注册中心凭据请由调用方注入 AgentCardProvider，不能依赖编排中心的全局环境。


## 镜像与挂载

公共工作流模板是只读发布资源，位于 `samples/workflow_templates/`，由镜像白名单明确打包；`/templates` 及导入接口从该目录读取，不依赖运行态 `data/`，因此挂载空数据卷也可以使用。旧版本的公共 `data/workflow_templates/` 随源码升级迁移到新目录；不会自动移动或删除部署现场的文件。若曾自行扩展旧目录模板，需要人工审查并迁入发布资源目录、重建镜像，不能期待旧数据卷覆盖内置模板。

即使使用 MySQL/PostgreSQL，PreFlow、沙箱报告/Stub 模板、方案包仍为文件存储。容器部署必须持久化 `/opt/orchestration-center/data` 和 `/opt/orchestration-center/log`；SQL 不是这些文件的备份。Helm 的持久卷及升级迁移约定见打包仓库部署文档。

模型使用完整 etc/config/models.yaml，api_key_env/auth.*_env 引用 .env 或 Secret。LLM_CONFIG_FILE 可选择其他挂载；挂载优先于 chat-only 的环境生成，显式选择不存在的文件会拒绝。Compose 使用长格式 bind 并禁止自动创建缺失的模型/凭据文件为目录。

TLS bundle：server.cer、server_key.pem、cert_pwd、trust.cer。验证客户端时还需 CA/可选 CRL；关闭客户端校验时不会因缺 CA/CRL 阻止监听，但 HTTPS 健康探针仍必须有可校验的服务端 CA。服务原有密钥强度/口令规则不变。生产使用企业 CA，开发可使用 generate_selfsign_cert.py。

### HTTPS 的两种证书校验开关

服务端 `ORCH_ENABLE_HTTPS=true`、`ORCH_VERIFY_CLIENT=false`：仍是 HTTPS，但不要求调用方提供客户端证书。调用方使用 HTTPX/Requests 的 `verify=False`：仅关闭调用方对服务端证书及主机名的校验。两者可以同时设置，TLS 能建立；它们均不关闭业务鉴权。

机器 API 在 auto 模式下改用至少 32 字节的 `ORCH_API_TOKEN`，调用方传 `Authorization: Bearer ...`；无/错 Token 返回 401，正确 Token 可以访问业务接口。浏览器用户接口仍先登录、携带会话 Cookie。`ORCH_CLIENT_VERIFY_SERVER=false` 是编排中心作为调用方访问注册中心时的出站开关，与入站 `ORCH_VERIFY_CLIENT` 不是同一个设置。

若服务端启用 `ORCH_VERIFY_CLIENT=true`，调用方仅设置 `verify=False` 不能绕过客户端证书要求：仍需传合法客户端证书/私钥，否则 TLS 握手失败。HTTP 与 HTTPS-no-mTLS 均不提供生产匿名业务认证模式；只保留显式 loopback `security.dev_insecure_mode=true` 的本地演示例外。自签名开发可跳过服务端验证，生产应配置可信 CA。

Linux 应用 UID=10001；只读挂载目录推荐 0700、文件 0600 或组内只读 0440/0640，不得世界可读或组可写。Kubernetes 模板以 subPath 挂载文件到受限镜像目录，Secret 更新需滚动重启。探针必须匹配证书 SAN；mTLS 探针另需客户端证书/私钥。/health 只报告最小健康，不返回业务列表，不能当作真实数据库/模型的持续业务验收。

完整 MySQL/HTTP/HTTPS/Helm 配置见 openan-installation 的 containerized/TRANSPORT_DEPLOYMENT.md。上线前运行真正的镜像、数据库和代理链路验收，不以单元测试通过代替环境验证。
