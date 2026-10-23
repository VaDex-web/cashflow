# Mock-ответы API

Примеры JSON строго по [`docs/contract.md`](../contract.md). Компания-пример — ООО «Южный Вкус» (опт продуктов для кафе), сегодня = 23.10.2026.

| файл | эндпоинт |
|---|---|
| `login_response.json` | `POST /api/auth/login` |
| `health.json` | `GET /api/health` |
| `company_created.json` | `POST /api/companies` |
| `forecast.json` | `GET /api/companies/{id}/forecast` — разрыв 5–8 ноября, худший день 6 ноября: −270 000 ₽, 88% |
| `forecast_low_data.json` | то же, но с `warnings` (мало данных) |
| `alerts.json` | `GET /api/companies/{id}/alerts` |
| `categories.json` | `GET /api/companies/{id}/categories` |
| `recurring.json` | `GET /api/companies/{id}/recurring` |
| `events.json` | `GET /api/companies/{id}/events` (все 5 источников, есть `overdue`) |
| `scenario_request.json` → `scenario_result.json` | `POST /api/companies/{id}/scenarios/run` (выручка −30%) |
| `plan_fact.json` | `GET /api/companies/{id}/plan-fact` |
| `sync_response.json` | `POST /api/companies/{id}/integrations/{name}/sync` |
| `metrics.json` | `core/reports/metrics.json` (цифры = 0, MOCK — подставит команда ядра) |

Все файлы согласованы между собой и генерируются скриптом:

```bash
python3 docs/mock/_generate.py
```
