// Сборка docs/presentation.pptx: node build.js <repoRoot>
const path = require('path')
const fs = require('fs')
const pptxgen = require('pptxgenjs')
const sharp = require('sharp')
const React = require('react')
const ReactDOMServer = require('react-dom/server')
const fa = require('react-icons/fa6')
const { applyTheme } = require(process.env.PPTX_SKILL + '/scripts/apply_theme.js')

const ROOT = process.argv[2]
const SHOTS = path.join(ROOT, 'docs/screenshots')
const OUT = path.join(ROOT, 'docs/presentation.pptx')

const THEME = {
  name: 'Денежный прогноз',
  headFontFace: 'Arial',
  bodyFontFace: 'Arial',
  colors: {
    dk1: '13241C', lt1: 'FFFFFF', dk2: '0B3D2E', lt2: 'F3F6F1',
    accent1: '8DC63F', accent2: '11553F', accent3: 'D23B3B', accent4: 'D98A00', accent5: '2F6FB3', accent6: '7A8A80',
    hlink: '11553F', folHlink: '6FA62A',
  },
}
const HEX = { green: '0B3D2E', green2: '11553F', lime: '8DC63F', limeBg: 'EEF7E1', red: 'D23B3B', redBg: 'FDECEC', amber: 'D98A00', grey: '7A8A80', text: '13241C', text2: '4B5D53', bg2: 'F3F6F1', border: 'DFE6DA' }

const pres = new pptxgen()
pres.layout = 'LAYOUT_16x9' // 10 x 5.625
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace }
pres.title = 'Денежный прогноз — прогноз остатка и кассовых разрывов для малого бизнеса'
pres.author = 'Команда «Денежный прогноз»'
const C = pres.SchemeColor

// ---------- layouts ----------
pres.defineSlideMaster({
  title: 'DARK',
  background: { color: C.text2 },
  objects: [
    { placeholder: { options: { name: 'title', type: 'title', x: 0.6, y: 1.0, w: 8.8, h: 1.85, fontSize: 38, bold: true, color: C.background1, align: 'left', valign: 'bottom', margin: 0 }, text: '' } },
    { placeholder: { options: { name: 'body', type: 'body', x: 0.6, y: 3.0, w: 8.8, h: 1.2, fontSize: 18, color: 'CFE2D6', valign: 'top', margin: 0 }, text: '' } },
  ],
})
pres.defineSlideMaster({
  title: 'CONTENT',
  background: { color: C.background1 },
  margin: [0.4, 0.5, 0.45, 0.5],
  objects: [
    { placeholder: { options: { name: 'title', type: 'title', x: 0.5, y: 0.3, w: 9.0, h: 0.7, fontSize: 26, bold: true, color: C.text2, align: 'left', valign: 'middle', margin: 0 }, text: '' } },
    { text: { text: 'Денежный прогноз · хакатон Банка Центр-Инвест', options: { x: 0.5, y: 5.25, w: 6, h: 0.25, fontSize: 9, color: C.accent6, margin: 0 } } },
  ],
  slideNumber: { x: 9.0, y: 5.25, w: 0.5, h: 0.25, fontSize: 9, color: C.accent6, align: 'right' },
})

// ---------- helpers ----------
async function icon(Comp, color = '#FFFFFF', size = 256) {
  const svg = ReactDOMServer.renderToStaticMarkup(React.createElement(Comp, { color, size }))
  const buf = await sharp(Buffer.from(svg)).png().toBuffer()
  return 'image/png;base64,' + buf.toString('base64')
}
async function iconCircle(slide, Comp, x, y, d, fill, name) {
  slide.addShape(pres.shapes.OVAL, { x, y, w: d, h: d, fill: { color: fill }, line: { type: 'none' }, objectName: name + ' circle' })
  const pad = d * 0.25
  slide.addImage({ data: await icon(Comp), x: x + pad, y: y + pad, w: d - 2 * pad, h: d - 2 * pad, objectName: name + ' icon' })
}
const meta = {}
async function dims(file) {
  if (!meta[file]) meta[file] = await sharp(path.join(SHOTS, file)).metadata()
  return meta[file]
}
/** Скриншот в тёмной рамке «экрана», вписанный в прямоугольник с сохранением пропорций */
async function screen(slide, file, box, { crop, name } = {}) {
  const m = await dims(file)
  let iw = m.width, ih = m.height
  if (crop) ih = Math.round(iw * crop) // обрезка снизу: высота = ширина × crop
  const frame = 0.08
  const maxW = box.w - 2 * frame, maxH = box.h - 2 * frame
  const k = Math.min(maxW / iw, maxH / ih)
  const w = iw * k, h = ih * k
  const x = box.x + (box.w - w) / 2, y = box.y + (box.h - h) / 2
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: x - frame, y: y - frame, w: w + 2 * frame, h: h + 2 * frame, rectRadius: 0.08,
    fill: { color: C.text2 }, line: { type: 'none' },
    shadow: { type: 'outer', color: '000000', opacity: 0.18, blur: 8, offset: 3, angle: 90 }, objectName: (name ?? file) + ' frame',
  })
  const img = { path: path.join(SHOTS, file), x, y, w, h, objectName: name ?? file }
  if (crop) { img.w = w; img.h = w * (m.height / m.width); img.sizing = { type: 'crop', x: 0, y: 0, w, h } }
  slide.addImage(img)
  return { x, y, w, h }
}
function stat(slide, x, y, w, value, label, color = C.accent2, name = label) {
  slide.addText(value, { x, y, w, h: 0.75, fontSize: 40, bold: true, color, margin: 0, isTextBox: true, objectName: name + ' value' })
  slide.addText(label, { x, y: y + 0.75, w, h: 0.6, fontSize: 12, color: C.text1, margin: 0, valign: 'top', isTextBox: true, objectName: name + ' label' })
}
function card(slide, x, y, w, h, fill = C.background2, name = 'card') {
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, rectRadius: 0.1, fill: { color: fill }, line: { type: 'none' }, objectName: name })
}
const content = (section) => pres.addSlide({ masterName: 'CONTENT', sectionTitle: section })

;(async () => {
  // 1. Титул
  pres.addSection({ title: 'Начало' })
  let s = pres.addSlide({ masterName: 'DARK', sectionTitle: 'Начало' })
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.6, y: 0.7, w: 0.62, h: 0.62, rectRadius: 0.12, fill: { color: C.accent1 }, line: { type: 'none' }, objectName: 'logo mark' })
  s.addText('₽', { x: 0.6, y: 0.7, w: 0.62, h: 0.62, fontSize: 26, bold: true, color: C.text2, align: 'center', valign: 'middle', margin: 0, isTextBox: true, objectName: 'logo glyph' })
  s.addText('Хакатон Банка Центр-Инвест', { x: 1.4, y: 0.75, w: 6, h: 0.5, fontSize: 14, color: 'A9C7B5', valign: 'middle', margin: 0, isTextBox: true, objectName: 'event' })
  s.addText('Денежный прогноз', { placeholder: 'title' })
  s.addText('Предприниматель за 10 секунд понимает: хватит ли денег в ближайший месяц, когда не хватит и что делать', { placeholder: 'body' })
  s.addNotes('Малый бизнес часто закрывается не из-за убытков, а потому что в нужный день на счёте нет денег. Наш сервис заранее говорит предпринимателю: хватит ли денег, когда не хватит и что делать.')

  // 2. Проблема
  pres.addSection({ title: 'Проблема и решение' })
  s = content('Проблема и решение')
  s.addText('Прибыльный бизнес, а платить зарплату нечем', { placeholder: 'title' })
  card(s, 0.5, 1.2, 4.3, 3.8, C.background2, 'persona card')
  await iconCircle(s, fa.FaUserTie, 0.8, 1.45, 0.6, C.accent2, 'persona')
  s.addText('ООО «Вектор Бизнес-Сервис»', { x: 1.55, y: 1.45, w: 3.1, h: 0.3, fontSize: 14, bold: true, color: C.text1, margin: 0, isTextBox: true, objectName: 'persona name' })
  s.addText('ИТ-аутсорсинг, 22 сотрудника, демо-компания S02', { x: 1.55, y: 1.75, w: 3.1, h: 0.3, fontSize: 11, color: C.accent6, margin: 0, isTextBox: true, objectName: 'persona sub' })
  s.addText([
    { text: '2,5 млн ₽ на счёте сегодня', options: { bullet: true, breakLine: true } },
    { text: '45% выручки — один клиент, и он задерживает счёт на 2,3 млн ₽', options: { bullet: true, breakLine: true } },
    { text: '28 октября — ЕНП ≈ 1,5 млн ₽, 5 ноября — зарплата 956 тыс. ₽', options: { bullet: true, breakLine: true } },
    { text: 'В выписке этого не видно — разрыв обнаружится в день платежа', options: { bullet: true } },
  ], { x: 0.8, y: 2.3, w: 3.8, h: 2.5, fontSize: 14, color: C.text1, paraSpaceAfter: 8, valign: 'top', margin: 0, isTextBox: true, objectName: 'persona facts' })
  stat(s, 5.3, 1.3, 4.2, '−544 000 ₽', 'реальный минимум остатка 5 ноября: остаток был ниже нуля с 5 по 13 ноября', C.accent3, 'real gap')
  stat(s, 5.3, 2.75, 4.2, 'за 13 дней', 'наш прогноз предупредил об этом разрыве, когда подключили 1С и открытые реестры', C.accent2, 'lead time')
  s.addText('Целевой пользователь — владелец малого бизнеса без финансового образования: ему нужна не таблица, а ответ «хватит или нет».', { x: 5.3, y: 4.25, w: 4.2, h: 0.75, fontSize: 12, italic: true, color: C.text2, margin: 0, valign: 'top', isTextBox: true, objectName: 'target user' })
  s.addNotes('Бизнес прибыльный, но деньги приходят с задержкой, а зарплата, ЕНП 28-го, аренда и кредит — по расписанию. Это реальный сценарий демо-компании S02: остаток действительно ушёл в минус 5 ноября, и наш прогноз предупредил об этом за 13 дней.')

  // 3. Решение
  s = content('Проблема и решение')
  s.addText('Три ответа на одном экране', { placeholder: 'title' })
  const sol = [
    [fa.FaScaleBalanced, 'Хватит ли денег', 'Светофор и одна фраза простыми словами: «через 13 дней, 5 ноября, может не хватить 685 000 ₽»'],
    [fa.FaCalendarDays, 'Когда и сколько', 'Остаток по дням на 30+ дней: ожидаемый и возможный диапазон, дата, сумма и вероятность разрыва'],
    [fa.FaListCheck, 'Что делать', '2–3 конкретных действия: кого попросить заплатить раньше, что перенести, когда нужен овердрафт'],
  ]
  for (let i = 0; i < 3; i++) {
    const y = 1.25 + i * 1.25
    await iconCircle(s, sol[i][0], 0.5, y, 0.55, i === 0 ? C.accent3 : C.accent2, 'solution ' + i)
    s.addText(sol[i][1], { x: 1.2, y, w: 3.1, h: 0.32, fontSize: 16, bold: true, color: C.text1, margin: 0, isTextBox: true, objectName: 'solution title ' + i })
    s.addText(sol[i][2], { x: 1.2, y: y + 0.34, w: 3.1, h: 0.8, fontSize: 12, color: C.text1, margin: 0, valign: 'top', isTextBox: true, objectName: 'solution text ' + i })
  }
  await screen(s, '02_risk_card.png', { x: 4.55, y: 1.2, w: 4.95, h: 3.85 }, { name: 'risk card screenshot' })
  s.addNotes('Цель кейса: прогноз остатка по дням минимум на 30 дней, кассовые разрывы с датой, суммой и вероятностью, понятно для предпринимателя. Всё это — на главном экране.')

  // 4–6. Демо
  pres.addSection({ title: 'Демо' })
  s = content('Демо')
  s.addText('Демо: выписка → прогноз → предупреждение', { placeholder: 'title' })
  await screen(s, '02_dashboard.png', { x: 0.5, y: 1.1, w: 6.4, h: 4.05 }, { name: 'dashboard screenshot' })
  const steps = [['1', 'Загрузили CSV выписки — 2 года, дубли и пропуски разобраны сами'], ['2', 'Подключили 1С, налоговый календарь, банк, реестры'], ['3', 'Главная: светофор, причина, первое действие'], ['4', 'График: ожидаемый остаток, диапазон, красная зона, значки платежей']]
  for (let i = 0; i < steps.length; i++) {
    const y = 1.2 + i * 0.98
    s.addShape(pres.shapes.OVAL, { x: 7.2, y, w: 0.4, h: 0.4, fill: { color: C.accent1 }, line: { type: 'none' }, objectName: 'step dot ' + i })
    s.addText(steps[i][0], { x: 7.2, y, w: 0.4, h: 0.4, fontSize: 14, bold: true, color: C.text2, align: 'center', valign: 'middle', margin: 0, isTextBox: true, objectName: 'step num ' + i })
    s.addText(steps[i][1], { x: 7.75, y: y - 0.05, w: 1.75, h: 0.9, fontSize: 11, color: C.text1, margin: 0, valign: 'top', isTextBox: true, objectName: 'step text ' + i })
  }
  s.addNotes('Входим, видим одну фразу: через 13 дней, 5 ноября, может не хватить 685 000 ₽, вероятность 97%. Ниже причина: 5 ноября зарплата 956 тыс. ₽ и аренда, а крупный клиент задерживает 2,3 млн ₽, и первое, что можно сделать — попросить его заплатить до 5 ноября. Наводим на график: линия — ожидаемый остаток, полоса — возможный диапазон, красная зона — денег нет.')

  s = content('Демо')
  s.addText('«Что если»: клиент заплатит на 3 недели позже', { placeholder: 'title' })
  await screen(s, '03_scenario_delay_card.png', { x: 0.5, y: 1.1, w: 6.4, h: 4.05 }, { name: 'scenario screenshot' })
  await iconCircle(s, fa.FaHourglassHalf, 7.2, 1.2, 0.55, C.accent3, 'scenario')
  s.addText('Четыре сценария', { x: 7.2, y: 1.9, w: 2.3, h: 0.35, fontSize: 15, bold: true, color: C.text1, margin: 0, isTextBox: true, objectName: 'scenario title' })
  s.addText([
    { text: 'клиент платит позже на 2–4 недели', options: { bullet: true, breakLine: true } },
    { text: 'выручка ниже на 10–30%', options: { bullet: true, breakLine: true } },
    { text: 'внеплановый расход', options: { bullet: true, breakLine: true } },
    { text: 'рост постоянных расходов', options: { bullet: true } },
  ], { x: 7.2, y: 2.3, w: 2.3, h: 1.5, fontSize: 12, color: C.text1, paraSpaceAfter: 4, margin: 0, valign: 'top', isTextBox: true, objectName: 'scenario list' })
  s.addText('Обычный и негативный прогноз — на одном графике, результат — одной фразой', { x: 7.2, y: 3.9, w: 2.3, h: 1.1, fontSize: 12, italic: true, color: C.text2, margin: 0, valign: 'top', isTextBox: true, objectName: 'scenario note' })
  s.addNotes('Предприниматель проверяет свои страхи. Задержка крупного клиента на 3 недели: разрыв останется 5 ноября, но не хватит уже 936 000 ₽ вместо 685 000 ₽ и продлится дольше. Оба прогноза на одном графике.')

  s = content('Демо')
  s.addText('План-факт и источники: прогноз живой', { placeholder: 'title' })
  await screen(s, '04_plan_fact.png', { x: 0.5, y: 1.1, w: 4.4, h: 4.05 }, { crop: 0.75, name: 'plan fact screenshot' })
  await screen(s, '05_events.png', { x: 5.1, y: 1.1, w: 4.4, h: 2.85 }, { name: 'events screenshot' })
  s.addText('Ожидаемый платёж не пришёл → счёт помечен «просрочен» → прогноз пересчитан. Каждое событие подписано источником.', { x: 5.1, y: 4.1, w: 4.4, h: 0.9, fontSize: 12, color: C.text1, margin: 0, valign: 'top', isTextBox: true, objectName: 'plan fact note' })
  s.addNotes('Сравниваем план с фактом. Клиент не заплатил в срок — одной кнопкой пересчитываем прогноз. Кроме выписки учитываем 1С, налоговый календарь, банк, открытые реестры и ручной ввод.')

  // 7. Источники
  pres.addSection({ title: 'Данные и подход' })
  s = content('Данные и подход')
  s.addText('Источники данных: каждый добавляет точность', { placeholder: 'title' })
  const src = [
    [fa.FaBuildingColumns, 'Банк', 'история, регулярные платежи, графики кредитов, подписанные платёжки'],
    [fa.FaBook, '1С', 'счета, договоры, зарплатные ведомости, просрочки'],
    [fa.FaReceipt, 'Налоговый календарь', 'ЕНП 28-го, УСН, НДС; режим оцениваем по выписке, ошибка суммы ЕНП ≈ 6%'],
    [fa.FaScroll, 'Открытые реестры', 'долги, арбитраж, ФССП контрагента → вероятность задержки оплаты'],
    [fa.FaPenToSquare, 'Ручной ввод', '«клиент обещал заплатить» — форма или фраза'],
  ]
  for (let i = 0; i < src.length; i++) {
    const y = 1.15 + i * 0.8
    await iconCircle(s, src[i][0], 0.5, y, 0.5, C.accent2, 'source ' + i)
    s.addText(src[i][1], { x: 1.15, y, w: 3.4, h: 0.26, fontSize: 13, bold: true, color: C.text1, margin: 0, isTextBox: true, objectName: 'source name ' + i })
    s.addText(src[i][2], { x: 1.15, y: y + 0.27, w: 3.4, h: 0.5, fontSize: 11, color: C.text2, margin: 0, valign: 'top', isTextBox: true, objectName: 'source text ' + i })
  }
  s.addChart(pres.charts.BAR, [{ name: 'Ошибка прогноза, млн ₽', labels: ['Только выписка', '+ налоговый календарь', '+ 1С', '+ открытые реестры', '+ 1С + реестры'], values: [1.80, 1.67, 1.27, 0.78, 0.51] }], {
    x: 4.9, y: 1.1, w: 4.6, h: 3.2, barDir: 'bar', chartColors: ['7A8A80', '7A8A80', '11553F', '11553F', '8DC63F'],
    showTitle: true, title: 'Средняя ошибка остатка на 30 дней, млн ₽ (S02)', titleFontSize: 12, titleColor: HEX.text, titleFontFace: '+mn-lt',
    showValue: true, dataLabelPosition: 'outEnd', dataLabelFormatCode: '0.00', dataLabelFontSize: 11, dataLabelColor: HEX.text, dataLabelFontFace: '+mn-lt',
    catAxisLabelColor: HEX.text2, catAxisLabelFontSize: 10, catAxisLabelFontFace: '+mn-lt', catAxisOrientation: 'maxMin',
    valAxisHidden: true, valGridLine: { style: 'none' }, catGridLine: { style: 'none' }, showLegend: false, varyColors: true, objectName: 'sources chart',
  })
  s.addText('Только по выписке разрыв 5 ноября не виден (вероятность 18%). С 1С и реестрами — найден, вероятность 75%.', { x: 4.9, y: 4.35, w: 4.6, h: 0.7, fontSize: 12, bold: true, color: C.text2, margin: 0, valign: 'top', isTextBox: true, objectName: 'sources takeaway' })
  s.addNotes('Источник: api/reports/sources_effect.md — прогноз на 30 дней сравнивается с тем, что было на самом деле. На реальных выписках организаторов (holdout, 38 компаний) налоговый календарь улучшает прогноз в 18 компаниях из 38.')

  // 8. Подход
  s = content('Данные и подход')
  s.addText('Как строим прогноз', { placeholder: 'title' })
  const pipe = [
    [fa.FaFileCsv, 'Выписка', 'чистка: дубли, пропуски, BOM, ИНН строкой'],
    [fa.FaTags, 'Категории', 'правила + память контрагента + ML'],
    [fa.FaRotate, 'Регулярные платежи', 'зарплата, аренда, ЕНП, кредиты; 74% приходят в ±3 дня'],
    [fa.FaDiceFive, 'Монте-Карло', '2 000 вариантов будущего: задержки оплат, колебания выручки'],
    [fa.FaTriangleExclamation, 'Риски', 'дата, сумма, вероятность, причина и действия'],
  ]
  const pw = 1.68
  for (let i = 0; i < pipe.length; i++) {
    const x = 0.5 + i * (pw + 0.15)
    card(s, x, 1.3, pw, 2.4, i === 4 ? C.background2 : C.background2, 'pipe card ' + i)
    await iconCircle(s, pipe[i][0], x + (pw - 0.6) / 2, 1.5, 0.6, i === 4 ? C.accent3 : C.accent2, 'pipe ' + i)
    s.addText(pipe[i][1], { x: x + 0.1, y: 2.2, w: pw - 0.2, h: 0.35, fontSize: 13, bold: true, color: C.text1, align: 'center', margin: 0, isTextBox: true, objectName: 'pipe title ' + i })
    s.addText(pipe[i][2], { x: x + 0.12, y: 2.6, w: pw - 0.24, h: 1.0, fontSize: 11, color: C.text2, align: 'center', margin: 0, valign: 'top', isTextBox: true, objectName: 'pipe text ' + i })
  }
  s.addText([
    { text: 'Результат: ', options: { bold: true } },
    { text: 'остаток по дням — ожидаемый (P50) и возможный диапазон (P10–P90). Два вида риска: разрыв ниже 0 ₽ и остаток ниже комфортного минимума владельца. Новые операции обновляют прогноз без полного пересчёта (~0,05 с).' },
  ], { x: 0.5, y: 3.95, w: 9.0, h: 1.0, fontSize: 13, color: C.text1, margin: 0, valign: 'top', isTextBox: true, objectName: 'pipe result' })
  s.addNotes('Модель не чёрный ящик: каждая сумма в причине риска подписана источником — «из выписки», «налоговый календарь», «из 1С».')

  // 9. Качество
  s = content('Данные и подход')
  s.addText('Проверка качества: честный бэктест', { placeholder: 'title' })
  stat(s, 0.5, 1.15, 2.9, '16%', 'ошибка остатка на 30 дней; у наивной модели 21%', C.accent2, 'mae')
  stat(s, 0.5, 2.45, 2.9, '80%', 'дней факт внутри «возможного диапазона»', C.accent2, 'coverage')
  stat(s, 0.5, 3.75, 2.9, '72%', 'реальных разрывов найдено, в среднем за 14 дней', C.accent3, 'recall')
  s.addChart(pres.charts.BAR, [{ name: 'Ошибка остатка, % оборота', labels: ['Наивная (повтор 28 дней)', 'Сезонная (ETS)', 'Наш гибрид'], values: [21, 19, 16] }], {
    x: 3.7, y: 1.1, w: 5.8, h: 2.9, barDir: 'col', chartColors: ['7A8A80', '7A8A80', '11553F'], varyColors: true,
    showTitle: true, title: 'Ошибка остатка на 30 дней, % месячного оборота (меньше — лучше)', titleFontSize: 12, titleColor: HEX.text, titleFontFace: '+mn-lt',
    showValue: true, dataLabelPosition: 'outEnd', dataLabelFormatCode: '0"%"', dataLabelFontSize: 12, dataLabelColor: HEX.text, dataLabelFontFace: '+mn-lt',
    catAxisLabelColor: HEX.text2, catAxisLabelFontSize: 11, catAxisLabelFontFace: '+mn-lt', valAxisHidden: true, valAxisMinVal: 0,
    valGridLine: { style: 'none' }, catGridLine: { style: 'none' }, showLegend: false, objectName: 'models chart',
  })
  card(s, 3.7, 4.1, 5.8, 0.95, C.background2, 'method card')
  s.addText('150 компаний организаторов разделены на dev и holdout. Параметры подбирали только на dev; цифры — только holdout: 73 компании, 542 прогноза на модель, rolling origin, 8 отсечек × 30 дней.', { x: 3.85, y: 4.17, w: 5.5, h: 0.8, fontSize: 11, color: C.text1, margin: 0, valign: 'middle', isTextBox: true, objectName: 'method text' })
  s.addNotes('Источник: core/reports/metrics.md. Precision предупреждений о разрыве — 46%: каждое второе предупреждение — ложное, но цена пропущенного разрыва для владельца выше. Категоризация со скрытым назначением платежа: accuracy 97%.')

  // 10. Архитектура
  pres.addSection({ title: 'Архитектура и безопасность' })
  s = content('Архитектура и безопасность')
  s.addText('Архитектура решения', { placeholder: 'title' })
  const am = await sharp(path.join(ROOT, 'docs/architecture_slide.png')).metadata()
  const aw = 9.0, ah = Math.min(3.45, aw * am.height / am.width)
  const aww = ah * am.width / am.height
  s.addImage({ path: path.join(ROOT, 'docs/architecture_slide.png'), x: 0.5 + (9.0 - aww) / 2, y: 1.1, w: aww, h: ah, objectName: 'architecture diagram' })
  s.addText('web (React) → API (FastAPI, JWT, SQLite, интеграции) → ядро cashflow_core (Python). Контракт JSON — общий для всех частей.', { x: 0.5, y: 1.1 + ah + 0.1, w: 9.0, h: 0.4, fontSize: 12, color: C.text2, margin: 0, isTextBox: true, objectName: 'architecture caption' })
  s.addNotes('Ядро — независимый Python-пакет, API — по открытому контракту docs/contract.md. Встраивается в интернет-банк как виджет.')

  // 11. Безопасность
  s = content('Архитектура и безопасность')
  s.addText('Безопасность данных клиента', { placeholder: 'title' })
  const sec = [
    [fa.FaKey, 'Вход и токены', 'JWT на каждом запросе, пароли — PBKDF2-SHA256, одинаковое время ответа на неверный логин'],
    [fa.FaUserShield, 'Изоляция', 'один пользователь — одна компания; чужие данные — 403'],
    [fa.FaEyeSlash, 'Логи без тайн', 'фильтр маскирует ИНН, суммы, названия и e-mail; тела запросов не пишутся'],
    [fa.FaFileShield, 'Загрузка', 'лимит размера и проверка формата до разбора; выписка не хранится в браузере'],
  ]
  for (let i = 0; i < sec.length; i++) {
    const col = i % 2, row = Math.floor(i / 2)
    const x = 0.5 + col * 4.6, y = 1.2 + row * 1.9
    card(s, x, y, 4.4, 1.7, C.background2, 'security card ' + i)
    await iconCircle(s, sec[i][0], x + 0.25, y + 0.3, 0.6, C.accent2, 'security ' + i)
    s.addText(sec[i][1], { x: x + 1.05, y: y + 0.28, w: 3.15, h: 0.35, fontSize: 15, bold: true, color: C.text1, margin: 0, isTextBox: true, objectName: 'security title ' + i })
    s.addText(sec[i][2], { x: x + 1.05, y: y + 0.68, w: 3.15, h: 0.9, fontSize: 12, color: C.text2, margin: 0, valign: 'top', isTextBox: true, objectName: 'security text ' + i })
  }
  s.addNotes('Подробности — api/README.md, раздел «Безопасность»; фильтр логов — api/logging_setup.py.')

  // 12. Сверх базы и планы
  pres.addSection({ title: 'Итоги' })
  s = content('Итоги')
  s.addText('Сверх базового прогноза и что дальше', { placeholder: 'title' })
  card(s, 0.5, 1.15, 4.4, 3.9, C.background2, 'done card')
  s.addText('Реализовано', { x: 0.75, y: 1.3, w: 4.0, h: 0.35, fontSize: 16, bold: true, color: C.accent2, margin: 0, isTextBox: true, objectName: 'done title' })
  s.addText([
    { text: '5 источников данных с единым форматом событий', options: { bullet: true, breakLine: true } },
    { text: '«Что если» по 4 сценариям', options: { bullet: true, breakLine: true } },
    { text: 'План-факт с пересчётом прогноза', options: { bullet: true, breakLine: true } },
    { text: 'Быстрое обновление без пересчёта', options: { bullet: true, breakLine: true } },
    { text: 'Ручной ввод обычной фразой', options: { bullet: true, breakLine: true } },
    { text: 'Пакетный прогноз: 150 компаний за 85 с', options: { bullet: true, breakLine: true } },
    { text: 'Интерфейс для телефона', options: { bullet: true } },
  ], { x: 0.75, y: 1.75, w: 4.0, h: 3.2, fontSize: 13, color: C.text1, paraSpaceAfter: 5, margin: 0, valign: 'top', isTextBox: true, objectName: 'done list' })
  await screen(s, '09_mobile.png', { x: 5.1, y: 1.1, w: 1.8, h: 4.0 }, { name: 'mobile screenshot' })
  s.addText('Дальше', { x: 7.15, y: 1.3, w: 2.35, h: 0.35, fontSize: 16, bold: true, color: C.accent2, margin: 0, isTextBox: true, objectName: 'next title' })
  s.addText([
    { text: 'Виджет в интернет-банке: выписка уже в банке', options: { bullet: true, breakLine: true } },
    { text: 'Уведомление за 2 недели до разрыва', options: { bullet: true, breakLine: true } },
    { text: 'Овердрафт прямо из предупреждения', options: { bullet: true, breakLine: true } },
    { text: 'Реальные API 1С и ФНС', options: { bullet: true } },
  ], { x: 7.15, y: 1.75, w: 2.35, h: 3.2, fontSize: 12, color: C.text1, paraSpaceAfter: 5, margin: 0, valign: 'top', isTextBox: true, objectName: 'next list' })
  s.addNotes('Пакетный прогноз для контрольного датасета: python -m api.predict — все 150 компаний за 85 с на 4 процессах, детерминированно.')

  // 13. Итог
  s = pres.addSlide({ masterName: 'DARK', sectionTitle: 'Итоги' })
  s.addText('Предупреждаем о разрыве заранее и говорим, что делать', { placeholder: 'title' })
  s.addText('30+ дней прогноза по дням · дата, сумма и вероятность разрыва · 16% ошибки против 21% у наивной модели · разрыв S02 найден за 13 дней', { placeholder: 'body' })
  s.addNotes('Спасибо! Готовы показать сервис вживую и ответить на вопросы.')

  await pres.writeFile({ fileName: OUT })
  await applyTheme(OUT, THEME)
  console.log('written', OUT)
})().catch((e) => { console.error(e); process.exit(1) })
