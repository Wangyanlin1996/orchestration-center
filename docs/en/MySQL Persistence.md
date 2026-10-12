<!-- Copyright (c) 2026 Huawei Technologies Co., Ltd. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0 -->

# MySQL persistence

Requires **MySQL 8.0.19+**; MySQL 8.4 LTS is used in integration CI. MySQL 5.7 and
MariaDB are not supported by this dialect. Install `requirements.txt` to obtain
PyMySQL and DBUtils; no additional OS client library is needed.

## Storage boundary

Set `persistence_mode=mysql` in `etc/conf/server.conf`. This selects the same
database-backed handlers as PostgreSQL: PSOP workflows, execution records and
user accounts. PreFlow, templates, solution packages, sandbox sessions and audit
files retain their existing file storage. Sessions/login tokens remain in memory
and still require a single server process. Selecting MySQL does not migrate
existing JSON/PostgreSQL data or copy demo workflows into the database.

The service creates the database if absent and creates/verifies its tables at
startup. The account needs CREATE DATABASE only when the database is missing;
for a pre-created database grant table CREATE, ALTER (legacy user migration),
SELECT, INSERT, UPDATE and DELETE. DDL is not rolled back by MySQL; this startup
routine is idempotent, not a general schema-migration system.

Tables use InnoDB, utf8mb4, case-sensitive NO PAD `utf8mb4_0900_bin` keys,
LONGTEXT for workflow/record content and DATETIME(6) stored in UTC. MySQL PSOP
IDs are limited to 255 characters, execution IDs to 64 and usernames to 64;
overlength values fail rather than silently truncate. Payloads are also bounded
by the server's `max_allowed_packet` and the existing HTTP request limits.

## Local Python service

1. Copy `etc/conf/db/mysql.json.template` to `etc/conf/db/mysql.json` and
   set the host, port, database and user. The real file is gitignored and excluded
   from Docker builds. The PostgreSQL `db/postgresql.json` is not used in MySQL mode.
2. Supply the variable named by `password_env` (default `MYSQL_PASSWORD`) through
   process environment or the root `.env`. Explicit process values override `.env`.
   `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_DATABASE`, `MYSQL_USER`, pool/timeout settings
   and `MYSQL_SSL_CA` also override the JSON file. An environment-only deployment
   needs no JSON file. A missing password variable is an error; an explicitly empty
   variable allows a passwordless disposable local instance.
   Literal password fields are rejected; use password_env only.
3. Set `persistence_mode=mysql`. For an empty SQL user store, inject `OC_ADMIN_INITIAL_PASSWORD`
   through a secret manager or set `admin_initial_password_file` to a protected file.
   Run `python -m orchestrate.start`; startup creates admin from that secret. Existing users
   are not reset and do not require the first-boot secret again.
4. Change the initial password in the web UI and log in again before obtaining an API token.
   Database credentials are independent from application accounts and TLS/mTLS.

Optional offline pre-provisioning remains supported: a trusted administrator may call
`create_tables()` and `seed_admin_if_empty(getpass.getpass(...))` before exposing the service.
This is not required for normal bootstrap. Do not bypass security preflight.

## Connection settings

| JSON key | Environment override | Default / meaning |
|---|---|---|
| `host`, `port` | `MYSQL_HOST`, `MYSQL_PORT` | `127.0.0.1`, `3306` |
| `database`, `user` | `MYSQL_DATABASE`, `MYSQL_USER` | `orchestration_center`; user required |
| `password_env` | variable named by the field | `MYSQL_PASSWORD`; required (may explicitly be empty) |
| `pool_min`, `pool_max` | `MYSQL_POOL_MIN`, `MYSQL_POOL_MAX` | `1`, `20`; per process; `0 <= min <= max`, max >= 1 |
| `connect_timeout` | `MYSQL_CONNECT_TIMEOUT` | `10` seconds (TCP connect) |
| `read_timeout`, `write_timeout` | `MYSQL_READ_TIMEOUT`, `MYSQL_WRITE_TIMEOUT` | `30` seconds each (socket operations, not a total query deadline) |
| `ssl_ca` | `MYSQL_SSL_CA` | empty: plaintext local/development connection with a warning; set a trusted CA file in production |

With a CA configured, both certificate and hostname are verified. A TLS or pool
failure never switches to PostgreSQL/file mode. Pool exhaustion fails immediately;
checkout pings idle connections. Each checkout starts a transaction, writes commit
explicitly and errors roll back; closing returns a reset connection to the pool.
The pool is closed at application shutdown. Timeout settings are not a guarantee
of a total HTTP request deadline or an automatic replay of an uncertain write.

## Containers

For an external database, pass `PERSISTENCE_MODE=mysql` and `MYSQL_*` through the
environment/secret manager; the entrypoint does not write MySQL credentials to a
config file. Mount the CA read-only and set `MYSQL_SSL_CA` for a production database.

For a disposable local database, set `MYSQL_USER`, `MYSQL_PASSWORD` and a distinct
`MYSQL_ROOT_PASSWORD` in `.env`. The optional overlay publishes no database port:

```bash
docker network create openan-net  # once, if absent
docker compose -f docker-compose.yml -f docker-compose.mysql.yml up -d mysql
docker compose -f docker-compose.yml -f docker-compose.mysql.yml run --rm orchestration-center python -c "from database.utils.table_creation import create_tables; from database.utils.user_store import seed_admin_if_empty; import getpass; create_tables(); seed_admin_if_empty(getpass.getpass('Initial admin password: '))"
docker compose -f docker-compose.yml -f docker-compose.mysql.yml up --build -d
```

The first-boot command does not replace TLS or the existing startup security
preflight. Production endpoints should use the existing HTTPS/mTLS setup. The
named `mysql-data` volume survives restarts. Back it up before changing versions.

## Validation

Unit tests: `python -m pytest tests/test_mysql_backend.py tests/test_persistence_mode.py`.
Live tests require an explicitly disposable server configured by
`ORCH_MYSQL_TEST_HOST`, `ORCH_MYSQL_TEST_PORT`, `ORCH_MYSQL_TEST_USER` and
`ORCH_MYSQL_TEST_PASSWORD`; run `python -m pytest tests/test_mysql_integration.py`.
The account needs CREATE/DROP DATABASE for randomly named `oc_test_*` schemas.
These tests include real HTTP and HTTPS requests, not only TestClient/mocked SQL.
Do not use a production server. CI runs them against a dedicated MySQL 8.4 service.
