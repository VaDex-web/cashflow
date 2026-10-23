# Контракт проекта «Сервис финансового прогнозирования для малого бизнеса»

Единый источник правды для core/ (A), api/ (B), web/ (C).
**Любое изменение контракта — только после согласования с человеком.**
Примеры ответов: [`docs/mock/*.json`](mock/) — строго по схемам ниже.

Разделы, помеченные **[ПРЕДЛОЖЕНИЕ]**, — не из исходного ТЗ, а дополнения, которые нужны интерфейсу. Они ждут согласования; до согласования web/ трактует их как необязательные (если поля нет — не падает).

---

## 1. Формат выписки (CSV, UTF-8)

| поле | тип | описание |
|---|---|---|
| `date` | `YYYY-MM-DD` | дата операции |
| `amount` | число > 0 | сумма |
| `direction` | `"in"` / `"out"` | поступление / списание |
| `counterparty_name` | строка | контрагент |
| `counterparty_inn` | строка | ИНН контрагента |
| `purpose` | строка | назначение платежа (свободный текст) |
| `balance_eod` | число | остаток на конец дня |

Парсер терпим к: другим названиям колонок, знаковой сумме (минус = списание), пропускам, дублям.

---

## 2. Общие сущности (JSON)

### Event — ожидаемое будущее событие
```json
{
  "id": "string",
  "type": "contract | invoice | tax | loan | payroll | manual",
  "direction": "in | out",
  "amount": 0,
  "date": "YYYY-MM-DD",
  "source": "bank | 1c | tax_calendar | manual | open_registry",
  "status": "expected | paid | overdue",
  "counterparty": "string (необязательно)",
  "note": "string (необязательно)"
}
```

### Scenario
```json
{ "type": "client_delay | revenue_drop | unplanned_expense | fixed_cost_growth", "params": {} }
```
| type | params |
|---|---|
| `client_delay` | `{ "counterparty_or_event_id": "string", "weeks": 2..4 }` |
| `revenue_drop` | `{ "percent": 10..30 }` |
| `unplanned_expense` | `{ "amount": number, "date": "YYYY-MM-DD" }` |
| `fixed_cost_growth` | `{ "percent": number }` |

### ForecastResult
```json
{
  "company_id": "string",
  "generated_at": "ISO-8601 datetime",
  "horizon_days": 30,
  "daily": [ { "date": "YYYY-MM-DD", "balance_p50": 0, "balance_low": 0, "balance_high": 0 } ],
  "risks": [ {
    "date": "YYYY-MM-DD",
    "shortfall_amount": 0,
    "probability": 0.0,
    "severity": "low | medium | high",
    "reason": "простым языком",
    "recommendations": ["строка"]
  } ],
  "recurring": [ { "name": "string", "direction": "in | out", "amount_avg": 0, "period_days": 30, "next_date": "YYYY-MM-DD", "confidence": 0.0 } ],
  "sources_used": ["строка"]
}
```
- `balance_p50` — ожидаемый остаток; `balance_low` / `balance_high` — границы возможного диапазона.
- `probability` ∈ [0, 1].

**[ПРЕДЛОЖЕНИЕ] необязательные поля ForecastResult:**
- `warnings: string[]` — предупреждения о качестве данных простым языком, напр. `"Данных мало (42 дня), прогноз приблизительный"`.
- `current_balance: number`, `as_of: "YYYY-MM-DD"` — фактический остаток и дата последней операции (для карточки «сейчас на счёте»).
- `daily[].events: string[]` — id событий (Event) на эту дату, для маркеров на графике.

### ScenarioResult
```json
{
  "base": "ForecastResult",
  "scenario": "ForecastResult",
  "delta": { "first_gap_date": "YYYY-MM-DD | null", "max_shortfall": 0 }
}
```
`delta.first_gap_date` — дата первого разрыва **в сценарии**; `delta.max_shortfall` — макс. нехватка **в сценарии** (null / 0, если разрыва нет).

### PlanFact
```json
[ {
  "period": "YYYY-MM-DD (начало периода)",
  "planned_in": 0, "actual_in": 0,
  "planned_out": 0, "actual_out": 0,
  "deviations": [ { "event_id": "string", "text": "string" } ]
} ]
```

---

## 3. Интерфейс ядра (Python, core/ → вызывает api/)

```python
load_statement(path_or_df) -> DataFrame
categorize(df) -> DataFrame            # + колонки category, category_confidence
detect_recurring(df) -> list[dict]     # элементы = ForecastResult.recurring[]
forecast(df, events=[], horizon=30, scenario=None) -> ForecastResult (dict)
run_scenarios(df, events, scenario) -> ScenarioResult
update_forecast(state, new_rows) -> (state, ForecastResult)   # без полного пересчёта
backtest(df) -> dict                   # метрики
compare_models(df) -> таблица метрик
```

---

## 4. API (api/ → вызывает web/)

Префикс `/api`. Аутентификация JWT: заголовок `Authorization: Bearer <token>`.

| метод | путь | тело / параметры | ответ |
|---|---|---|---|
| POST | `/auth/login` | `{username, password}` | **[ПРЕДЛОЖЕНИЕ]** `{access_token, token_type: "bearer"}` |
| GET | `/health` | — | `{status: "ok"}` |
| POST | `/companies` | multipart, поле `file` (CSV) | `{company_id}` |
| GET | `/companies/{id}/forecast?horizon=30` | — | `ForecastResult` |
| GET | `/companies/{id}/alerts` | — | **[ПРЕДЛОЖЕНИЕ]** `ForecastResult.risks[]` |
| GET | `/companies/{id}/categories` | — | **[ПРЕДЛОЖЕНИЕ]** см. ниже |
| GET | `/companies/{id}/recurring` | — | `ForecastResult.recurring[]` |
| GET | `/companies/{id}/events` | — | `Event[]` |
| POST | `/companies/{id}/events` | `Event` без `id` | `Event` (с `id`) |
| POST | `/companies/{id}/scenarios/run` | `Scenario` | `ScenarioResult` |
| GET | `/companies/{id}/plan-fact` | — | `PlanFact` |
| POST | `/companies/{id}/integrations/{name}/sync` | name: `bank` \| `1c` \| `tax_calendar` \| `registry` | **[ПРЕДЛОЖЕНИЕ]** `{name, status: "ok", events_added: n, synced_at}` |
| POST | `/companies/{id}/transactions` | `[строки выписки]` | `ForecastResult` (через `update_forecast`) |

**[ПРЕДЛОЖЕНИЕ] ответ `/categories`:**
```json
{
  "summary": [ { "category": "Аренда", "direction": "out", "total": 0, "count": 0, "share": 0.0 } ],
  "transactions": [ {
    "date": "YYYY-MM-DD", "amount": 0, "direction": "in | out",
    "counterparty_name": "", "counterparty_inn": "", "purpose": "",
    "balance_eod": 0, "category": "", "category_confidence": 0.0
  } ]
}
```
`share` — доля категории внутри своего направления (in / out).

**[ПРЕДЛОЖЕНИЕ] ошибки:** `{"detail": "понятный текст на русском"}` с HTTP-кодом 4xx/5xx.

---

## 5. [ПРЕДЛОЖЕНИЕ] Метрики качества (`core/reports/metrics.json`)

```json
{
  "generated_at": "ISO-8601",
  "dataset": "string",
  "horizon_days": 30,
  "models": [ { "name": "string", "mae": 0, "mape": 0.0, "coverage_80": 0.0, "gap_recall": 0.0, "gap_precision": 0.0, "is_selected": false } ],
  "backtest": [ { "date": "YYYY-MM-DD", "actual": 0, "predicted": 0, "low": 0, "high": 0 } ]
}
```
- `mae` — средняя ошибка остатка, ₽; `mape` — доля (0.12 = 12%);
- `coverage_80` — доля дней, где факт попал в диапазон low–high;
- `gap_recall` / `gap_precision` — насколько хорошо находим кассовые разрывы.

---

## 6. Правила стыковки
- Пока чужая часть не готова — заглушка с ТОЧНО такой же сигнатурой и JSON-схемой; примеры в `docs/mock/`.
- Каждый работает только в своей папке: `core/` — A, `api/` + `data/synthetic/` — B, `web/` + `docs/` — C.
- Небольшие коммиты, README с командами запуска в своей папке.
