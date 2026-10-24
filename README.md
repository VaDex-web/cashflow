# Сервис финансового прогнозирования для малого бизнеса

Хакатон, кейс Банка Центр-Инвест. Сервис по истории банковских операций прогнозирует остаток на счёте по дням на 30+ дней вперёд, находит кассовые разрывы (дата, сумма, вероятность) и объясняет их предпринимателю простыми словами.

| папка | что |
|---|---|
| `core/` | Python-пакет `cashflow_core`: загрузка выписки, категории, регулярные платежи, налоги, прогноз, риски, сценарии, бэктест — [README](core/README.md) |
| `api/` | FastAPI: JWT, эндпоинты по контракту, интеграции-имитации, план-факт, тесты — [README](api/README.md) |
| `web/` | интерфейс: React + Vite + TypeScript + Recharts — [README](web/README.md) |
| `docs/` | [контракт](docs/contract.md), [архитектура](docs/architecture.md), [развёртывание](docs/deploy.md), [статус](docs/status.md), [отчёт проверки](docs/verification_report.md), [аудит](docs/audit.md), [история демо](docs/demo_story.md), [сценарий выступления](docs/demo_script.md), [презентация](docs/presentation.pdf), скриншоты `docs/screens/` |
| `data/raw/` | датасет организаторов — **не в git**: распаковать `cashflow_dataset_participants.zip` сюда |
| `data/synthetic/` | наши демо-данные (компании S01–S05, источники, «как было на самом деле») |
| `deploy/`, `docker-compose.yml`, `scripts/` | Caddy (HTTPS), запуск в Docker, smoke-тест, выписка «по дату» для демо |

Контракт данных между частями — [`docs/contract.md`](docs/contract.md); изменения — только после согласования с тимлидом.

## Запуск локально

Нужны Python 3.10+ и Node 20+.

```bash
# 0. датасет организаторов
mkdir -p data/raw && unzip cashflow_dataset_participants.zip -d data/raw

# 1. ядро и API (из корня репозитория)
python3 -m venv .venv && source .venv/bin/activate
pip install -r api/requirements.txt && pip install -e core
uvicorn api.main:app --port 8000          # http://localhost:8000/docs
# если `python -m cashflow_core…` пишет «No module named 'cashflow_core'» (на macOS `pip install -e`
# иногда не подхватывается) — из корня репозитория: export PYTHONPATH=core

# 2. интерфейс (в другом терминале)
cd web && npm ci && npm run dev           # http://localhost:5173 → «Посмотреть демо»
```

## Проверка

```bash
python -m pytest core/tests -q            # тесты ядра
python -m pytest api/tests -q             # тесты API (в т.ч. на настоящем ядре)

# прогноз для контрольного датасета: CSV (company_id;date;balance_forecast;balance_low;balance_high) + JSON с рисками
python -m cashflow_core.predict data/raw/all_operations.csv --horizon 30 --out predictions.csv

# качество на любом датасете в формате организаторов: rolling origin, 4 подхода, включая «остаток не изменится»;
# ошибка — по фактическому остатку, отдельно dev и holdout
python -m cashflow_core.evaluate data/raw --workers 4 --split core/reports/split.json --name raw

# имитация контрольного датасета: последние 30 дней каждой выписки — факт
python -m cashflow_core.control data/raw --workers 4 --split core/reports/split.json --name raw

# чек-поинт одной командой: шаги расчёта в консоли, прогноз и риски, Accuracy / Precision / Recall / F1 /
# MAE / MSE / Brier и матрица ошибок по бэктесту; файлы predictions.csv, predictions.json, checkpoint_metrics.json
python scripts/run_checkpoint.py data/raw/statements/C001.csv
python scripts/run_checkpoint.py data/raw --workers 8
```

Если `python -m cashflow_core…` не находит модуль, выполните из корня `export PYTHONPATH=core`.

## Публичное развёртывание (Docker + HTTPS)

```bash
cp .env.example .env        # DOMAIN=<IP>.sslip.io или свой домен, JWT_SECRET=$(openssl rand -hex 32)
docker compose up -d --build
bash scripts/smoke_test.sh https://<DOMAIN>
```

Проверка на своём компьютере: `DOMAIN=localhost` в `.env`, затем `INSECURE=1 bash scripts/smoke_test.sh https://localhost`
(Caddy выдаёт для localhost самоподписанный сертификат). Секреты (`JWT_SECRET`, пароли `API_USERS`) — только в `.env`
на сервере, в репозиторий они не попадают (`.env` в `.gitignore`).

Пошагово для чистой Ubuntu (Aeza): [`docs/deploy.md`](docs/deploy.md). Демо-вход в один клик — кнопка «Посмотреть демо»: у каждого гостя своя копия демо-компании с готовым прогнозом.
