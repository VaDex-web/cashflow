# api/ — сервер «Денежный прогноз» (FastAPI)

Принимает выписки, строит прогноз остатка и риски кассовых разрывов (ядро `cashflow_core`), сценарии «что если»,
план-факт, принимает данные из источников (налоговый календарь, 1С, договоры, счета, банк, открытые реестры,
ручной ввод), защищён JWT. Контракт — [`docs/contract.md`](../docs/contract.md), схемы ответов совпадают с ним
(`api/schemas.py`), документация OpenAPI — http://localhost:8000/docs.

## Запуск

```bash
# из корня репозитория
pip install -r api/requirements.txt
pip install -e core                       # ядро (или export CORE_PATH=путь/к/core)
uvicorn api.main:app --reload --port 8000 # http://localhost:8000/docs
```

Интерфейс: `cd web && VITE_USE_MOCK=false npm run dev` — Vite проксирует `/api` на :8000 (CORS для :5173 тоже открыт).
Вход по умолчанию — `demo` / `demo`.

| переменная | по умолчанию | что |
|---|---|---|
| `USE_STUB_CORE` | `false` | `true` — ядро-заглушка (ответы из `docs/mock/*.json`, та же сигнатура), `false` — настоящий `cashflow_core`; если ядро не импортируется, включается заглушка и пишется предупреждение в лог |
| `CORE_PATH` | `core/` | где лежит пакет `cashflow_core` |
| `API_USERS` | `demo:demo` | пользователи `логин:пароль,…` (создаются при старте, пароли — PBKDF2-хэши) |
| `JWT_SECRET` | генерируется в `api/data/.jwt_secret` | секрет подписи токенов; `JWT_TTL_MINUTES` — срок жизни (720) |
| `DATABASE_URL` | `sqlite:///api/data/cashflow.db` | хранилище (SQLAlchemy) |
| `MAX_UPLOAD_MB` | `20` | лимит размера файла (413 с понятным текстом) |
| `REGISTRY_DELAY_DAYS` | `14` | на сколько сдвигать в прогнозе оплаты проблемного контрагента |
| `CORE_N_SIMS` | `2000` | траекторий Monte Carlo в ядре |
| `RAW_DATA_DIR`, `SYNTHETIC_DIR` | `data/raw`, `data/synthetic` | датасет организаторов и демо-данные |

## Эндпоинты

Префикс `/api`, все кроме `/health` и `/auth/login` — с `Authorization: Bearer <token>`. Ошибки — `{"detail": "текст на русском"}`.

| метод | путь | что |
|---|---|---|
| POST | `/auth/login` | `{username, password}` → `{access_token, token_type}` |
| GET | `/health` | `{status: "ok", core: "cashflow_core 0.1.0"}` |
| POST | `/companies` | multipart `file` (CSV) → `{company_id, rows, warnings}`; `?company=C009` — выбрать компанию из `all_operations.csv` |
| GET | `/companies` | компании датасета (`data/raw/companies.csv`), демо (`data/synthetic/companies.csv`) и загруженные пользователем |
| GET | `/companies/{id}/forecast?horizon=30` | `ForecastResult` (горизонт 7–365) |
| GET | `/companies/{id}/alerts` · `/recurring` · `/categories` | риски · регулярные платежи · категории (`?limit=` — последних операций) |
| GET · POST | `/companies/{id}/events` | `Event[]` · добавить событие (ручной ввод) |
| GET · PATCH · PUT · DELETE | `/companies/{id}/events/{event_id}` | CRUD события (перенос даты, статус — после ручного изменения синхронизация его не перетирает) |
| POST | `/companies/{id}/events/parse?save=true` | `{text: "клиент обещал заплатить 300 000 ₽ 20-го"}` → черновик события и «как поняли» |
| POST | `/companies/{id}/scenarios/run` | `Scenario` → `ScenarioResult` (диапазоны параметров — по контракту) |
| GET | `/companies/{id}/plan-fact?weeks=8&period=week\|day` | `PlanFact`; просрочки помечаются, прогноз пересчитывается |
| POST | `/companies/{id}/transactions` | новые строки выписки → `ForecastResult` через `update_forecast` (без полного пересчёта) |
| POST | `/companies/{id}/integrations/{name}/sync` | `bank` · `1c` · `tax_calendar` · `registry` · `contracts` · `invoices` → `{name, status, events_added, synced_at, events_updated, message}` |
| POST | `/companies/{id}/integrations/{name}/upload` | загрузить файл источника (`1c`, `contracts`, `invoices`, `bank`, `registry`) и синхронизировать |
| GET | `/companies/{id}/integrations` | источники, их состояние и число событий |
| GET | `/companies/{id}/counterparties/checks` | проверка контрагентов по открытым реестрам |

Компании `C001…C150` (датасет) и `S01…S05` (демо) доступны без загрузки — выписка читается из файла при первом
обращении. Загруженные компании видит только владелец (403 для остальных).

## Источники данных (`api/integrations/`)

Единый интерфейс — `Integration.fetch(company: CompanyContext) -> list[Event]`; у каждого события есть `source`
(показывается пользователю). Повторная синхронизация обновляет события (детерминированные `id`), одно и то же
событие из двух источников (ведомость в 1С и в зарплатном проекте банка) не дублируется.

| name | `source` | что даёт | откуда |
|---|---|---|---|
| `tax_calendar` | `tax_calendar` | ЕНП до 28-го (НДФЛ и взносы), авансы УСН 28.04/28.07/28.10 и годовой, НДС тремя частями после квартала, налог на прибыль, ЕСХН; срок на выходной — на следующий рабочий день | режим — `company.settings.tax_regime` или оценка по выписке (`estimate_tax_regime` ядра); суммы — по выручке, НДС из назначений, медиане ЕНП |
| `1c` | `1c` | счета покупателям и от поставщиков, договоры с графиком, зарплатные ведомости | JSON-выгрузка (формат — `api/integrations/onec.py`, пример — `data/synthetic/integrations/S02/1c_export.json`) |
| `contracts` | `manual` | договоры: сумма, график, предоплата %, отсрочка, абонентские платежи | JSON/CSV (формат — `contracts.py`) |
| `invoices` | `manual` | счета: сумма, дата, срок оплаты/отсрочка, оплачено; просроченные → `overdue` | CSV/JSON (формат — `invoices.py`) |
| `bank` | `bank` | графики кредитов, ведомости зарплатного проекта, созданные и подписанные платёжные поручения | `bank.json`; без файла — мок: график кредитов и лизинга по истории счёта |
| `registry` | `open_registry` | статус контрагента (ЕГРЮЛ), банкротство, долг по налогам, арбитраж, ФССП → уровень риска; этапы госконтрактов | `registry.json`; без файла — детерминированный мок по ИНН |
| `manual` | `manual` | ручной ввод формой и фразой | `POST /events`, `/events/parse` |

**Как реестр влияет на прогноз.** Контрагент с высоким риском помечается в `note` его событий («⚠ Риск задержки
оплаты: долг по налогам …»), а прогноз строится со сценарием ядра `client_delay` на `REGISTRY_DELAY_DAYS`:
все ожидаемые поступления от него (регулярные и события) сдвигаются, причина — в `warnings`. В событиях для ядра
есть поля `risk` и `delay_probability`.

Тестовые данные источников для демо-компаний — `data/synthetic/integrations/<id>/`; для загруженной копии
(`s02-xxxxxx`) берутся данные исходной компании. Отчёт о вкладе источников — [`reports/sources_effect.md`](reports/sources_effect.md).

## План-факт (`api/plan_fact.py`)

1. Сверка событий с выпиской: окно поиска и допуск суммы зависят от типа (налог — по назначению и ±50%,
   зарплата — по назначению, ±15%, счета/договоры — по контрагенту/ИНН, оплата до 45 дней позже срока, частичная
   оплата учитывается). Найдена оплата → `paid` (дата и сумма факта); срок прошёл, оплаты нет → `overdue`.
2. План по неделям = события + регулярные платежи ядра, не закрытые событиями (месячные — то же число с переносом
   выходных) + «фон» (обычный поток за 12 недель до окна). Факт — операции выписки.
3. Отклонения на русском: «АО «ДонТрансЛогистика» не оплатил счёт №205 на 2 322 000 ₽ (ожидали 22 октября)»,
   опоздание оплаты, частичная оплата, регулярное поступление не пришло, внеплановое крупное списание,
   поступления ниже / списания выше плана.
4. Новая просрочка → прогноз пересчитывается, риск проверяется заново, итог («риск разрыва 5 ноября — 91% (было 42%)»)
   попадает в `warnings` прогноза.

## Безопасность

* JWT (HS256) на всех эндпоинтах, кроме `/health` и `/auth/login`; пароли — PBKDF2-SHA256; одинаковое время ответа
  для неизвестного логина и неверного пароля.
* Изоляция: загруженную компанию видит только её владелец.
* Логи без чувствительных данных (`api/logging_setup.py`): фильтр на всех логгерах маскирует ИНН, суммы,
  наименования в «…» и e-mail; access-лог — только метод, путь без query, код и время; тела запросов не пишутся.
* Лимит размера загрузки, проверка формата до разбора.

## Хранилище

SQLite (SQLAlchemy): `companies`, `transactions`, `events` (статус, факт оплаты, источник), `counterparty_checks`,
`documents` (загруженные файлы источников), `integration_runs`, `forecast_states` (сериализованное состояние ядра —
для `update_forecast` без полного пересчёта и быстрого старта после перезапуска; ключ — версия операций + хэш событий).
При изменении событий состояние пересобирается с уже обученным категоризатором (~2 с), прогноз по готовому состоянию — ~0,05 с.

## Тесты и отчёты

```bash
CORE_PATH=core python -m pytest api/tests -q              # 36 тестов, ~15 с (без ядра тесты на настоящем ядре пропускаются)
CORE_PATH=core python -m api.reports.sources_effect       # отчёт о вкладе источников (~20 мин на 4 ядрах)
CORE_PATH=core python -m api.reports.demo_candidates      # компании датасета с разрывом через 7–21 день → reports/demo_candidates.md
python data/synthetic/generate.py                         # демо-данные
```

## Демо (S02 — B2B-услуги, разрыв через 13 дней)

```bash
T=$(curl -s localhost:8000/api/auth/login -H 'Content-Type: application/json' -d '{"username":"demo","password":"demo"}' | python -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
H="Authorization: Bearer $T"
curl -s -H "$H" localhost:8000/api/companies/S02/alerts                       # по выписке: 5 ноября, ~15%
for s in tax_calendar 1c bank registry; do curl -s -X POST -H "$H" localhost:8000/api/companies/S02/integrations/$s/sync; done
curl -s -H "$H" localhost:8000/api/companies/S02/alerts                       # с источниками: 5 ноября, ~90%
curl -s -H "$H" localhost:8000/api/companies/S02/plan-fact                    # счёт №205 просрочен
```

Подробно — [`data/synthetic/demo_scenario.md`](../data/synthetic/demo_scenario.md).

## Известные ограничения ядра (для `core/`)

Найдены при проверке источников (`reports/sources_effect.md`):

1. **Перенос оплаты регулярного клиента дальше чем на 7 дней.** Ручной ввод «клиент обещал 16-го» для клиента,
   который платит ~26-го: ядро v0.1 оставляет и регулярный платёж, и событие — деньги учитываются дважды
   (`engine.build_plan`, окно сопоставления ±7 дней). Для открытых реестров API обходит это сценарием `client_delay`.
2. **События от клиентов без регулярного паттерна.** Известные из 1С/счетов поступления добавляются сверх
   остаточного ряда выручки, где эти клиенты уже есть, — на реальных выписках имитация 1С поэтому ухудшает MAE.
   Нужно вычитать долю контрагента из остаточного потока, когда по нему есть события.
3. `update_forecast` не помечает событие оплаченным, если операция уже сопоставлена с регулярным платежом
   (API досверяет статусы сам — `plan_fact.reconcile`).
4. Сценарий `client_delay` — один контрагент за раз, поэтому поправка реестров применяется к одному, самому крупному
   проблемному клиенту, а в `/scenarios/run` не совмещается со сценарием пользователя (об этом есть `warnings`).
