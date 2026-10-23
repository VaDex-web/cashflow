"""Генератор согласованных mock-ответов по docs/contract.md.

Запуск: python3 docs/mock/_generate.py  (пишет *.json рядом с собой)
Компания-пример: ООО «Южный Вкус» — оптовая поставка продуктов в кафе, Ростов-на-Дону.
"""
import json
import math
import random
from datetime import date, timedelta
from pathlib import Path

OUT = Path(__file__).parent
COMPANY = "demo-yuzhny-vkus"
TODAY = date(2026, 10, 23)  # последняя фактическая дата выписки
HORIZON = 30
START_BALANCE = 500_000
GENERATED_AT = "2026-10-23T18:30:00+03:00"


def d(s):
    return date.fromisoformat(s)


# Ожидаемые события (Event)
EVENTS = [
    {"id": "ev-payroll-1026", "type": "payroll", "direction": "out", "amount": 412_000, "date": "2026-10-26",
     "source": "1c", "status": "expected", "counterparty": "Сотрудники (12 чел.)", "note": "Зарплата за 2-ю половину октября"},
    {"id": "ev-tax-1028", "type": "tax", "direction": "out", "amount": 168_000, "date": "2026-10-28",
     "source": "tax_calendar", "status": "expected", "counterparty": "ФНС России", "note": "Единый налоговый платёж: НДФЛ и страховые взносы"},
    {"id": "ev-romashka-1028", "type": "contract", "direction": "in", "amount": 140_000, "date": "2026-10-28",
     "source": "1c", "status": "expected", "counterparty": "ООО «Кофейня Ромашка»", "note": "Оплата по договору поставки №47"},
    {"id": "ev-rent-1102", "type": "contract", "direction": "out", "amount": 185_000, "date": "2026-11-02",
     "source": "bank", "status": "expected", "counterparty": "ИП Карапетян А.С.", "note": "Аренда склада, ноябрь"},
    {"id": "ev-supplier-1105", "type": "invoice", "direction": "out", "amount": 465_000, "date": "2026-11-05",
     "source": "1c", "status": "expected", "counterparty": "ООО «Агрокомплекс Дон»", "note": "Счёт №1182 за овощи и молочку"},
    {"id": "ev-loan-1106", "type": "loan", "direction": "out", "amount": 96_500, "date": "2026-11-06",
     "source": "bank", "status": "expected", "counterparty": "Банк Центр-Инвест", "note": "Платёж по кредиту на оборудование"},
    {"id": "ev-payroll-1110", "type": "payroll", "direction": "out", "amount": 168_000, "date": "2026-11-10",
     "source": "1c", "status": "expected", "counterparty": "Сотрудники (12 чел.)", "note": "Аванс за ноябрь"},
    {"id": "ev-gorodok-1109", "type": "invoice", "direction": "in", "amount": 720_000, "date": "2026-11-09",
     "source": "1c", "status": "expected", "counterparty": "ООО «Ресторанный двор Городок»", "note": "Оплата счёта №318"},
    {"id": "ev-registry-1116", "type": "contract", "direction": "in", "amount": 260_000, "date": "2026-11-16",
     "source": "open_registry", "status": "expected", "counterparty": "МБОУ СОШ №52", "note": "Госконтракт на питание (zakupki.gov.ru), этап 2"},
    {"id": "ev-manual-1118", "type": "manual", "direction": "out", "amount": 120_000, "date": "2026-11-18",
     "source": "manual", "status": "expected", "counterparty": "ООО «ХолодТехСервис»", "note": "Ремонт холодильной камеры — договорились устно"},
    {"id": "ev-supplier-1120", "type": "invoice", "direction": "out", "amount": 900_000, "date": "2026-11-20",
     "source": "1c", "status": "expected", "counterparty": "ООО «Агрокомплекс Дон»", "note": "Предоплата закупки к новогоднему сезону"},
]

# Прошлые события для план-факта (часть просрочена)
PAST_EVENTS = [
    {"id": "ev-lakomka-1016", "type": "invoice", "direction": "in", "amount": 210_000, "date": "2026-10-16",
     "source": "1c", "status": "overdue", "counterparty": "ООО «Пекарня Лакомка»", "note": "Счёт №301 — не оплачен"},
    {"id": "ev-romashka-1009", "type": "contract", "direction": "in", "amount": 140_000, "date": "2026-10-09",
     "source": "1c", "status": "paid", "counterparty": "ООО «Кофейня Ромашка»", "note": "Оплата по договору №47"},
    {"id": "ev-payroll-1010", "type": "payroll", "direction": "out", "amount": 168_000, "date": "2026-10-09",
     "source": "1c", "status": "paid", "counterparty": "Сотрудники (12 чел.)", "note": "Аванс за октябрь"},
]

# Ежедневный «фон»: выручка от мелких клиентов и мелкие расходы (будни)
DAILY_IN, DAILY_OUT = 58_000, 21_000
SIGMA_DAY = 52_000  # неопределённость в день


def daily_flows(day, events, revenue_k=1.0, fixed_k=1.0):
    net = 0.0
    if day.weekday() < 5:
        net += DAILY_IN * revenue_k - DAILY_OUT
    elif day.weekday() == 5:
        net += 0.4 * DAILY_IN * revenue_k
    for e in events:
        if e["date"] == day.isoformat():
            amt = e["amount"]
            if e["direction"] == "in":
                net += amt * (revenue_k if e["type"] in ("contract", "invoice") else 1)
            else:
                net -= amt * (fixed_k if e["type"] in ("payroll", "contract", "loan") else 1)
    return net


def phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def fmt_rub(x):
    return f"{round(x / 1000) * 1000:,.0f}".replace(",", " ") + " ₽"


MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
          "сентября", "октября", "ноября", "декабря"]


def human_date(s):
    x = d(s)
    return f"{x.day} {MONTHS[x.month - 1]}"


def build_forecast(events, revenue_k=1.0, fixed_k=1.0, label=None):
    bal = START_BALANCE
    daily = []
    for t in range(1, HORIZON + 1):
        day = TODAY + timedelta(days=t)
        bal += daily_flows(day, events, revenue_k, fixed_k)
        sigma = SIGMA_DAY * math.sqrt(t) + 2_500 * t
        ev_ids = [e["id"] for e in events if e["date"] == day.isoformat()]
        row = {"date": day.isoformat(), "balance_p50": round(bal),
               "balance_low": round(bal - 1.2816 * sigma), "balance_high": round(bal + 1.2816 * sigma)}
        if ev_ids:
            row["events"] = ev_ids
        daily.append((row, sigma))

    # Эпизоды риска: подряд идущие дни с balance_low < 0
    risks, episode = [], []
    for row, sigma in daily + [(None, None)]:
        if row and row["balance_low"] < 0:
            episode.append((row, sigma))
            continue
        if episode:
            worst, s = min(episode, key=lambda x: x[0]["balance_p50"])
            p50 = worst["balance_p50"]
            prob = round(phi(-p50 / s), 2)
            shortfall = round(-p50) if p50 < 0 else round(-worst["balance_low"])
            sev = "high" if prob >= 0.6 else "medium" if prob >= 0.3 else "low"
            risks.append({"date": worst["date"], "shortfall_amount": int(round(shortfall, -3)),
                          "probability": prob, "severity": sev, "_episode": [r["date"] for r, _ in episode]})
            episode = []

    for r in risks:
        r.pop("_episode")
        dt = r["date"]
        if dt < "2026-11-05":
            r["reason"] = (f"{human_date('2026-11-02')} нужно заплатить аренду склада 185 000 ₽. После зарплаты и налогов "
                           "на счёте останется мало, и если выручка за эти дни окажется ниже обычной, денег может не хватить.")
            r["recommendations"] = [
                "Выставьте счета постоянным клиентам заранее, до 30 октября.",
                "Предложите арендодателю оплату аренды двумя частями: 2 и 10 ноября.",
            ]
        elif dt <= "2026-11-12":
            r["reason"] = (f"{human_date('2026-11-05')} нужно оплатить поставщику «Агрокомплекс Дон» 465 000 ₽, "
                           f"а {human_date('2026-11-06')} — платёж по кредиту 96 500 ₽. Крупная оплата от «Городка» "
                           f"придёт только {human_date('2026-11-09')}, поэтому несколько дней денег на счёте не хватит.")
            r["recommendations"] = [
                "Попросите «Агрокомплекс Дон» перенести оплату счёта №1182 на 10 ноября — после поступления от «Городка».",
                "Напомните «Пекарне Лакомке» о просроченном счёте №301 на 210 000 ₽ — этого хватит, чтобы закрыть большую часть нехватки.",
                "Если перенос невозможен — подключите овердрафт или кредитную линию в Центр-Инвест на 2–3 недели.",
            ]
        else:
            r["reason"] = (f"{human_date('2026-11-20')} запланирована предоплата новогодней закупки 900 000 ₽, "
                           f"а {human_date('2026-11-18')} — ремонт холодильной камеры 120 000 ₽. Если клиенты заплатят "
                           "чуть позже обычного, денег может не хватить.")
            r["recommendations"] = [
                "Разбейте предоплату закупки на две части: 20 и 27 ноября.",
                "Договоритесь с «ХолодТехСервисом» об оплате ремонта после 25 ноября.",
                "Заранее обсудите с Центр-Инвест сезонный кредит на пополнение оборотных средств.",
            ]

    return {
        "company_id": COMPANY,
        "generated_at": GENERATED_AT,
        "horizon_days": HORIZON,
        "as_of": TODAY.isoformat(),
        "current_balance": START_BALANCE,
        "daily": [row for row, _ in daily],
        "risks": risks,
        "recurring": RECURRING,
        "sources_used": SOURCES,
        "warnings": [],
    }


RECURRING = [
    {"name": "Зарплата (2-я половина месяца)", "direction": "out", "amount_avg": 405_000, "period_days": 30, "next_date": "2026-10-26", "confidence": 0.95},
    {"name": "Аванс сотрудникам", "direction": "out", "amount_avg": 166_000, "period_days": 30, "next_date": "2026-11-10", "confidence": 0.93},
    {"name": "Аренда склада — ИП Карапетян А.С.", "direction": "out", "amount_avg": 185_000, "period_days": 30, "next_date": "2026-11-02", "confidence": 0.98},
    {"name": "Единый налоговый платёж", "direction": "out", "amount_avg": 161_000, "period_days": 30, "next_date": "2026-10-28", "confidence": 0.9},
    {"name": "Кредит на оборудование — Центр-Инвест", "direction": "out", "amount_avg": 96_500, "period_days": 30, "next_date": "2026-11-06", "confidence": 0.99},
    {"name": "ООО «Кофейня Ромашка» — оплата поставок", "direction": "in", "amount_avg": 138_000, "period_days": 19, "next_date": "2026-10-28", "confidence": 0.78},
    {"name": "Связь и интернет — ПАО «Ростелеком»", "direction": "out", "amount_avg": 6_400, "period_days": 30, "next_date": "2026-11-03", "confidence": 0.88},
    {"name": "Эквайринг — поступления от розницы", "direction": "in", "amount_avg": 58_000, "period_days": 1, "next_date": "2026-10-26", "confidence": 0.72},
]

SOURCES = [
    "Банковская выписка: 184 дня операций (апрель–октябрь 2026)",
    "1С: счета и договоры (6 ожидаемых платежей)",
    "Налоговый календарь ФНС",
    "Открытые реестры: госконтракты (zakupki.gov.ru)",
    "Ручной ввод (1 событие)",
]


def transactions():
    rnd = random.Random(7)
    rows, bal = [], 1_120_000
    cps_in = [("ООО «Кофейня Ромашка»", "6164123456", "Оплата по договору поставки №47", "Выручка от клиентов"),
              ("ООО «Ресторанный двор Городок»", "6163987654", "Оплата по счёту", "Выручка от клиентов"),
              ("ПАО «Сбербанк» (эквайринг)", "7707083893", "Зачисление средств по операциям эквайринга", "Выручка от розницы")]
    cps_out = [("ООО «Агрокомплекс Дон»", "6141045678", "Оплата за товар по счёту", "Закупка товара"),
               ("ИП Карапетян А.С.", "616400112233", "Арендная плата за склад", "Аренда"),
               ("УФК по Ростовской области (ФНС)", "7727406020", "Единый налоговый платёж", "Налоги и взносы"),
               ("Зарплатный проект", "6163011391", "Перечисление заработной платы по реестру", "Зарплата"),
               ("ПАО «Ростелеком»", "7707049388", "Услуги связи", "Связь и ПО"),
               ("ООО «Лукойл-Югнефтепродукт»", "2309086820", "Топливные карты", "Транспорт и топливо"),
               ("Банк Центр-Инвест", "6163011391", "Погашение кредита и процентов", "Кредиты"),
               ("ООО «ХолодТехСервис»", "6165098765", "Обслуживание холодильного оборудования", "Ремонт и обслуживание")]
    day = TODAY - timedelta(days=27)
    while day <= TODAY:
        if day.weekday() < 6:
            for _ in range(rnd.randint(1, 3)):
                if rnd.random() < 0.45:
                    n, inn, p, c = rnd.choice(cps_in)
                    amt = rnd.choice([58_000, 61_500, 140_000, 72_300]) if "эквайринг" in n else rnd.randint(9, 30) * 10_000
                    direction = "in"
                else:
                    n, inn, p, c = rnd.choice(cps_out)
                    amt = rnd.randint(3, 60) * 1_000
                    direction = "out"
                bal += amt if direction == "in" else -amt
                rows.append({"date": day.isoformat(), "amount": amt, "direction": direction,
                             "counterparty_name": n, "counterparty_inn": inn, "purpose": p,
                             "balance_eod": bal, "category": c,
                             "category_confidence": round(rnd.uniform(0.62, 0.99), 2)})
        day += timedelta(days=1)
    # Сводим конечный остаток к START_BALANCE
    shift = START_BALANCE - rows[-1]["balance_eod"]
    for r in rows:
        r["balance_eod"] += shift
    rows.reverse()
    return rows


def categories(txs):
    summary = {}
    for t in txs:
        k = (t["category"], t["direction"])
        s = summary.setdefault(k, {"category": k[0], "direction": k[1], "total": 0, "count": 0})
        s["total"] += t["amount"]
        s["count"] += 1
    tot = {"in": 0, "out": 0}
    for s in summary.values():
        tot[s["direction"]] += s["total"]
    out = []
    for s in sorted(summary.values(), key=lambda s: (s["direction"], -s["total"])):
        s["share"] = round(s["total"] / tot[s["direction"]], 3)
        out.append(s)
    return {"summary": out, "transactions": txs}


def plan_fact():
    weeks = [("2026-09-28", 1_020_000, 1_005_000, 890_000, 902_000, []),
             ("2026-10-05", 1_180_000, 1_164_000, 1_050_000, 1_038_000, []),
             ("2026-10-12", 1_240_000, 1_018_000, 960_000, 1_012_000,
              [{"event_id": "ev-lakomka-1016", "text": "«Пекарня Лакомка» не оплатила счёт №301 на 210 000 ₽ (ожидали 16 октября)"},
               {"event_id": "manual-fuel", "text": "Расходы на топливо выше плана на 52 000 ₽"}]),
             ("2026-10-19", 980_000, 905_000, 870_000, 884_000,
              [{"event_id": "ev-gorodok-1021", "text": "«Ресторанный двор Городок» заплатил на 75 000 ₽ меньше счёта (частичная оплата)"}])]
    return [{"period": p, "planned_in": pi, "actual_in": ai, "planned_out": po, "actual_out": ao, "deviations": dv}
            for p, pi, ai, po, ao, dv in weeks]


def metrics():
    rnd = random.Random(3)
    bt, start, bal = [], date(2026, 9, 1), 900_000
    for i in range(45):
        day = start + timedelta(days=i)
        bal += rnd.randint(-90, 100) * 1_000
        pred = bal + rnd.randint(-60, 60) * 1_000
        w = 70_000 + i * 2_500
        bt.append({"date": day.isoformat(), "actual": bal, "predicted": pred, "low": pred - w, "high": pred + w})
    return {
        "_note": "MOCK — подставить реальные цифры из core/reports/metrics.json",
        "generated_at": GENERATED_AT, "dataset": "MOCK", "horizon_days": 30,
        "models": [
            {"name": "Наивная (остаток не меняется)", "mae": 0, "mape": 0, "coverage_80": 0, "gap_recall": 0, "gap_precision": 0, "is_selected": False},
            {"name": "Скользящее среднее", "mae": 0, "mape": 0, "coverage_80": 0, "gap_recall": 0, "gap_precision": 0, "is_selected": False},
            {"name": "Регулярные платежи + события + Монте-Карло", "mae": 0, "mape": 0, "coverage_80": 0, "gap_recall": 0, "gap_precision": 0, "is_selected": True},
        ],
        "backtest": bt,
    }


def scenario():
    base = build_forecast(EVENTS)
    sc = build_forecast(EVENTS, revenue_k=0.7)
    gaps = [r for r in sc["daily"] if r["balance_p50"] < 0]
    return {
        "base": base,
        "scenario": sc,
        "delta": {"first_gap_date": gaps[0]["date"] if gaps else None,
                  "max_shortfall": int(round(-min(r["balance_p50"] for r in sc["daily"]), -3)) if gaps else 0},
    }, {"type": "revenue_drop", "params": {"percent": 30}}


def dump(name, obj):
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    fc = build_forecast(EVENTS)
    dump("forecast.json", fc)
    dump("alerts.json", fc["risks"])
    low = dict(fc, warnings=["Данных мало: выписка всего за 41 день. Прогноз приблизительный — загрузите выписку хотя бы за 3 месяца.",
                             "Не найдено регулярных поступлений от клиентов — прогноз выручки построен по среднему."],
               sources_used=["Банковская выписка: 41 день операций (сентябрь–октябрь 2026)"])
    dump("forecast_low_data.json", low)
    dump("recurring.json", RECURRING)
    dump("events.json", PAST_EVENTS + EVENTS)
    dump("categories.json", categories(transactions()))
    dump("plan_fact.json", plan_fact())
    sr, req = scenario()
    dump("scenario_request.json", req)
    dump("scenario_result.json", sr)
    dump("metrics.json", metrics())
    dump("login_response.json", {"access_token": "mock.jwt.token", "token_type": "bearer"})
    dump("company_created.json", {"company_id": COMPANY})
    dump("health.json", {"status": "ok"})
    dump("sync_response.json", {"name": "1c", "status": "ok", "events_added": 2, "synced_at": GENERATED_AT})
    print("risks:", json.dumps(fc["risks"], ensure_ascii=False)[:600])
    print("min p50:", min((r["balance_p50"], r["date"]) for r in fc["daily"]))
    print("scenario delta:", sr["delta"])
