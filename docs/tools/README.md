# Скрипты для презентации

```bash
# 1. Скриншоты интерфейса (нужны запущенные api :8000 и web с VITE_USE_MOCK=false на :5174)
npm i playwright && npx playwright install chromium
node docs/tools/shoot.mjs docs/screenshots http://localhost:5174

# 2. Сборка docs/presentation.pptx из скриншотов, docs/architecture_slide.png и цифр бэктеста
npm i pptxgenjs sharp react react-dom react-icons
PPTX_SKILL=<папка со scripts/apply_theme.js> node docs/tools/build_presentation.js .
```

Цифры на слайдах — из `core/reports/metrics.md` (holdout, 73 компании) и `api/reports/sources_effect.md` (S02).
