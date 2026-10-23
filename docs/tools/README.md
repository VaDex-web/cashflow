# Скрипты для презентации и демо

```bash
# 1. Выписка героя демо «по дату» (из data/raw, в git не попадает)
python scripts/make_demo_statement.py C124 2025-09-16

# 2. Скриншоты шагов демо (нужны запущенные api :8000 и web :5173)
npm i playwright && npx playwright install chromium
node docs/tools/shoot_story.mjs http://localhost:5173 data/demo/C124_по_2025-09-16.csv docs/screens

# 3. Сборка docs/presentation.pptx (скриншоты из docs/screens, схема docs/architecture_slide.png)
npm i pptxgenjs sharp react react-dom react-icons
PPTX_SKILL=<папка со scripts/apply_theme.js> node docs/tools/build_presentation.js .
```

Цифры на слайдах (константы `Q`, `SRC_*` в начале скрипта) перепроверены запуском 24.10.2026:
`python -m cashflow_core.evaluate data/raw --ids <holdout из core/reports/split.json> --sims 500 --origins 8 --step 21`
и `python -m api.reports.sources_effect --part A`. История C124 — `docs/demo_story.md`.
