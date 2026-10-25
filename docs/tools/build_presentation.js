const path = require('path')
const fs = require('fs')
const pptxgen = require('pptxgenjs')
const sharp = require('sharp')
const React = require('react')
const ReactDOMServer = require('react-dom/server')
const fa = require('react-icons/fa6')
const QRCode = require('qrcode')
const JSZip = require('jszip')
const { applyTheme } = require(process.env.PPTX_SKILL + '/scripts/apply_theme.js')

const ROOT = process.argv[2]
const SHOTS = path.join(ROOT, 'docs/screens')
const OUT = path.join(ROOT, 'docs/presentation.pptx')
const DEMO_URL = 'https://217.144.184.234.sslip.io/'

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
pres.layout = 'LAYOUT_16x9'
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace }
pres.title = 'Денежный прогноз — прогноз остатка и кассовых разрывов для малого бизнеса'
pres.author = 'Команда «Денежный прогноз»'
const C = pres.SchemeColor

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
async function screen(slide, file, box, { crop, name } = {}) {
  const m = await dims(file)
  let iw = m.width, ih = m.height
  if (crop) ih = Math.round(iw * crop)
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
const num = (v, d) => v.toFixed(d).replace('.', ',')

function chartTitle(slide, box, title, name) {
  slide.addText(title, { x: box.x, y: box.y, w: box.w, h: 0.42, fontSize: 12, bold: true, color: C.text1, margin: 0, valign: 'top', isTextBox: true, objectName: name + ' title' })
}
function hbars(slide, box, { title, labels, values, colors, digits, name }) {
  chartTitle(slide, box, title, name)
  const top = box.y + 0.5, rowH = (box.h - 0.5) / labels.length
  const labelW = 1.75, gap = 0.1, valueW = 0.55
  const x0 = box.x + labelW + gap, maxW = box.w - labelW - gap - valueW
  const max = Math.max(...values)
  labels.forEach((label, i) => {
    const y = top + i * rowH, barH = rowH * 0.62, by = y + (rowH - barH) / 2
    const w = Math.max(0.04, maxW * values[i] / max)
    slide.addText(label, { x: box.x, y, w: labelW, h: rowH, fontSize: 10, color: C.text2, align: 'right', valign: 'middle', margin: 0, isTextBox: true, objectName: `${name} label ${i}` })
    slide.addShape(pres.shapes.RECTANGLE, { x: x0, y: by, w, h: barH, fill: { color: colors[i] }, line: { type: 'none' }, objectName: `${name} bar ${i}` })
    slide.addText(num(values[i], digits), { x: x0 + w + 0.06, y, w: valueW, h: rowH, fontSize: 11, bold: true, color: C.text1, valign: 'middle', margin: 0, isTextBox: true, objectName: `${name} value ${i}` })
  })
}
function vbars(slide, box, { title, labels, values, colors, digits, suffix, name }) {
  chartTitle(slide, box, title, name)
  const top = box.y + 0.75, labelH = 0.45, base = box.y + box.h - labelH
  const colW = box.w / labels.length, barW = colW * 0.5, maxH = base - top
  const max = Math.max(...values)
  slide.addShape(pres.shapes.LINE, { x: box.x, y: base, w: box.w, h: 0, line: { color: HEX.border, width: 1 }, objectName: name + ' axis' })
  labels.forEach((label, i) => {
    const h = Math.max(0.04, maxH * values[i] / max), x = box.x + i * colW + (colW - barW) / 2
    slide.addShape(pres.shapes.RECTANGLE, { x, y: base - h, w: barW, h, fill: { color: colors[i] }, line: { type: 'none' }, objectName: `${name} bar ${i}` })
    slide.addText(num(values[i], digits) + suffix, { x: box.x + i * colW, y: base - h - 0.3, w: colW, h: 0.28, fontSize: 12, bold: true, color: C.text1, align: 'center', margin: 0, isTextBox: true, objectName: `${name} value ${i}` })
    slide.addText(label, { x: box.x + i * colW + 0.03, y: base + 0.04, w: colW - 0.06, h: labelH - 0.04, fontSize: 10, color: C.text2, align: 'center', valign: 'top', margin: 0, isTextBox: true, objectName: `${name} label ${i}` })
  })
}
async function stripUnusedTypes(file) {
  const zip = await JSZip.loadAsync(fs.readFileSync(file))
  const used = new Set(Object.keys(zip.files).filter((f) => !zip.files[f].dir).map((f) => f.split('.').pop().toLowerCase()))
  const ct = await zip.file('[Content_Types].xml').async('string')
  const out = ct.replace(/<Default Extension="([^"]+)"[^>]*\/>/g, (m, ext) => (used.has(ext.toLowerCase()) ? m : ''))
  const clean = new JSZip()
  clean.file('[Content_Types].xml', out, { createFolders: false })
  for (const name of Object.keys(zip.files)) {
    if (zip.files[name].dir || name === '[Content_Types].xml') continue
    clean.file(name, await zip.file(name).async('uint8array'), { createFolders: false })
  }
  fs.writeFileSync(file, await clean.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' }))
}

const Q = { mae: '13,1', maeFlat: '13,3', maeNaive: 21.5, maeEts: 19.0, maeVal: 13.1, maeFlatVal: 13.3, wape: '0,263', wapeFlat: '0,253',
  better: 61, cov: 81, recall: 61, precision: 70, lead: 12, n: 73, forecasts: 542, ctlWape: '0,235', ctlWapeFlat: '0,231', ctlBetter: 54 }
const SRC_LABELS = ['Только выписка', '+ налоговый календарь', '+ 1С', '+ открытые реестры', '+ 1С + реестры']
const SRC_VALUES = [1.78, 1.48, 1.27, 0.74, 0.46]
const SRC_TAKEAWAY = 'На синтетической демо-компании S02: только по выписке разрыв не виден (вероятность 18%), с 1С и реестрами — найден (86%).'
;(async () => {
  pres.addSection({ title: 'Начало' })
  let s = pres.addSlide({ masterName: 'DARK', sectionTitle: 'Начало' })
  const logo = await sharp(path.join(ROOT, 'web/public/logo.svg'), { density: 600 }).resize(256, 256).png().toBuffer()
  s.addImage({ data: 'image/png;base64,' + logo.toString('base64'), x: 0.6, y: 0.7, w: 0.62, h: 0.62, objectName: 'logo' })
  s.addText('Хакатон Банка Центр-Инвест', { x: 1.4, y: 0.75, w: 6, h: 0.5, fontSize: 14, color: 'A9C7B5', valign: 'middle', margin: 0, isTextBox: true, objectName: 'event' })
  s.addText('Денежный прогноз', { placeholder: 'title' })
  s.addText('Предупреждаем предпринимателя о кассовом разрыве заранее — и подсказываем, что сделать', { placeholder: 'body' })
  s.addNotes('Ведущий (10 с): Малый бизнес часто закрывается не из-за убытков, а потому что в нужный день на счёте нет денег. Мы сделали сервис, который заранее говорит: когда не хватит, сколько и что сделать.')

  pres.addSection({ title: 'Проблема и решение' })
  s = content('Проблема и решение')
  s.addText('Прибыльный бизнес, а на счёте −471 600 ₽', { placeholder: 'title' })
  card(s, 0.5, 1.2, 4.4, 3.85, C.background2, 'persona card')
  await iconCircle(s, fa.FaLaptopCode, 0.8, 1.45, 0.6, C.accent2, 'persona')
  s.addText('ООО «Софт-Решения-771»', { x: 1.55, y: 1.45, w: 3.2, h: 0.3, fontSize: 14, bold: true, color: C.text1, margin: 0, isTextBox: true, objectName: 'persona name' })
  s.addText('разработка ПО · реальная выписка из датасета (C124)', { x: 1.55, y: 1.75, w: 3.2, h: 0.3, fontSize: 11, color: C.accent6, margin: 0, isTextBox: true, objectName: 'persona sub' })
  s.addText([
    { text: '16 сентября на счёте 2,9 млн ₽', options: { bullet: true, breakLine: true } },
    { text: '29.09 — ЕНП 1,48 млн ₽, 30.09 — зарплата 2,48 млн ₽', options: { bullet: true, breakLine: true } },
    { text: 'клиент заплатил 1,27 млн ₽ только 3 октября', options: { bullet: true, breakLine: true } },
    { text: 'итог — овердрафт и проценты банку', options: { bullet: true } },
  ], { x: 0.8, y: 2.3, w: 3.9, h: 2.55, fontSize: 14, color: C.text1, paraSpaceAfter: 8, valign: 'top', margin: 0, isTextBox: true, objectName: 'persona facts' })
  await iconCircle(s, fa.FaUserTie, 5.3, 1.3, 0.6, C.accent3, 'user')
  s.addText('Наш пользователь', { x: 6.05, y: 1.3, w: 3.4, h: 0.3, fontSize: 15, bold: true, color: C.text1, margin: 0, isTextBox: true, objectName: 'user title' })
  s.addText('владелец малого бизнеса без финансового образования: ему нужна не таблица, а ответ — хватит денег или нет', { x: 6.05, y: 1.65, w: 3.45, h: 0.95, fontSize: 12, color: C.text2, margin: 0, valign: 'top', isTextBox: true, objectName: 'user text' })
  await iconCircle(s, fa.FaCalendarXmark, 5.3, 2.85, 0.6, C.accent3, 'pain')
  s.addText('Почему так бывает', { x: 6.05, y: 2.85, w: 3.4, h: 0.3, fontSize: 15, bold: true, color: C.text1, margin: 0, isTextBox: true, objectName: 'pain title' })
  s.addText('зарплата, налоги и аренда — по графику, а клиенты платят, когда платят; выписка показывает прошлое, а разрыв видно только в день платежа', { x: 6.05, y: 3.2, w: 3.45, h: 1.2, fontSize: 12, color: C.text2, margin: 0, valign: 'top', isTextBox: true, objectName: 'pain text' })
  s.addNotes('Ведущий (25 с): Это реальная выписка из датасета организаторов. IT-компания, прибыльная. 16 сентября на счёте 2,9 миллиона. В конце месяца налог и зарплата, клиент платит только 3 октября — и 1 октября на счёте минус 471 тысяча, банк берёт проценты за овердрафт.')

  s = content('Проблема и решение')
  s.addText('Три ответа на одном экране', { placeholder: 'title' })
  const sol = [
    [fa.FaScaleBalanced, 'Хватит ли денег', 'цветная карточка риска и одна фраза: «через 14 дней, 30 сентября, дефицит составит 458 000 ₽»'],
    [fa.FaCalendarDays, 'Когда и сколько', 'остаток по дням на 30+ дней: ожидаемый и возможный диапазон, дата, сумма и вероятность разрыва'],
    [fa.FaListCheck, 'Что делать', 'конкретное действие: «попросите ООО «Ритейл-381» оплатить до 30 сентября»'],
  ]
  for (let i = 0; i < 3; i++) {
    const y = 1.25 + i * 1.25
    await iconCircle(s, sol[i][0], 0.5, y, 0.55, i === 0 ? C.accent3 : C.accent2, 'solution ' + i)
    s.addText(sol[i][1], { x: 1.2, y, w: 3.1, h: 0.32, fontSize: 16, bold: true, color: C.text1, margin: 0, isTextBox: true, objectName: 'solution title ' + i })
    s.addText(sol[i][2], { x: 1.2, y: y + 0.34, w: 3.1, h: 0.8, fontSize: 12, color: C.text1, margin: 0, valign: 'top', isTextBox: true, objectName: 'solution text ' + i })
  }
  await screen(s, '03_preduprezhdenie.png', { x: 4.55, y: 1.2, w: 4.95, h: 3.85 }, { name: 'risk card screenshot' })
  s.addNotes('Ведущий (15 с): Прогноз остатка по дням на 30+ дней, разрыв с датой, суммой и вероятностью — понятно человеку без финансового образования, на главном экране.')

  pres.addSection({ title: 'Демо' })
  s = content('Демо')
  s.addText('Демо: прогноз от 16 сентября против факта', { placeholder: 'title' })
  await screen(s, '04_grafik.png', { x: 0.5, y: 1.1, w: 5.6, h: 4.05 }, { name: 'chart screenshot' })
  const facts = [
    ['30 сентября', 'дата разрыва: прогноз = факт', C.accent2],
    ['58%', 'вероятность за 14 и за 7 дней: средний риск, оранжевая карточка', C.accent4],
    ['−458 тыс. ₽', 'ожидаемый остаток; на деле −381 тыс. ₽ 30.09 и −472 тыс. ₽ 1.10', C.text2],
  ]
  for (let i = 0; i < facts.length; i++) {
    const y = 1.15 + i * 1.3
    s.addText(facts[i][0], { x: 6.4, y, w: 3.1, h: 0.6, fontSize: 30, bold: true, color: facts[i][2], margin: 0, isTextBox: true, objectName: 'fact value ' + i })
    s.addText(facts[i][1], { x: 6.4, y: y + 0.6, w: 3.1, h: 0.6, fontSize: 12, color: C.text1, margin: 0, valign: 'top', isTextBox: true, objectName: 'fact label ' + i })
  }
  s.addNotes('Оператор (45 с): «Посмотреть демо» → загружаем выписку по 16 сентября (будущего сервис не видит) → подключаем налоговый календарь → главная. Ведущий: через 14 дней, 30 сентября, может не хватить 458 тысяч, вероятность 58%, и первое действие. На самом деле 30 сентября на счёте минус 381 тысяча, 1 октября — минус 472.')

  s = content('Демо')
  s.addText('«Что если» и источники: прогноз меняется сразу', { placeholder: 'title' })
  await screen(s, '06_chto_esli.png', { x: 0.5, y: 1.1, w: 5.1, h: 3.0 }, { name: 'scenario screenshot' })
  s.addText('Клиент заплатит на 3 недели позже → «не хватит уже 910 000 ₽ вместо 458 000 ₽». База и сценарий — на одном графике.', { x: 0.5, y: 4.2, w: 5.1, h: 0.8, fontSize: 12, color: C.text1, margin: 0, valign: 'top', isTextBox: true, objectName: 'scenario note' })
  await screen(s, '05_istochniki.png', { x: 5.8, y: 1.1, w: 3.7, h: 2.6 }, { crop: 0.62, name: 'sources screenshot' })
  s.addText([
    { text: 'подключили источник → на экране «было → стало»', options: { bullet: true, breakLine: true } },
    { text: 'платёж фразой: «купим станок за 1,2 млн 10 ноября»', options: { bullet: true, breakLine: true } },
    { text: 'план-факт: не пришёл платёж → прогноз пересчитан', options: { bullet: true } },
  ], { x: 5.8, y: 3.85, w: 3.7, h: 1.2, fontSize: 12, color: C.text1, paraSpaceAfter: 4, margin: 0, valign: 'top', isTextBox: true, objectName: 'sources list' })
  s.addNotes('Оператор (30 с): «Что если»: клиент заплатит на три недели позже — нехватка вырастает до 910 тысяч. Ведущий: источники и ручной ввод меняют прогноз сразу — экран показывает «было → стало».')

  pres.addSection({ title: 'Данные и подход' })
  s = content('Данные и подход')
  s.addText('Источники данных: каждый добавляет точность', { placeholder: 'title' })
  const src = [
    [fa.FaBuildingColumns, 'Банк', 'выписка, регулярные платежи; графики кредитов и платёжки — на тестовых выгрузках'],
    [fa.FaBook, '1С', 'счета, договоры, зарплата — загрузка выгрузки; в демо тестовые файлы'],
    [fa.FaReceipt, 'Налоговый календарь', 'ЕНП 28-го, УСН, НДС; режим определяем по выписке'],
    [fa.FaScroll, 'Открытые реестры', 'долги и суды контрагента → риск задержки оплаты'],
    [fa.FaPenToSquare, 'Ручной ввод', 'форма или обычная фраза'],
  ]
  for (let i = 0; i < src.length; i++) {
    const y = 1.15 + i * 0.8
    await iconCircle(s, src[i][0], 0.5, y, 0.5, C.accent2, 'source ' + i)
    s.addText(src[i][1], { x: 1.15, y, w: 3.4, h: 0.26, fontSize: 13, bold: true, color: C.text1, margin: 0, isTextBox: true, objectName: 'source name ' + i })
    s.addText(src[i][2], { x: 1.15, y: y + 0.27, w: 3.4, h: 0.5, fontSize: 11, color: C.text2, margin: 0, valign: 'top', isTextBox: true, objectName: 'source text ' + i })
  }
  hbars(s, { x: 4.9, y: 1.1, w: 4.6, h: 3.2 }, {
    title: 'Ошибка остатка на 30 дней, млн ₽ (синтетическая демо-компания S02)', labels: SRC_LABELS, values: SRC_VALUES,
    colors: ['7A8A80', '7A8A80', '11553F', '11553F', '8DC63F'], digits: 2, name: 'sources chart',
  })
  s.addText(SRC_TAKEAWAY, { x: 4.9, y: 4.35, w: 4.6, h: 0.7, fontSize: 12, bold: true, color: C.text2, margin: 0, valign: 'top', isTextBox: true, objectName: 'sources takeaway' })
  s.addNotes('Ведущий (20 с): Это наша синтетическая компания с известным будущим (api/reports/sources_effect.md). Честно: работает частично — налоговый календарь считается по выписке, банк и 1С — на тестовых выгрузках, реестры — демонстрационная проверка по ИНН.')

  s = content('Данные и подход')
  s.addText('Как строим прогноз', { placeholder: 'title' })
  const pipe = [
    [fa.FaFileCsv, 'Выписка', 'дубли, пропуски, BOM, «;», ИНН строкой'],
    [fa.FaTags, 'Категории', 'правила + обучение на операциях самой компании'],
    [fa.FaRotate, 'Регулярные платежи', 'зарплата, аренда, ЕНП 28-го, кредиты'],
    [fa.FaDiceFive, 'Монте-Карло', '2 000 вариантов будущего; остальное сжимаем к текущему остатку'],
    [fa.FaTriangleExclamation, 'Риски', 'дата, сумма, вероятность, причина и действия'],
  ]
  const pw = 1.68
  for (let i = 0; i < pipe.length; i++) {
    const x = 0.5 + i * (pw + 0.15)
    card(s, x, 1.3, pw, 2.4, C.background2, 'pipe card ' + i)
    await iconCircle(s, pipe[i][0], x + (pw - 0.6) / 2, 1.5, 0.6, i === 4 ? C.accent3 : C.accent2, 'pipe ' + i)
    s.addText(pipe[i][1], { x: x + 0.1, y: 2.2, w: pw - 0.2, h: 0.35, fontSize: 13, bold: true, color: C.text1, align: 'center', margin: 0, isTextBox: true, objectName: 'pipe title ' + i })
    s.addText(pipe[i][2], { x: x + 0.12, y: 2.6, w: pw - 0.24, h: 1.0, fontSize: 11, color: C.text2, align: 'center', margin: 0, valign: 'top', isTextBox: true, objectName: 'pipe text ' + i })
  }
  s.addText([
    { text: 'Результат: ', options: { bold: true } },
    { text: 'остаток по дням — ожидаемый (P50) и возможный диапазон (P10–P90): известные платежи с датами, остальные потоки — ближе к «остаток не изменится». Два вида риска: ниже 0 ₽ и ниже комфортного минимума. Без утечки из будущего (тест) и без подгонки под компании.' },
  ], { x: 0.5, y: 3.95, w: 9.0, h: 1.0, fontSize: 13, color: C.text1, margin: 0, valign: 'top', isTextBox: true, objectName: 'pipe result' })
  s.addNotes('Ведущий (20 с): Модель объяснимая: каждая сумма в причине подписана источником. Прогноз детерминированный, работает без сети, на 150 компаниях — около 25 секунд.')

  s = content('Данные и подход')
  s.addText('Сравнение с «остаток не изменится»', { placeholder: 'title' })
  stat(s, 0.5, 1.15, 2.9, Q.better + '%', 'компаний: прогноз точнее, чем «остаток не изменится»', C.accent2, 'better')
  stat(s, 0.5, 2.45, 2.9, Q.mae + '%', 'ошибка фактического остатка, медиана в долях оборота; у бейзлайна ' + Q.maeFlat + '%', C.accent2, 'mae')
  stat(s, 0.5, 3.75, 2.9, Q.recall + '%', 'разрывов найдено заранее (точность ' + Q.precision + '%), в среднем за ' + Q.lead + ' дней', C.accent3, 'recall')
  vbars(s, { x: 3.7, y: 1.1, w: 5.8, h: 2.75 }, {
    title: 'Ошибка фактического остатка, % месячного оборота (меньше — лучше)',
    labels: ['Остаток не изменится', 'Наивная (повтор 28 дней)', 'Сезонная (ETS)', 'Наш прогноз'],
    values: [Q.maeFlatVal, Q.maeNaive, Q.maeEts, Q.maeVal], colors: ['7A8A80', '7A8A80', '7A8A80', '11553F'], digits: 1, suffix: '%', name: 'models chart',
  })
  card(s, 3.7, 3.95, 5.8, 1.1, C.background2, 'method card')
  s.addText(`Честно: общий WAPE на ${Q.n} отложенных компаниях — ${Q.wape} против ${Q.wapeFlat} у «остаток не изменится», чуть хуже; за последние 30 дней всех 150 выписок — ${Q.ctlWape} против ${Q.ctlWapeFlat}. Поэтому прогноз — смесь модели с бейзлайном. Параметры подбирались только на dev, цифры — holdout, ${Q.forecasts} прогнозов на модель.`, { x: 3.85, y: 4.0, w: 5.5, h: 1.0, fontSize: 10.5, color: C.text1, margin: 0, valign: 'middle', isTextBox: true, objectName: 'method text' })
  s.addNotes(`Ведущий (25 с): Жюри сравнит прогноз с фактическим остатком, поэтому главный соперник — «остаток не изменится». Наш прогноз точнее у ${Q.better}% компаний и по медиане ошибки, но по общему WAPE чуть хуже — это видно в core/reports/metrics.md. Разрывы: находим ${Q.recall}%, точность предупреждений ${Q.precision}%.`)

  pres.addSection({ title: 'Архитектура' })
  s = content('Архитектура')
  s.addText('Архитектура и безопасность', { placeholder: 'title' })
  const am = await sharp(path.join(ROOT, 'docs/architecture_slide.png')).metadata()
  const ah = 3.0, aww = ah * am.width / am.height
  s.addImage({ path: path.join(ROOT, 'docs/architecture_slide.png'), x: 0.5, y: 1.15, w: aww, h: ah, objectName: 'architecture diagram' })
  const sec = [[fa.FaKey, 'JWT, пароли PBKDF2'], [fa.FaUserShield, 'общие компании — только чтение, у гостя своя копия (тест)'], [fa.FaEyeSlash, 'в логах нет ИНН, сумм, названий, токенов (тест)'], [fa.FaGaugeHigh, 'лимит запросов и размера файла'], [fa.FaLock, 'HTTPS: Caddy + docker compose, развёрнуто на VPS']]
  const sx = 0.5 + aww + 0.3, sw = 9.5 - sx
  for (let i = 0; i < sec.length; i++) {
    const y = 1.15 + i * 0.62
    await iconCircle(s, sec[i][0], sx, y, 0.42, C.accent2, 'security ' + i)
    s.addText(sec[i][1], { x: sx + 0.55, y: y - 0.02, w: sw - 0.55, h: 0.5, fontSize: 11, color: C.text1, margin: 0, valign: 'middle', isTextBox: true, objectName: 'security text ' + i })
  }
  s.addText('web (React) → API (FastAPI, SQLite, интеграции) → ядро cashflow_core (Python). Единый контракт JSON.', { x: 0.5, y: 4.4, w: 9.0, h: 0.5, fontSize: 12, color: C.text2, margin: 0, isTextBox: true, objectName: 'architecture caption' })
  s.addNotes('Ведущий (20 с): Три части по общему контракту. Запуск — одна команда docker compose с HTTPS; демо — в один клик, у каждого гостя своя копия компании, общие данные никто не испортит.')

  pres.addSection({ title: 'Итоги' })
  s = content('Итоги')
  s.addText('Сделано сверх минимума и что дальше', { placeholder: 'title' })
  card(s, 0.5, 1.15, 4.4, 3.9, C.background2, 'done card')
  s.addText('Работает в прототипе', { x: 0.75, y: 1.3, w: 4.0, h: 0.35, fontSize: 16, bold: true, color: C.accent2, margin: 0, isTextBox: true, objectName: 'done title' })
  s.addText([
    { text: '«что если»: 6 сценариев, в т.ч. потеря клиента и рост налогов', options: { bullet: true, breakLine: true } },
    { text: 'ручной ввод — формой и обычной фразой', options: { bullet: true, breakLine: true } },
    { text: 'источники — частично: налоговый календарь, банк и 1С на тестовых выгрузках; «было → стало»', options: { bullet: true, breakLine: true } },
    { text: 'план-факт с пересчётом прогноза', options: { bullet: true, breakLine: true } },
    { text: 'прогноз для 150 компаний одной командой', options: { bullet: true, breakLine: true } },
    { text: 'телефон, планшет, ноутбук', options: { bullet: true } },
  ], { x: 0.75, y: 1.75, w: 4.0, h: 3.2, fontSize: 13, color: C.text1, paraSpaceAfter: 5, margin: 0, valign: 'top', isTextBox: true, objectName: 'done list' })
  await screen(s, '10_telefon.png', { x: 5.1, y: 1.1, w: 1.8, h: 4.0 }, { name: 'mobile screenshot' })
  s.addText('Дальше', { x: 7.15, y: 1.3, w: 2.35, h: 0.35, fontSize: 16, bold: true, color: C.accent2, margin: 0, isTextBox: true, objectName: 'next title' })
  s.addText([
    { text: 'виджет в интернет-банке: выписка уже в банке', options: { bullet: true, breakLine: true } },
    { text: 'уведомление за 2 недели до разрыва', options: { bullet: true, breakLine: true } },
    { text: 'овердрафт прямо из предупреждения', options: { bullet: true, breakLine: true } },
    { text: 'настоящие API 1С и ФНС', options: { bullet: true } },
  ], { x: 7.15, y: 1.75, w: 2.35, h: 3.2, fontSize: 12, color: C.text1, paraSpaceAfter: 5, margin: 0, valign: 'top', isTextBox: true, objectName: 'next list' })
  s.addNotes('Ведущий (10 с): «Что если», план-факт и ручной ввод работают полностью; источники — частично, на тестовых выгрузках. Дальше — встроить в интернет-банк: выписка у банка уже есть.')

  s = pres.addSlide({ masterName: 'DARK', sectionTitle: 'Итоги' })
  s.addText('Предупреждаем о разрыве заранее и говорим, что делать', { placeholder: 'title' })
  s.addText(`Прогноз на 30+ дней по дням · дата, сумма и вероятность разрыва · точнее «остаток не изменится» у ${Q.better}% компаний · реальный разрыв 30.09.2025 — за 14 дней`, { placeholder: 'body' })
  const qr = await QRCode.toBuffer(DEMO_URL, { errorCorrectionLevel: 'M', margin: 2, width: 600, color: { dark: '#0B3D2E', light: '#FFFFFF' } })
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 8.15, y: 4.2, w: 1.25, h: 1.25, rectRadius: 0.08, fill: { color: C.background1 }, line: { type: 'none' }, objectName: 'qr card' })
  s.addImage({ data: 'image/png;base64,' + qr.toString('base64'), x: 8.2, y: 4.25, w: 1.15, h: 1.15, objectName: 'qr prototype', altText: 'QR-код: ' + DEMO_URL })
  s.addText([
    { text: 'Прототип: ', options: { bold: true, color: C.background1 } },
    { text: DEMO_URL.replace(/\/$/, ''), options: { color: C.background1, hyperlink: { url: DEMO_URL } } },
    { text: ' → «Посмотреть демо»', options: { color: 'CFE2D6' } },
  ], { x: 0.6, y: 4.55, w: 7.4, h: 0.6, fontSize: 14, valign: 'middle', margin: 0, isTextBox: true, objectName: 'prototype link' })
  s.addNotes('Ведущий (10 с): Спасибо! Готовы ответить на вопросы.')

  await pres.writeFile({ fileName: OUT })
  await applyTheme(OUT, THEME)
  await stripUnusedTypes(OUT)
  console.log('written', OUT)
})().catch((e) => { console.error(e); process.exit(1) })
