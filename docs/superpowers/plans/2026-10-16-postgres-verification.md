# PostgreSQL 上線驗證 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal：** 實際讓 PredictFix 跑在 PostgreSQL 17 上並通過既有情境、容器重啟與備份還原驗證，補上 README「PostgreSQL 尚未實測」的缺口。

**Architecture：** 驗證分兩層。程式內層讓既有 `tests/*_scenario.py` 以子程序連到用完即丟的 PostgreSQL 資料庫；容器層用 Compose 啟動正式模式的「API 映像＋PostgreSQL」，跑 `check_container.py`、重啟保存與 `pg_dump`／`pg_restore`。兩層都放在 `scripts/verify_postgres.py`，不進 pytest。

**Tech Stack：** Python 3.12、SQLAlchemy 2.1、psycopg 3.3.6、PostgreSQL 17（`postgres:17-alpine`）、Docker Compose、GitHub Actions。

**Spec：** `docs/superpowers/specs/2026-10-16-machine-scan-and-postgres-design.md`（第 4 節）

## Global Constraints

- 在新分支 `feat/postgres-and-machine-scan` 上工作，不直接 commit 到 `main`。
- PostgreSQL 版本固定 `postgres:17-alpine`；連線字串格式 `postgresql+psycopg://`。
- `pg_dump`、`pg_restore`、`createdb`、`psql` 一律在 PostgreSQL 17 容器內執行，不依賴本機或 runner 的 client。
- 備份檔一律用 `docker compose cp` 複製出容器，不用 stdout 重導向（Windows PowerShell 會破壞 binary）。
- 密碼不寫進程式碼或檔案：驗證用密碼在執行時以 `secrets.token_urlsafe(24)` 產生並只透過環境變數傳遞；CI 的 PostgreSQL service 用 `POSTGRES_HOST_AUTH_METHOD: trust`。
- 驗證腳本只接受 `127.0.0.1`／`localhost` 的連線目標，避免誤連真實資料庫。
- pytest 仍全部使用 SQLite，必須維持全部通過、零跳過。
- 新檔案縮排 2 個空白；修改既有檔案時沿用該檔案的縮排。註解用正體中文，只說明「為什麼」。
- `backend/openai_runtime.py` 的本機 sqlite 快取不屬於主資料庫，不修改。
- `scripts/verify_postgres.py` 與 `scripts/backup_database.py` 在模組層級不可 import `backend`：`backend.store` 一被匯入就固定 `DATABASE_URL`，會污染同一個 pytest 程序裡 `tests/test_api.py` 的隔離資料庫。

## Review Focus

- Docker 沒有啟動時執行驗證腳本 → 應印出一行可理解的中文錯誤並以非 0 結束，而不是 traceback（測試：`test_docker_missing_message`）。
- 驗證中途失敗 → 暫存資料庫與 Compose 專案仍要被清除（測試：`test_cleanup_runs_on_failure`）。
- 傳入非本機的連線網址 → 拒絕執行（測試：`test_rejects_non_local_admin_url`）。
- 還原目標資料庫已存在 → 拒絕，絕不覆寫（測試：`test_restore_refuses_existing_database`）。
- 程式內情境在 PostgreSQL 上因交易／鎖定行為不同而失敗 → 由 Task 2 實跑揭露，修正後要在 SQLite 上重跑 pytest 確認沒有退化。

---

### Task 1：讓情境腳本與備份腳本能分辨資料庫種類

**Files:**
- Modify: `tests/production_scenario.py:96-108`（備份還原區塊）
- Modify: `scripts/backup_database.py`
- Test: `tests/test_backup_postgres.py`

**Interfaces:**
- Produces（`scripts/backup_database.py`）：
  - `backup_postgres(compose: list[str], destination: Path, database: str = 'predictfix', user: str = 'predictfix') -> dict` — 在 `db` 服務內 `pg_dump -Fc` 到 `/tmp`，再 `compose cp` 出來；寫入與 SQLite 版相同格式的 `.json` manifest（`created_at`、`sha256`、`bytes`、`format: 'pg_custom'`）。
  - `restore_postgres(compose: list[str], source: Path, target_database: str, user: str = 'predictfix') -> dict` — 驗證 checksum → 若 `target_database` 已存在就 `raise FileExistsError` → `createdb` → `pg_restore` → `DELETE FROM login_sessions` → 回傳 `{'restored': True, 'sessions_revoked': True, 'database': target_database}`。
  - `compose` 參數是 `docker compose` 之後、子命令之前的參數清單，例如 `['-p','pf-verify','-f','compose.production.yaml','-f','deploy/compose.verify.yaml']`。
  - CLI 新增 `--postgres`、`--compose-file`（可重複）、`--project`、`--target-database`；未加 `--postgres` 時行為與現在完全相同。
- 所有 docker 呼叫集中在 `run_compose(compose: list[str], *args: str, check: bool = True) -> subprocess.CompletedProcess`，方便測試替換。

- [ ] **Step 1：寫失敗的測試**（以 monkeypatch 替換 `run_compose`，不需要 Docker）

```python
def test_restore_refuses_existing_database(monkeypatch, tmp_path):
  # run_compose 模擬 psql 查到目標資料庫已存在
  ...
  with pytest.raises(FileExistsError):
    backup_database.restore_postgres(['-p','x'], dump, 'pf_restore_check')
  assert not any('createdb' in c for c in calls)

def test_restore_rejects_checksum_mismatch(tmp_path): ...  # 竄改 dump 後 raise RuntimeError('Backup checksum mismatch')

def test_backup_postgres_uses_container_cp(monkeypatch, tmp_path):
  ...
  assert any(c[:2]==('exec','db') and 'pg_dump' in c for c in calls)
  assert any(c[0]=='cp' for c in calls)
  assert json.loads(manifest.read_text())['format']=='pg_custom'
```

- [ ] **Step 2：執行測試確認失敗**

Run: `.venv\Scripts\python.exe -m pytest tests/test_backup_postgres.py -q`
Expected: FAIL（`backup_postgres` 不存在）

- [ ] **Step 3：實作 `backup_postgres`、`restore_postgres`、`run_compose`**

檢查資料庫是否存在用 `psql -tAc "SELECT 1 FROM pg_database WHERE datname=..."`；資料庫名稱只接受 `^[a-z][a-z0-9_]{2,62}$`，避免 SQL 注入。

- [ ] **Step 4：`production_scenario.py` 依 `store.engine.dialect.name` 分流**

SQLite 維持原本的檔案備份還原並回報 `online_backup_restore: True`；PostgreSQL 不在程式內做檔案備份，回報 `online_backup_restore: 'verified_in_container_layer'`。重啟保存與污染檢查兩種資料庫都要跑。

- [ ] **Step 5：執行測試確認通過且無退化**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: 全部 PASS，0 skipped

- [ ] **Step 6：Commit**

```bash
git add scripts/backup_database.py tests/production_scenario.py tests/test_backup_postgres.py
git commit -m "Add PostgreSQL backup and restore through the database container"
```

### Task 2：`scripts/verify_postgres.py` 兩層驗證並修正不相容處

**Files:**
- Create: `scripts/verify_postgres.py`
- Create: `deploy/compose.verify.yaml`
- Test: `tests/test_verify_postgres.py`
- Modify：實跑後發現的不相容處（預期在 `backend/` 內，數量未知）

**Interfaces:**
- Consumes：Task 1 的 `backup_postgres`、`restore_postgres`、`run_compose`。
- Produces：
  - CLI `python scripts/verify_postgres.py scenarios --admin-url postgresql+psycopg://postgres@127.0.0.1:55432/postgres`（密碼由 `PGPASSWORD` 環境變數提供）。
  - CLI `python scripts/verify_postgres.py container`（自行產生密碼、用專案名 `pf-verify`、API 對外 `127.0.0.1:18084`）。
  - 兩者成功時最後一行印出 JSON 摘要，失敗時以非 0 結束。
  - `SCENARIOS = {'dispatch_concurrency_scenario.py': 'Isolated-Test-Password-123456', 'production_scenario.py': 'Isolated-Test-Password-123456', 'repair_flow_scenario.py': 'Isolated-Flow-Password-123456'}`（這些是既有測試檔已使用的隔離測試值）。
  - `require_local(url: str) -> None`、`docker_available() -> bool`。
- `deploy/compose.verify.yaml`：只覆寫 `api` 的 `ports: ["127.0.0.1:18084:8080"]` 與 `COOKIE_SECURE: "0"`。

- [ ] **Step 1：寫失敗的測試**（不需要 Docker 或 PostgreSQL）

```python
def test_rejects_non_local_admin_url():
  with pytest.raises(SystemExit):
    verify_postgres.require_local('postgresql+psycopg://postgres@10.0.0.5:5432/postgres')

def test_docker_missing_message(monkeypatch, capsys):
  monkeypatch.setattr(verify_postgres.shutil, 'which', lambda name: None)
  assert verify_postgres.main(['container']) == 1
  assert '找不到 Docker' in capsys.readouterr().err

def test_cleanup_runs_on_failure(monkeypatch):
  # 讓第一個情境失敗，確認仍呼叫 DROP DATABASE ... WITH (FORCE)
  ...
```

- [ ] **Step 2：執行測試確認失敗**

Run: `.venv\Scripts\python.exe -m pytest tests/test_verify_postgres.py -q`
Expected: FAIL（模組不存在）

- [ ] **Step 3：實作 `scenarios` 子命令**

每個情境建立 `pf_verify_<檔名去副檔名>_<6 位 hex>` 資料庫，以子程序執行，環境為 `APP_MODE=production`、`DEMO_MODE=0`、`OLLAMA_MODEL=''`、`LOCAL_LLM_MODEL=''`、對應的 `BOOTSTRAP_PASSWORD`、`DATABASE_URL` 指向該資料庫；`finally` 中 `DROP DATABASE ... WITH (FORCE)`。

- [ ] **Step 4：實作 `container` 子命令**

順序：產生 `POSTGRES_PASSWORD`、`BOOTSTRAP_PASSWORD` 並組出 `DATABASE_URL=postgresql+psycopg://predictfix:<pw>@db/predictfix`，設定 `APP_DOMAIN=verify.localhost`（只為滿足 compose 的必填檢查，不啟動 proxy）→ `up -d --build db api` → `check_container.py --url http://127.0.0.1:18084` → 以 HTTP 登入 supervisor 並建立設備 `VERIFY-01` → `restart db api` → 等 `/healthz` → 確認 `VERIFY-01` 仍在 → `backup_postgres` → `restore_postgres(..., 'pf_restore_check')` → 用 `psql` 確認還原庫 `machines` 有 1 筆、`login_sessions` 為 0 → `finally` 執行 `down -v`。

- [ ] **Step 5：執行單元測試確認通過**

Run: `.venv\Scripts\python.exe -m pytest tests/test_verify_postgres.py -q`
Expected: PASS

- [ ] **Step 6：本機實跑兩層驗證**

```powershell
docker run --rm -d --name pf-verify-pg -p 127.0.0.1:55432:5432 -e POSTGRES_PASSWORD=$env:PGPASSWORD postgres:17-alpine
.venv\Scripts\python.exe scripts/verify_postgres.py scenarios --admin-url postgresql+psycopg://postgres@127.0.0.1:55432/postgres
.venv\Scripts\python.exe scripts/verify_postgres.py container
docker stop pf-verify-pg
```

Expected：兩個子命令最後一行皆為 JSON 且所有值為真。執行前先在 PowerShell 設定 `$env:PGPASSWORD` 為隨機值。

- [ ] **Step 7：修正實跑揭露的不相容處，再重跑 Step 6 與完整 pytest**

每個修正都要附上「哪個情境、什麼錯誤」寫進 commit 訊息。
Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: 全部 PASS，0 skipped

- [ ] **Step 8：Commit**

```bash
git add scripts/verify_postgres.py deploy/compose.verify.yaml tests/test_verify_postgres.py backend
git commit -m "Verify scenarios, restart persistence and backups on PostgreSQL 17"
```

### Task 3：CI job 與文件更新

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `README.md`（第 22、83、133、167、263 行附近的 PostgreSQL 敘述與驗證方式段落）
- Modify: `docs/production-setup.md:52-65`

**Interfaces:**
- Consumes：Task 2 的兩個 CLI 子命令。

- [ ] **Step 1：新增 CI job `postgres`**

`services.postgres`：`image: postgres:17-alpine`、`env: POSTGRES_HOST_AUTH_METHOD: trust`、`ports: ['5432:5432']`、health check `pg_isready`。步驟：checkout → setup-python 3.12 → `pip install -r requirements.txt` → `python scripts/verify_postgres.py scenarios --admin-url postgresql+psycopg://postgres@127.0.0.1:5432/postgres` → `python scripts/verify_postgres.py container`。`timeout-minutes: 20`。

- [ ] **Step 2：本機用 YAML 解析確認語法**

Run: `.venv\Scripts\python.exe -c "import yaml,sys;yaml.safe_load(open('.github/workflows/ci.yml',encoding='utf-8'))"`（若 venv 無 PyYAML，改為 `docker run --rm -v ${PWD}:/w -w /w python:3.12-slim sh -c "pip -q install pyyaml && python -c \"import yaml;yaml.safe_load(open('.github/workflows/ci.yml'))\""`）
Expected：無錯誤輸出

- [ ] **Step 3：更新 README 與 production-setup**

把「PostgreSQL 尚未實測」改成實測日期與實際驗證項目（三個情境、容器重啟保存、`pg_dump`／`pg_restore` 到新資料庫並撤銷 session）；HTTPS／Caddy 仍維持「尚未實測」。新增「如何自行驗證 PostgreSQL」的指令段落（Task 2 Step 6 的指令）。

- [ ] **Step 4：Commit**

```bash
git add .github/workflows/ci.yml README.md docs/production-setup.md
git commit -m "Run PostgreSQL verification in CI and document the verified path"
```
