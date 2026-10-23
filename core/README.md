# cashflow_core — ядро прогноза остатка и кассовых разрывов

Python-пакет: загрузка выписки → категории → регулярные платежи → прогноз остатка
по дням (P10/P50/P90) → риски кассового разрыва с причиной и рекомендациями →
сценарии «что если» → бэктест.

Зависимости только `numpy`, `pandas`, `scikit-learn`, `matplotlib` (тесты — `pytest`).

## Запуск

```bash
# из корня репозитория
pip install -e core            # или: export PYTHONPATH=core
python -m cashflow_core.demo data/raw/statements/C001.csv
python -m cashflow_core.demo data/raw/all_operations.csv --company C009 --horizon 45
python -m cashflow_core.demo data/raw/statements/C001.csv \
       --scenario '{"type":"client_delay","params":{"counterparty_or_event_id":"Дистрибьютор-489","weeks":3}}'
python -m cashflow_core.demo data/raw/statements/C001.csv --json /tmp/forecast.json

python -m pytest core/tests                 # 37 тестов (~1 мин)
python core/tests/run_tests.py              # то же без pytest (мини-раннер)
python -m cashflow_core.report --companies 30 --workers 4   # бэктест → core/reports/ (~20 мин)
python -m cashflow_core.report --rebuild    # пересобрать metrics.json/md/png из metrics_detail.json
```

## API (контракт)

```python
from cashflow_core import (load_statement, categorize, detect_recurring, forecast,
                           run_scenarios, update_forecast, backtest, compare_models,
                           build_state, forecast_from_state, estimate_tax_regime)

df = load_statement("data/raw/statements/C001.csv")      # DataFrame, df.attrs["warnings"]
cat = categorize(df)                                      # + category, category_label, category_confidence
rec = detect_recurring(cat)                               # [{name, direction, amount_avg, period_days, next_date, confidence}]
res = forecast(df, events=[], horizon=30)                 # ForecastResult (dict)
scn = run_scenarios(df, [], {"type": "revenue_drop", "params": {"percent": 20}})  # {base, scenario, delta}

# Для API выгоднее один раз построить состояние и переиспользовать его:
state = build_state(df, events, horizon=30, company_id="C001")   # ~4 с на 2 года истории
res = forecast_from_state(state)                                  # ~0.05 с
scn = run_scenarios(state, scenario={"type": "unplanned_expense", "params": {"amount": 500000, "date": "2026-10-15"}})
state, res = update_forecast(state, new_rows)                     # новые операции без полного пересчёта
```

Дополнительные необязательные аргументы `forecast`/`build_state`: `company_id`, `n_sims` (2000),
`seed` (42), `threshold` (порог разрыва, 0 ₽), `model` (`auto|ets|gbm|naive`), `as_of`.

### Формат ответа

`ForecastResult` строго по контракту + необязательные поля контракта `warnings`, `as_of`,
`current_balance`, `daily[].events` (id событий на дату):

```json
{
  "company_id": "C001", "generated_at": "2026-10-23T17:30:00+00:00", "horizon_days": 30,
  "as_of": "2026-09-29", "current_balance": 1723624.49,
  "daily": [{"date": "2026-09-30", "balance_p50": 1861000.0, "balance_low": 1527000.0, "balance_high": 2130000.0}],
  "risks": [{"date": "2026-10-28", "shortfall_amount": 821000.0, "probability": 0.28, "severity": "medium",
             "reason": "28 октября нужно заплатить квартальный налог (ЕНП) 505 000 ₽ и ...",
             "recommendations": ["Перенести оплату поставщику ...", "Заранее подключить овердрафт ..."]}],
  "recurring": [{"name": "Зарплата (~10-го числа)", "direction": "out", "amount_avg": 349926.82,
                 "period_days": 30, "next_date": "2026-10-09", "confidence": 0.985}],
  "sources_used": ["bank"],
  "warnings": []
}
```

* `balance_low` / `balance_high` — P10 / P90 (80% интервал) по 2000 траекториям Monte Carlo.
* `risks[].probability` — максимальная за эпизод доля траекторий с остатком < 0.
* `risks[].shortfall_amount` — P90 максимальной нехватки за эпизод среди траекторий, где разрыв случился.
* `severity`: high — p ≥ 0.6 (или p ≥ 0.4 в ближайшие 7 дней); medium — p ≥ 0.25; low — остальное (от 5%).
* Коды категорий: `revenue, payroll, rent, taxes, suppliers, utilities, loans, bank_fees, transfers, other`
  (русские названия — `cashflow_core.schema.CATEGORIES`).

`run_scenarios(...)["delta"]`: по контракту `first_gap_date` и `max_shortfall` — значения **для сценария**;
дополнительно `first_gap_date_base`, `max_shortfall_base`, `days_earlier`, `max_shortfall_change`.

## Как устроен прогноз

1. **Очистка** (`io.py`). Колонки распознаются по синонимам (`operation_date→date`,
   `payment_purpose→purpose`, «Поступление/Списание»→in/out, «Дебет/Кредит», знаковая сумма),
   ИНН читается строкой, даты в разных форматах, кодировки utf-8/cp1251, «шапка» над таблицей.
   Дубли удаляются **сверкой с остатком**: если без дубля сумма за день сходится с изменением
   `balance_eod` — это дубль выгрузки (в датасете у дублей разные `operation_id`).
   Расхождения остатка с операциями помечаются в `warnings`.
2. **Категории** (`categorize.py`): правила по назначению (после вырезания «в т.ч. НДС…»),
   затем «память контрагента», затем TF-IDF + логистическая регрессия для пустых/непонятных назначений.
3. **Регулярные платежи** (`recurring.py`): поиск «якорей» — день месяца (до двух: аванс 25-го и
   зарплата 10-го), день недели, квартал; учитывается перенос с выходных/праздников по
   производственному календарю РФ (вперёд для налогов, назад для зарплаты — выучивается из данных).
4. **Налоги** (`taxes.py`): ЕНП 28-го = ежемесячная база + квартальный всплеск, который
   прогнозируется как доля выручки прошлого квартала (доля — по тому же месяцу прошлого года).
   Режим налогообложения оценивается по данным (`estimate_tax_regime`).
5. **Остальные потоки** (`flows.py`): сезонный профиль (уровень × тип дня × «как год назад»)
   или градиентный бустинг — выбирается **по ошибкам прошлых прогнозов на этих же данных**.
6. **Monte Carlo** (`engine.py`): 2000 траекторий; шум сумм, задержки входящих платежей,
   ошибки остаточной модели берутся из реальных ошибок прошлых 30-дневных прогнозов.
   Пополнения «собственными средствами» и займы учредителя в прогноз **не** закладываются:
   прогноз показывает, сколько не хватит, если ничего не делать.
7. **Риски** (`risk.py`), **сценарии** (`scenarios.py`) — из тех же симуляций с общими случайными числами.

## Инкрементальное обновление

`update_forecast(state, new_rows)`: новые строки (список dict / DataFrame / CSV) чистятся тем же
парсером и размечаются уже обученным категоризатором; дубли отбрасываются; остаток сдвигается;
операции сопоставляются с ожидаемыми регулярными платежами и событиями (`paid`), неоплаченные
в срок события получают `overdue` и попадают в `warnings`; модели потоков не переобучаются (берут
продлённую историю как контекст). Полная перестройка — раз в 30 дней новых данных.
На C001: 26 новых операций — 0.13 с против ~4–8 с полного построения. `state.last_update` — что изменилось.

## Качество (бэктест)

`core/reports/metrics.md` — таблица для слайда и методика, `metrics.json` — формат раздела 5 контракта,
`metrics_detail.json` — все метрики, `errors.png` — ошибка по дням горизонта.
Rolling origin: на каждой отсечке модели учатся только на прошлом; сравниваются наивная,
сезонная (ETS-подобная) и гибрид; интервалы у всех строятся одинаково (по прошлым ошибкам).

## Граничные случаи

История < 14 дней — «минимальный» режим (средние потоки); < 90 дней — упрощённый (без бустинга,
шире интервалы); оба помечаются в `warnings`. Пустой/битый файл, нет колонок, нулевые суммы,
пустые назначения и ИНН, овердрафт (отрицательный старт), один крупный клиент (> 50% выручки),
новый контрагент в событиях, прекратившиеся регулярные поступления — не роняют расчёт, а дают
понятное предупреждение.

## Логи

Логгер `cashflow_core` пишет только счётчики, доли, длительности и id; фильтр дополнительно
маскирует похожие на ИНН и суммы числа.
