// Скриншоты шагов демо (история C124 «по состоянию на 16.09.2025»):
//   python scripts/make_demo_statement.py C124 2025-09-16
//   node docs/tools/shoot_story.mjs http://localhost:5173 data/demo/C124_по_2025-09-16.csv docs/screens
import { chromium } from 'playwright'
import { mkdirSync } from 'node:fs'

const [base, csvPath, out] = process.argv.slice(2)
mkdirSync(out, { recursive: true })
const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2, locale: 'ru-RU', ignoreHTTPSErrors: true })
const page = await ctx.newPage()
const shot = async (name, opts = {}) => { await page.waitForTimeout(700); await page.screenshot({ path: `${out}/${name}.png`, ...opts }); console.log('saved', name) }
const card = async (name, hasText) => { await page.locator('section.card', { hasText }).first().screenshot({ path: `${out}/${name}.png` }); console.log('saved', name) }

// 1. Вход: демо в один клик
await page.goto(base + '/')
await page.waitForSelector('text=Посмотреть демо')
await shot('01_vhod')
await page.click('button:has-text("Посмотреть демо")')
await page.waitForSelector('text=Остаток на счёте по дням', { timeout: 60_000 })

// 2. Загрузка выписки компании «по состоянию на 16 сентября 2025»
await page.goto(base + '/upload')
await page.setInputFiles('input[type=file]', csvPath)
await shot('02_zagruzka')
await page.click('button:has-text("Построить прогноз")')
await page.waitForSelector('text=Остаток на счёте по дням', { timeout: 90_000 })

// 3. Подключаем налоговый календарь
await page.goto(base + '/events')
await page.click('.card:has-text("Налоговый календарь") button')
await page.waitForSelector('.card:has-text("Налоговый календарь") >> text=Обновлено', { timeout: 60_000 })
await shot('05_istochniki')

// 4. Главная: предупреждение и график
await page.goto(base + '/')
await page.waitForSelector('text=Остаток на счёте по дням', { timeout: 90_000 })
await shot('03_glavnaya')
await card('03_preduprezhdenie', 'ВНИМАНИЕ')
await card('04_grafik', 'Остаток на счёте по дням')
await card('04_spisok', 'Предупреждения')

// 5. Что если: клиент заплатит позже
await page.goto(base + '/scenarios')
await page.waitForSelector('select')
await page.waitForTimeout(800)
const opt = await page.locator('select option', { hasText: 'Ритейл-381' }).first().getAttribute('value')
if (opt) await page.selectOption('select', opt)
await page.click('button:has-text("Показать")')
await page.waitForSelector('text=РЕЗУЛЬТАТ', { timeout: 60_000 })
await card('06_chto_esli', 'РЕЗУЛЬТАТ')

// 6. План-факт
await page.goto(base + '/plan-fact')
await page.waitForSelector('text=По неделям')
await shot('07_plan_fakt', { fullPage: true })

// 7. Операции и категории
await page.goto(base + '/operations')
await page.waitForSelector('text=Регулярные платежи')
await page.waitForTimeout(1500)
await shot('08_operacii')

// 8. Качество прогноза
await page.goto(base + '/quality')
await page.waitForSelector('text=Сравнение подходов')
await shot('09_kachestvo', { fullPage: true })

// 9. Телефон
const m = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true, locale: 'ru-RU', ignoreHTTPSErrors: true })
const mp = await m.newPage()
await mp.goto(base + '/')
await mp.click('button:has-text("Посмотреть демо")')
await mp.waitForSelector('text=Остаток на счёте по дням', { timeout: 60_000 })
await mp.goto(base + '/upload')
await mp.setInputFiles('input[type=file]', csvPath)
await mp.click('button:has-text("Построить прогноз")')
await mp.waitForSelector('text=Остаток на счёте по дням', { timeout: 90_000 })
await mp.goto(base + '/events')
await mp.click('.card:has-text("Налоговый календарь") button')
await mp.waitForSelector('.card:has-text("Налоговый календарь") >> text=Обновлено', { timeout: 60_000 })
await mp.goto(base + '/')
await mp.waitForSelector('text=Остаток на счёте по дням', { timeout: 90_000 })
await mp.waitForTimeout(800)
await mp.screenshot({ path: `${out}/10_telefon.png` }); console.log('saved 10_telefon')
await browser.close()
