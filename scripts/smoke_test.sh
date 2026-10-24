#!/usr/bin/env bash
set -euo pipefail

BASE="${1:?укажите адрес, например https://203.0.113.10.sslip.io}"
BASE="${BASE%/}"
MAX_SECS="${MAX_SECS:-3}"
CURL=(curl -sS --max-time 30)
[[ "${INSECURE:-0}" == "1" ]] && CURL+=(-k)

fail() { echo "✗ $*" >&2; exit 1; }
ok() { echo "✓ $*"; }
json() { python3 -c "import json,sys; d=json.load(sys.stdin); print($1)"; }

code=$("${CURL[@]}" -o /tmp/smoke_index.html -w '%{http_code}' "$BASE/") || fail "сайт недоступен или сертификат HTTPS недействителен: $BASE$( [[ "$BASE" == *localhost* && "${INSECURE:-0}" != "1" ]] && echo " (локально сертификат самоподписанный — запустите с INSECURE=1)")"
[[ "$code" == "200" ]] || fail "главная страница: HTTP $code"
grep -q '<div id="root">' /tmp/smoke_index.html || fail "главная страница отдала не интерфейс"
ok "главная страница по HTTPS"

read -r code t < <("${CURL[@]}" -o /tmp/smoke_health.json -w '%{http_code} %{time_total}\n' "$BASE/api/health")
[[ "$code" == "200" ]] || fail "/api/health: HTTP $code"
core=$(json 'd.get("core","")' < /tmp/smoke_health.json)
[[ "$core" == cashflow_core* ]] || fail "/api/health: ядро «$core» — ожидалось настоящее cashflow_core"
ok "/api/health за ${t}s, ядро: $core"

read -r code t < <("${CURL[@]}" -X POST -o /tmp/smoke_demo.json -w '%{http_code} %{time_total}\n' "$BASE/api/auth/demo")
[[ "$code" == "200" ]] || fail "демо-вход: HTTP $code $(cat /tmp/smoke_demo.json)"
token=$(json 'd["access_token"]' < /tmp/smoke_demo.json)
python3 -c "import sys; sys.exit(0 if float('$t') <= $MAX_SECS else 1)" || fail "демо-вход дольше ${MAX_SECS}s: ${t}s"
ok "демо-вход за ${t}s"

company=$("${CURL[@]}" -H "Authorization: Bearer $token" "$BASE/api/me" | json 'd["company_id"]')
[[ -n "$company" ]] || fail "у демо-пользователя нет компании"

read -r code t < <("${CURL[@]}" -H "Authorization: Bearer $token" -o /tmp/smoke_fc.json -w '%{http_code} %{time_total}\n' \
  "$BASE/api/companies/$company/forecast?horizon=30")
[[ "$code" == "200" ]] || fail "прогноз: HTTP $code"
python3 -c "import sys; sys.exit(0 if float('$t') <= $MAX_SECS else 1)" || fail "прогноз дольше ${MAX_SECS}s: ${t}s"
summary=$(json '"дней %d, рисков %d, первый риск: %s" % (len(d["daily"]), len(d["risks"]), (d["risks"][0]["date"] + ", вероятность " + str(round(d["risks"][0]["probability"]*100)) + "%") if d["risks"] else "нет")' < /tmp/smoke_fc.json)
days=$(json 'len(d["daily"])' < /tmp/smoke_fc.json)
[[ "$days" -ge 30 ]] || fail "прогноз короче 30 дней: $days"
ok "прогноз $company за ${t}s ($summary)"

code=$("${CURL[@]}" -o /dev/null -w '%{http_code}' "$BASE/api/companies/$company/forecast")
[[ "$code" == "401" ]] || fail "прогноз без входа должен давать 401, а дал $code"
ok "без входа данные закрыты (401)"

echo "Готово: $BASE работает."
