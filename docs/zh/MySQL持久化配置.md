<!-- Copyright (c) 2026 Huawei Technologies Co., Ltd. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0 -->

# MySQL 持久化配置

支持 **MySQL 8.0.19+**，集成 CI 使用 MySQL 8.4 LTS。不支持 MySQL 5.7 或 MariaDB。
安装 `requirements.txt` 即包含 PyMySQL、DBUtils，不需要额外安装系统客户端库。

## 范围与边界

在 `etc/conf/server.conf` 设置 `persistence_mode=mysql`，即可使用与 PostgreSQL 相同的
数据库处理器：PSOP 工作流、执行记录、用户账号进入数据库。PreFlow、模板、方案包、
沙箱会话和审计文件仍按现有方式保存在文件中；登录会话令牌仍在内存中，服务依然只支持
单进程会话。切换存储类型不会自动迁移旧 JSON/PostgreSQL 数据，也不自动导入样例工作流。

数据库不存在时自动创建；启动时创建、检查表结构。仅首次创建数据库需要 CREATE DATABASE，
预建数据库的账号需具备表 CREATE、ALTER（旧用户表升级）、SELECT、INSERT、UPDATE、DELETE。
MySQL DDL 不能通过事务回滚；这里是可重复执行的启动建表，不是通用迁移框架。

表使用 InnoDB、utf8mb4，以及区分大小写且不忽略尾部空格的 `utf8mb4_0900_bin`；正文使用
LONGTEXT，时间使用 DATETIME(6)，按 UTC 存取。MySQL 的 PSOP ID 上限为 255 字符，执行 ID
和用户名各 64 字符；超长会报错，不静默截断。大记录同时受服务端 `max_allowed_packet`
以及现有 HTTP 请求体上限约束。

## 配置与启动

1. 将 `etc/conf/db/mysql.json.template` 复制为 `etc/conf/db/mysql.json`，设置地址、
   端口、库名和账号。真实配置已加入 Git 和 Docker 忽略规则。MySQL 模式不读取 PostgreSQL
   的 `db/postgresql.json`。
2. 密码通过 `password_env` 指定的变量注入，默认 `MYSQL_PASSWORD`。支持进程环境和根目录
   `.env`，进程环境优先。`MYSQL_HOST`、`MYSQL_PORT`、`MYSQL_DATABASE`、`MYSQL_USER`、
   连接池、超时及 `MYSQL_SSL_CA` 也覆盖 JSON 配置；容器可全部使用环境变量，无需 JSON。
   缺少密码变量会报错；显式设置为空才允许无密码的临时测试实例。
   不再接受 JSON 中的明文或密文 `password`，只使用变量引用。
3. 设置 `persistence_mode=mysql`。SQL 空用户库通过秘密管理器注入 `OC_ADMIN_INITIAL_PASSWORD`，
   或将 `admin_initial_password_file` 指向受保护的口令文件。运行 `python -m orchestrate.start`，
   启动用此秘密创建 admin；已有账号不重置，也不再要求首次引导口令。
4. 首次在网页改密，再重新登录并获取 API Token；数据库口令与应用账号、TLS/mTLS 独立。

可信管理员仍可在对外启动前离线调用 `create_tables()` 与
`seed_admin_if_empty(getpass.getpass(...))` 预建账号，这是可选操作，不是正常引导的必需步骤。
不要绕过安全预检。

## 连接参数

| JSON 参数 | 环境变量 | 默认与含义 |
|---|---|---|
| `host`、`port` | `MYSQL_HOST`、`MYSQL_PORT` | `127.0.0.1`、`3306` |
| `database`、`user` | `MYSQL_DATABASE`、`MYSQL_USER` | `orchestration_center`；账号必须配置 |
| `password_env` | 该字段指定的变量 | 默认 `MYSQL_PASSWORD`；变量必须存在（允许显式空值用于本地无密码数据库） |
| `pool_min`、`pool_max` | `MYSQL_POOL_MIN`、`MYSQL_POOL_MAX` | 每进程 `1`、`20`；0 <= min <= max，max >= 1 |
| `connect_timeout` | `MYSQL_CONNECT_TIMEOUT` | TCP 连接超时，默认 10 秒 |
| `read_timeout`、`write_timeout` | `MYSQL_READ_TIMEOUT`、`MYSQL_WRITE_TIMEOUT` | 套接字读写超时，各 30 秒；不是 SQL 总耗时上限 |
| `ssl_ca` | `MYSQL_SSL_CA` | 空值是本地开发明文连接并告警；生产应设置可信 CA 路径 |

配置 CA 后同时校验证书和主机名。数据库/TLS 故障不会回退到 PostgreSQL 或文件模式；
连接池耗尽立即报错，不无限等待。取连接时检查存活、显式开始事务，写入提交，异常回滚，
归还连接时重置事务，应用关闭时释放池。超时不是整个 HTTP 请求的总时限；不自动重放
提交结果不确定的写操作。

## 容器

对接外部 MySQL：注入 `PERSISTENCE_MODE=mysql` 和 `MYSQL_*`，生产环境只读挂载可信 CA 并
设置 `MYSQL_SSL_CA`。入口脚本不把 MySQL 密码写入配置文件。

本地独立 MySQL 示例：在 `.env` 设置 `MYSQL_USER`、`MYSQL_PASSWORD` 和独立的
`MYSQL_ROOT_PASSWORD`，然后执行以下命令。MySQL 只接入容器网络，不向宿主发布数据库端口。

```bash
docker network create openan-net  # 网络不存在时执行一次
docker compose -f docker-compose.yml -f docker-compose.mysql.yml up -d mysql
docker compose -f docker-compose.yml -f docker-compose.mysql.yml run --rm orchestration-center python -c "from database.utils.table_creation import create_tables; from database.utils.user_store import seed_admin_if_empty; import getpass; create_tables(); seed_admin_if_empty(getpass.getpass('Initial admin password: '))"
docker compose -f docker-compose.yml -f docker-compose.mysql.yml up --build -d
```

首次初始化不替代 TLS 或启动安全预检。生产服务应使用现有 HTTPS/mTLS 配置。命名卷
`mysql-data` 在重启后保留数据；升级数据库版本前先备份。

## 验证

单元测试：`python -m pytest tests/test_mysql_backend.py tests/test_persistence_mode.py`。
真实数据库测试：配置专用临时服务器的 `ORCH_MYSQL_TEST_HOST/PORT/USER/PASSWORD`，执行
`python -m pytest tests/test_mysql_integration.py`。测试账号需有 CREATE/DROP DATABASE 权限，
每个测试只创建、删除随机生成的 `oc_test_*` 测试库，不使用本地真实库配置。
测试含真实 HTTP、HTTPS 网络接口，不只是 TestClient 或 SQL mock。不要指向生产实例；
CI 已配置独立 MySQL 8.4 服务执行。
