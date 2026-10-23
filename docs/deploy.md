# Развёртывание на VPS (Aeza, Ubuntu 22.04/24.04, Docker)

Итог: сайт по HTTPS на вашем домене или на `<IP>.sslip.io`, демо-вход в один клик, автоматический перезапуск после перезагрузки сервера.

Что запускается (`docker-compose.yml`):

| сервис | что делает | наружу |
|---|---|---|
| `web` | Caddy: раздаёт собранный интерфейс, проксирует `/api` в API, сам получает и продлевает сертификат Let's Encrypt | 80, 443 |
| `api` | FastAPI + ядро `cashflow_core`, база SQLite в томе `api_data`; при старте готовит демо-компанию и её прогноз | — (только внутри) |

Секреты (JWT, пароли) — **только в `.env` на сервере**, в репозитории их нет.

## 1. Сервер и домен

1. Создайте VPS в панели Aeza: Ubuntu 24.04, от 2 vCPU и 2 ГБ RAM (прогноз считается на сервере; 4 ГБ — с запасом). Запишите публичный IP, например `203.0.113.10`.
2. Домен — один из вариантов:
   * **без своего домена:** `203.0.113.10.sslip.io` — такое имя само указывает на ваш IP, сертификат выдаётся автоматически;
   * **свой домен:** A-запись `cashflow.example.ru → 203.0.113.10`, подождите, пока запись начнёт отвечать (`dig +short cashflow.example.ru`).
3. Подключитесь: `ssh root@203.0.113.10` (ключ или пароль из панели Aeza).

## 2. Docker и firewall

```bash
apt-get update && apt-get -y upgrade
apt-get install -y ca-certificates curl git ufw python3

# Docker Engine + Compose plugin (официальный скрипт)
curl -fsSL https://get.docker.com | sh
systemctl enable --now docker            # Docker стартует после перезагрузки сервера
docker compose version                   # проверка

# firewall: только SSH и веб
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp                        # HTTP/3
ufw --force enable
ufw status
```

> Docker публикует порты 80/443 в обход ufw — это нормально: открыты ровно те порты, что указаны в `docker-compose.yml` (API наружу не публикуется).

## 3. Код и данные

```bash
mkdir -p /opt && cd /opt
git clone https://github.com/VaDex-web/cashflow.git
cd cashflow

# датасет организаторов (не в git): нужен для компаний C001…C150 в демо-режиме; для демо-входа (S02) не обязателен
mkdir -p data/raw
# scp cashflow_dataset_participants.zip root@203.0.113.10:/opt/cashflow/   — с вашего компьютера
# apt-get install -y unzip && unzip cashflow_dataset_participants.zip -d data/raw
```

Репозиторий приватный — для `git clone` нужен доступ: deploy key (`ssh-keygen -t ed25519`, публичный ключ — в GitHub → Settings → Deploy keys) или токен GitHub, введённый при клонировании. Ключи и токены в репозиторий не кладите.

## 4. Настройка `.env`

```bash
cp .env.example .env
sed -i "s|^DOMAIN=.*|DOMAIN=203.0.113.10.sslip.io|" .env          # или ваш домен
sed -i "s|^JWT_SECRET=.*|JWT_SECRET=$(openssl rand -hex 32)|" .env
chmod 600 .env
nano .env                                                          # остальное — по желанию
```

| переменная | по умолчанию | зачем |
|---|---|---|
| `DOMAIN` | — (обязательно) | имя сайта, для него Caddy получает сертификат |
| `JWT_SECRET` | — | подпись токенов; без него сгенерируется и сохранится в томе `api_data` |
| `API_USERS` | пусто | постоянные пользователи `логин:пароль[:компания]`; пусто — только демо-вход |
| `DEMO_COMPANY` / `DEMO_WARMUP` / `DEMO_TTL_HOURS` | `S02` / `true` / `24` | демо-вход: каждому гостю своя копия; прогноз готовится при старте; гости удаляются через сутки |
| `MAX_UPLOAD_MB` | `20` | лимит размера загружаемой выписки |
| `RATE_LIMIT_PER_MIN` / `RATE_LIMIT_HEAVY_PER_MIN` | `300` / `20` | запросов в минуту с одного IP: всего / вход, загрузка файлов, прогноз без входа |
| `PUBLIC_PREDICT` | `true` | `POST /api/predict` без входа (проверка на контрольном датасете) |

## 5. Запуск

```bash
docker compose up -d --build
docker compose ps                         # оба сервиса — healthy (API — через ~10–30 с после старта)
bash scripts/smoke_test.sh https://203.0.113.10.sslip.io
```

`smoke_test.sh` проверяет: HTTPS и главную страницу, `/api/health` (настоящее ядро), демо-вход, прогноз демо-компании (≥30 дней, время ответа ≤ 3 с) и что без входа данные закрыты. Выход `0` — всё работает.

Первый запуск: Caddy получает сертификат за 10–60 с; если домен ещё не указывает на сервер, сертификат не выдастся — проверьте DNS и `docker compose logs web`.

## 6. Обновление

```bash
cd /opt/cashflow
git pull
docker compose up -d --build
bash scripts/smoke_test.sh https://203.0.113.10.sslip.io
```

База (`api_data`) и сертификаты (`caddy_data`) — в томах Docker и при обновлении сохраняются.

## 7. Логи и перезапуск

```bash
docker compose logs -f api               # запросы: метод, путь, код, время — без ИНН, сумм, названий и токенов
docker compose logs -f web               # Caddy: сертификаты
docker compose restart api               # перезапуск API
docker compose down && docker compose up -d   # полный перезапуск
```

После перезагрузки сервера всё поднимается само: Docker включён в автозапуск (`systemctl enable docker`), у сервисов `restart: unless-stopped`. Проверка: `reboot`, через минуту — `bash scripts/smoke_test.sh https://…`.

## 8. Если что-то не так

| симптом | что сделать |
|---|---|
| `api` не становится healthy | `docker compose logs api` — если «Ядро cashflow_core не найдено», пересоберите: `docker compose build --no-cache api` |
| браузер ругается на сертификат | DNS ещё не обновился или закрыт порт 80 — `ufw status`, `docker compose logs web` |
| «Слишком много запросов» | сработал лимит; поднимите `RATE_LIMIT_PER_MIN` в `.env` и `docker compose up -d` |
| сбросить демо-данные | `docker compose down -v && docker compose up -d` (удалит базу и сертификаты) |
