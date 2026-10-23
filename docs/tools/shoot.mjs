// Скриншоты интерфейса для презентации: node shoot.mjs <outDir> [baseUrl]
import { chromium } from 'playwright'
import { mkdirSync } from 'node:fs'

const out = process.argv[2]
const base = process.argv[3] ?? 'http://localhost:5174'
mkdirSync(out, { recursive: true })

const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2, locale: 'ru-RU' })
const page = await ctx.newPage()
const shot = async (name, opts = {}) => { await page.waitForTimeout(600); await page.screenshot({ path: `${out}/${name}.png`, ...opts }); console.log('saved', name) }
const waitIdle = async (sel, timeout = 90_000) => page.waitForSelector(sel, { timeout })

// 1. Вход
await page.goto(base + '/')
await waitIdle('text=Войти')
await shot('01_login')
await page.click('button:has-text("Войти")')

// 2. Главная
await waitIdle('text=Остаток на счёте по дням')
await shot('02_dashboard')
await shot('02_dashboard_full', { fullPage: true })
// карточка светофора крупно
const card = page.locator('section.card').first()
await card.screenshot({ path: `${out}/02_risk_card.png` }); console.log('saved 02_risk_card')
// график
const chart = page.locator('section.card', { hasText: 'Остаток на счёте по дням' })
await chart.screenshot({ path: `${out}/02_chart.png` }); console.log('saved 02_chart')

// 3. Что если: задержка крупного клиента на 3 недели
await page.goto(base + '/scenarios')
await waitIdle('button:has-text("Показать")')
await page.waitForTimeout(1500)
await page.click('button:has-text("Показать")')
await waitIdle('text=РЕЗУЛЬТАТ')
await page.locator('text=РЕЗУЛЬТАТ').scrollIntoViewIfNeeded()
await shot('03_scenario_delay')
await page.locator('section.card', { hasText: 'РЕЗУЛЬТАТ' }).screenshot({ path: `${out}/03_scenario_delay_card.png` })
// выручка −30%
await page.click('h3:has-text("Выручка упадёт")')
await page.locator('input[type=range]').fill('30')
await page.click('button:has-text("Показать")')
await waitIdle('text=РЕЗУЛЬТАТ')
await page.locator('section.card', { hasText: 'РЕЗУЛЬТАТ' }).screenshot({ path: `${out}/03_scenario_revenue_card.png` }); console.log('saved 03_scenario_revenue_card')

// 4. План-факт
await page.goto(base + '/plan-fact')
await waitIdle('text=По неделям')
await shot('04_plan_fact', { fullPage: true })

// 5. Платежи и источники
await page.goto(base + '/events')
await waitIdle('text=Ожидаемые платежи')
await page.waitForTimeout(1500)
await shot('05_events')

// 6. Операции
await page.goto(base + '/operations')
await waitIdle('text=Регулярные платежи')
await page.waitForTimeout(2000)
await shot('06_operations')

// 7. Качество
await page.goto(base + '/quality')
await waitIdle('text=Сравнение подходов')
await page.waitForTimeout(1000)
await shot('07_quality', { fullPage: true })

// 8. Загрузка выписки
await page.goto(base + '/upload')
await waitIdle('text=Перетащите сюда файл выписки')
await shot('08_upload')

// 9. Телефон
const m = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true, locale: 'ru-RU' })
const mp = await m.newPage()
await mp.goto(base + '/')
await mp.waitForSelector('text=Войти')
await mp.click('button:has-text("Войти")')
await mp.waitForSelector('text=Остаток на счёте по дням', { timeout: 90_000 })
await mp.waitForTimeout(800)
await mp.screenshot({ path: `${out}/09_mobile.png` }); console.log('saved 09_mobile')

await browser.close()
