// Rótulos, cores e ícones. Os nomes dos tipos vêm de /taxonomy (shared/taxonomia.json).

export const FAMILIES = {
  sinal: { label: 'Sinalização vertical', short: 'Sinais', color: '#C62D28', title: 'Sinalização vertical' },
  iluminacao: { label: 'Iluminação pública', short: 'Iluminação', color: '#E8A900', title: 'Iluminação pública' },
  residuos: { label: 'Resíduos', short: 'Resíduos', color: '#1E7A4C', title: 'Contentores e ecopontos' },
  mobiliario: { label: 'Bancos', short: 'Bancos', color: '#8A5A2B', title: 'Bancos' },
}

export const ACTIVE = ['auto', 'validado', 'corrigido']

export const ECO = {
  verde: '#2E8540', azul: '#1F6FD1', amarelo: '#F2C200', vermelho: '#C62D28', cinzento: '#6B6B6B', castanho: '#7A4E2D',
}

export const INSTALL = { subterraneo: 'Subterrâneo', ilha: 'Ilha de reciclagem', indiferenciado: 'Indiferenciado' }

// Chave do ícone de cada elemento
export function kindOf(p) {
  if (p.family === 'sinal') {
    if (p.subclass === 'regulatory_stop') return 'stop'
    return {
      prioridade: 'cedencia', perigo: 'perigo', proibicao: 'proibicao', obrigacao: 'obrigacao',
      informacao: 'informacao', regulamentacao: 'regulamentacao', complementar: 'complementar', orientacao: 'orientacao',
    }[p.sign_group] || 'desconhecido'
  }
  if (p.family === 'iluminacao') return p.class === 'candeeiro' ? 'candeeiro' : 'poste'
  if (p.family === 'mobiliario') return 'banco'
  if (p.class === 'subterraneo') return 'subterraneo'
  if (p.install_type === 'ilha') return 'ecoponto'
  if (p.install_type === 'indiferenciado') return 'contentor'
  return 'por_classificar'
}

const BIN = 'M11.5 14.5h17M17 14.5v-3h6v3M13.5 14.5l1.5 14h10l1.5-14'

// SVG de cada tipo (viewBox 40x40), igual ao protótipo + os tipos novos
export function iconSvg(kind, color, size = 32) {
  const open = `<svg width="${size}" height="${size}" viewBox="0 0 40 40" aria-hidden="true" style="display:block">`
  const body = {
    perigo: '<path d="M20 4.5 36.5 33.5h-33Z" fill="#FFFFFF" stroke="#C62D28" stroke-width="4" stroke-linejoin="round"/><path d="M20 15v8.5" stroke="#172033" stroke-width="2.8" stroke-linecap="round"/><circle cx="20" cy="28" r="1.7" fill="#172033"/>',
    cedencia: '<path d="M3.5 6.5h33L20 35.5Z" fill="#FFFFFF" stroke="#C62D28" stroke-width="4" stroke-linejoin="round"/>',
    stop: '<path d="M13 2.5h14l10.5 10.5v14L27 37.5H13L2.5 27V13Z" fill="#C62D28" stroke="#FFFFFF" stroke-width="2.5"/><text x="20" y="23.5" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-weight="800" font-size="9.5" fill="#FFFFFF">STOP</text>',
    obrigacao: '<circle cx="20" cy="20" r="17" fill="#1F5FAD" stroke="#FFFFFF" stroke-width="2.5"/><path d="M20 29V12M13.5 18.5 20 12l6.5 6.5" fill="none" stroke="#FFFFFF" stroke-width="3.6" stroke-linecap="round" stroke-linejoin="round"/>',
    informacao: '<rect x="3.5" y="3.5" width="33" height="33" rx="5" fill="#1F5FAD" stroke="#FFFFFF" stroke-width="2.5"/><path d="M20 18v11" stroke="#FFFFFF" stroke-width="4" stroke-linecap="round"/><circle cx="20" cy="12" r="2.6" fill="#FFFFFF"/>',
    proibicao: '<circle cx="20" cy="20" r="15.5" fill="#FFFFFF" stroke="#C62D28" stroke-width="5"/><path d="M10.5 29.5 29.5 10.5" stroke="#C62D28" stroke-width="4"/>',
    regulamentacao: '<circle cx="20" cy="20" r="15.5" fill="#FFFFFF" stroke="#C62D28" stroke-width="5"/><circle cx="20" cy="20" r="3" fill="#C62D28"/>',
    orientacao: '<rect x="2.5" y="8" width="35" height="24" rx="4" fill="#1F5FAD" stroke="#FFFFFF" stroke-width="2.5"/><path d="M12 27v-7h14" fill="none" stroke="#FFFFFF" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"/><path d="M22 15.5 26.5 20 22 24.5" fill="none" stroke="#FFFFFF" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"/>',
    complementar: '<rect x="3" y="10" width="34" height="20" rx="3" fill="#FFFFFF" stroke="#4A5468" stroke-width="2.5"/><path d="M10 17h20M10 23h13" stroke="#4A5468" stroke-width="2.6" stroke-linecap="round"/>',
    desconhecido: '<circle cx="20" cy="20" r="17" fill="#8A94A6" stroke="#FFFFFF" stroke-width="2.5"/><path d="M16 16a4 4 0 1 1 5.6 3.7c-1 .5-1.6 1.2-1.6 2.3v1" fill="none" stroke="#FFFFFF" stroke-width="3" stroke-linecap="round"/><circle cx="20" cy="28" r="1.8" fill="#FFFFFF"/>',
    candeeiro: '<circle cx="20" cy="20" r="17" fill="#E8A900" stroke="#FFFFFF" stroke-width="2.5"/><path d="M20 31V10" stroke="#172033" stroke-width="3.4" stroke-linecap="round"/><path d="M12 13h16" stroke="#172033" stroke-width="3" stroke-linecap="round"/><path d="M12 13v3.5M28 13v3.5" stroke="#172033" stroke-width="3" stroke-linecap="round"/>',
    poste: '<circle cx="20" cy="20" r="17" fill="#E8A900" stroke="#FFFFFF" stroke-width="2.5"/><path d="M15 31V15.5a4 4 0 0 1 4-4h5" fill="none" stroke="#172033" stroke-width="3" stroke-linecap="round"/><path d="M21.5 9.5h9l-2.2 4.5h-4.6Z" fill="#172033"/><path d="M26 17v2.5" stroke="#172033" stroke-width="2.2" stroke-linecap="round"/>',
    contentor: `<rect x="3.5" y="3.5" width="33" height="33" rx="9" fill="#4B5563" stroke="#FFFFFF" stroke-width="2.5"/><path d="${BIN}" fill="none" stroke="#FFFFFF" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>`,
    subterraneo: `<rect x="3.5" y="3.5" width="33" height="33" rx="9" fill="#0F5132" stroke="#FFFFFF" stroke-width="2.5"/><path d="M11.5 12.5h17M17 12.5v-3h6v3M13.5 12.5l1 10h11l1-10" fill="none" stroke="#FFFFFF" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/><path d="M9 29h22" stroke="#FFFFFF" stroke-width="3" stroke-linecap="round"/>`,
    banco: '<rect x="3.5" y="3.5" width="33" height="33" rx="9" fill="#8A5A2B" stroke="#FFFFFF" stroke-width="2.5"/><path d="M9.5 15h21M9.5 19.5h21" stroke="#FFFFFF" stroke-width="2.8" stroke-linecap="round"/><path d="M8.5 24h23M12 24v6M28 24v6" stroke="#FFFFFF" stroke-width="2.8" stroke-linecap="round"/>',
    por_classificar: `<rect x="3.5" y="3.5" width="33" height="33" rx="9" fill="#8A94A6" stroke="#FFFFFF" stroke-width="2.5" stroke-dasharray="4 3"/><path d="${BIN}" fill="none" stroke="#FFFFFF" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>`,
  }
  if (kind === 'ecoponto') {
    const fill = ECO[color] || '#1E7A4C'
    const ink = color === 'amarelo' ? '#172033' : '#FFFFFF'
    return `${open}<rect x="3.5" y="3.5" width="33" height="33" rx="9" fill="${fill}" stroke="#FFFFFF" stroke-width="2.5"/><path d="${BIN}" fill="none" stroke="${ink}" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/></svg>`
  }
  return `${open}${body[kind] || body.desconhecido}</svg>`
}


// ---------- ícones específicos de cada tipo de sinal (viewBox 40x40)
const INK = '#172033'
const RED = '#C62D28'
const BLUE = '#1F5FAD'
const st = (w = 2.6, c = INK) => `fill="none" stroke="${c}" stroke-width="${w}" stroke-linecap="round" stroke-linejoin="round"`
const txt = (t, size, color = INK, y = 25) =>
  `<text x="20" y="${y}" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-weight="800" font-size="${size}" fill="${color}">${t}</text>`

const redRing = (inner) => `<circle cx="20" cy="20" r="16" fill="#FFFFFF" stroke="${RED}" stroke-width="4.5"/>${inner}`
const slash = `<path d="M9.5 30.5 30.5 9.5" stroke="${RED}" stroke-width="3.6"/>`
const blueDisc = (inner) => `<circle cx="20" cy="20" r="17" fill="${BLUE}" stroke="#FFFFFF" stroke-width="2.5"/>${inner}`
const blueSquare = (inner) => `<rect x="3.5" y="3.5" width="33" height="33" rx="5" fill="${BLUE}" stroke="#FFFFFF" stroke-width="2.5"/>${inner}`
const warn = (inner) => `<path d="M20 4.5 36.5 33.5h-33Z" fill="#FFFFFF" stroke="${RED}" stroke-width="3.6" stroke-linejoin="round"/>${inner}`
const panel = (inner) => `<rect x="2.5" y="9" width="35" height="22" rx="3" fill="#FFFFFF" stroke="#4A5468" stroke-width="2.4"/>${inner}`

const W = '#FFFFFF'
const walker = (c = INK, dx = 0, dy = 0) =>
  `<g transform="translate(${dx} ${dy})"><circle cx="20" cy="11.5" r="2.4" fill="${c}"/><path d="M20 15v7l-4 6M20 22l4 6M16 18.5l4-1.5 4 2" ${st(2.4, c)}/></g>`
const arrowUp = (c = W) => `<path d="M20 30V12M13.5 18.5 20 12l6.5 6.5" ${st(3.6, c)}/>`
const turnRight = (c = W) => `<path d="M15 30V20a5 5 0 0 1 5-5h8" ${st(3.4, c)}/><path d="M24 10.5 28.5 15 24 19.5" ${st(3.4, c)}/>`
const turnLeft = (c = W) => `<path d="M25 30V20a5 5 0 0 0-5-5h-8" ${st(3.4, c)}/><path d="M16 10.5 11.5 15 16 19.5" ${st(3.4, c)}/>`
const bump = (c = INK, y = 27) => `<path d="M10 ${y}h5c2-6 8-6 10 0h5" ${st(2.6, c)}/>`
const bike = (c = W) =>
  `<circle cx="13" cy="25" r="4.5" ${st(2.2, c)}/><circle cx="27" cy="25" r="4.5" ${st(2.2, c)}/><path d="M13 25l5-8h7l2 8M18 17l2 8h-7M24 13h3" ${st(2.2, c)}/>`
const truck = (c = INK) => `<rect x="10" y="15" width="13" height="9" fill="${c}"/><path d="M23 18h4l3 3v3h-7Z" fill="${c}"/><circle cx="14" cy="26" r="2" fill="${c}"/><circle cx="26" cy="26" r="2" fill="${c}"/>`
const bus = (c = W) => `<rect x="12" y="11" width="16" height="16" rx="3" fill="${c}"/><rect x="14.5" y="13.5" width="11" height="6" fill="${BLUE}"/><circle cx="16" cy="29" r="1.8" fill="${c}"/><circle cx="24" cy="29" r="1.8" fill="${c}"/>`
const roundabout = (c = W) => `<path d="M20 12a8 8 0 1 1-7.4 5" ${st(3, c)}/><path d="M9.5 13.5l3 3.8 3.6-3.2" ${st(3, c)}/>`

export const SIGN_ICONS = {
  regulatory_stop: `<path d="M13 2.5h14l10.5 10.5v14L27 37.5H13L2.5 27V13Z" fill="${RED}" stroke="#FFFFFF" stroke-width="2.5"/>${txt('STOP', 9.5, W, 23.5)}`,
  regulatory_yield: `<path d="M3.5 6.5h33L20 35.5Z" fill="#FFFFFF" stroke="${RED}" stroke-width="4" stroke-linejoin="round"/>`,
  regulatory_no_entry: `<circle cx="20" cy="20" r="17" fill="${RED}" stroke="#FFFFFF" stroke-width="2.5"/><rect x="9" y="17" width="22" height="6" rx="1" fill="#FFFFFF"/>`,
  regulatory_maximum_speed_limit_30: redRing(txt('30', 15)),
  regulatory_maximum_speed_limit_40: redRing(txt('40', 15)),
  regulatory_maximum_speed_limit_50: redRing(txt('50', 15)),
  regulatory_no_parking: `<circle cx="20" cy="20" r="16" fill="${BLUE}" stroke="${RED}" stroke-width="4.5"/>${slash}`,
  regulatory_no_stopping: `<circle cx="20" cy="20" r="16" fill="${BLUE}" stroke="${RED}" stroke-width="4.5"/>${slash}<path d="M9.5 9.5 30.5 30.5" stroke="${RED}" stroke-width="3.6"/>`,
  regulatory_no_right_turn: redRing(turnRight(INK) + slash),
  regulatory_no_left_turn: redRing(turnLeft(INK) + slash),
  regulatory_road_closed_to_vehicles: redRing(''),
  regulatory_no_pedestrians: redRing(walker(INK, 0, 1) + slash),
  regulatory_no_heavy_goods_vehicles: redRing(truck()),
  regulatory_end_of_prohibition: `<circle cx="20" cy="20" r="16" fill="#FFFFFF" stroke="#4A5468" stroke-width="2.5"/><path d="M11 27 27 11M13.5 29.5 29.5 13.5M8.5 24.5 24.5 8.5" stroke="#4A5468" stroke-width="1.8"/>`,

  regulatory_go_straight: blueDisc(arrowUp()),
  regulatory_turn_right: blueDisc(turnRight()),
  regulatory_turn_left: blueDisc(turnLeft()),
  regulatory_turn_right_ahead: blueDisc(`<path d="M16 31V16h9" ${st(3.4, W)}/><path d="M21 11.5 25.5 16 21 20.5" ${st(3.4, W)}/>`),
  regulatory_turn_left_ahead: blueDisc(`<path d="M24 31V16h-9" ${st(3.4, W)}/><path d="M19 11.5 14.5 16 19 20.5" ${st(3.4, W)}/>`),
  regulatory_keep_right: blueDisc(`<path d="M13 13l14 14" ${st(3.6, W)}/><path d="M18 27h9v-9" ${st(3.6, W)}/>`),
  regulatory_roundabout: blueDisc(roundabout()),
  regulatory_bicycles_only: blueDisc(bike()),
  regulatory_one_way_straight: blueSquare(arrowUp()),

  warning_road_bump: warn(bump(INK, 27)),
  warning_roadworks: warn(`<circle cx="18" cy="14.5" r="2.2" fill="${INK}"/><path d="M18 17l-2 6 4 2v4M16 23l-4 6M17 19l6 2M23 21l4 8" ${st(2.2)}/>`),
  warning_two_way_traffic: warn(`<path d="M16 29V15M13 18l3-3 3 3M24 15v14M21 26l3 3 3-3" ${st(2.2)}/>`),
  warning_road_narrows: warn(`<path d="M15 29v-5l2-5v-5M25 29v-5l-2-5v-5" ${st(2.4)}/>`),
  warning_road_narrows_left: warn(`<path d="M15 29v-5l3-5v-5M25 29V14" ${st(2.4)}/>`),
  warning_road_narrows_right: warn(`<path d="M15 29V14M25 29v-5l-3-5v-5" ${st(2.4)}/>`),
  warning_railroad_crossing_without_barriers: warn(`<rect x="12" y="17" width="16" height="8" rx="2" fill="${INK}"/><circle cx="15" cy="27" r="1.8" fill="${INK}"/><circle cx="25" cy="27" r="1.8" fill="${INK}"/><path d="M17 15h6" ${st(2)}/>`),
  warning_pedestrians_crossing: warn(walker(INK, 0, 5)),
  warning_roundabout: warn(`<path d="M20 15.5a6 6 0 1 1-5.6 3.8" ${st(2.4)}/><path d="M13 16.5l1.6 3 2.8-1.8" ${st(2.4)}/>`),
  warning_children: warn(walker(INK, -4, 6) + walker(INK, 4, 7)),
  warning_other_danger: warn(`<path d="M20 15v8.5" stroke="${INK}" stroke-width="2.8" stroke-linecap="round"/><circle cx="20" cy="28" r="1.7" fill="${INK}"/>`),

  information_parking: blueSquare(txt('P', 22, W, 28)),
  information_pedestrians_crossing: blueSquare(`<path d="M7 31h26L20 9Z" fill="#FFFFFF"/>${walker(INK, 0, 7)}`),
  information_road_bump: blueSquare(bump(W, 25)),
  information_tram_bus_stop: blueSquare(bus()),
  information_hospital: blueSquare(`<rect x="10" y="10" width="20" height="20" rx="2" fill="#FFFFFF"/>${txt('H', 17, BLUE, 26)}`),
  information_dead_end: blueSquare(`<path d="M20 31V15" stroke="#FFFFFF" stroke-width="6"/><path d="M12 13h16" stroke="${RED}" stroke-width="5"/>`),
  information_motorway: blueSquare(`<path d="M12 31l5-20M28 31l-5-20M20 13v4M20 21v4M20 29v2" ${st(2.4, W)}/>`),
  information_end_of_motorway: blueSquare(`<path d="M12 31l5-20M28 31l-5-20" ${st(2.4, W)}/><path d="M9 31 31 9" stroke="${RED}" stroke-width="3"/>`),
  information_outro: blueSquare(`<path d="M20 18v11" stroke="#FFFFFF" stroke-width="4" stroke-linecap="round"/><circle cx="20" cy="12" r="2.6" fill="#FFFFFF"/>`),

  complementary_distance: panel(txt('100 m', 10, INK, 23.5)),
  complementary_tow_away_zone: panel(`<path d="M8 25h16v-6h-5l-3 3H8Z" fill="${INK}"/><path d="M24 22l7-7v8" ${st(2)}/><circle cx="12" cy="26" r="2" fill="${INK}"/><circle cx="21" cy="26" r="2" fill="${INK}"/>`),
}

function wrapSvg(body, size) {
  return `<svg width="${size}" height="${size}" viewBox="0 0 40 40" aria-hidden="true" style="display:block;overflow:visible">${body}</svg>`
}

// Ícone de um elemento: o desenho do tipo de sinal quando existe (sem números por cima;
// o número de contentores de uma ilha aparece só no detalhe)
export function iconFor(p, size = 32) {
  if (p.family === 'sinal' && SIGN_ICONS[p.subclass]) return wrapSvg(SIGN_ICONS[p.subclass], size)
  return iconSvg(kindOf(p), p.color, size)
}

// Chave para agrupar ícones iguais (cache dos marcadores e legenda)
// Chave do tipo de sinal nos filtros: o grupo + o tipo. Na regulamentação, "desconhecido" e "regulatory_outro"
// juntam-se num só "por identificar"
export const POR_IDENTIFICAR = 'por_identificar'
// confiança mínima nos filtros: só para sinais e resíduos (os detetores com mais falsos positivos)
export const CONF_FAMILIES = ['sinal', 'residuos', 'iluminacao', 'mobiliario']
export function typeKey(p) {
  const k = kindOf(p)
  const sub = k === 'regulamentacao' && (!p.subclass || p.subclass === 'desconhecido' || p.subclass === 'regulatory_outro')
    ? POR_IDENTIFICAR : p.subclass
  return `${k}:${sub}`
}

export function iconKey(p) {
  if (p.family === 'sinal' && SIGN_ICONS[p.subclass]) return p.subclass
  return `${kindOf(p)}|${p.color || ''}|${p.family === 'residuos' && p.n_units > 1 ? p.n_units : ''}`
}

// Legenda e filtros: ordem e nomes dos tipos de ícone
export const KIND_LABELS = {
  stop: 'STOP', cedencia: 'Cedência de passagem', proibicao: 'Proibição', obrigacao: 'Obrigação',
  regulamentacao: 'Regulamentação (tipo por identificar)', perigo: 'Perigo', informacao: 'Informação',
  complementar: 'Painéis complementares', orientacao: 'Orientação e outros', desconhecido: 'Sinal não identificado',
  candeeiro: 'Candeeiro', poste: 'Poste de iluminação',
  subterraneo: 'Contentor subterrâneo', ecoponto: 'Ecoponto (ilha de reciclagem)', contentor: 'Contentor de indiferenciados',
  por_classificar: 'Contentor por classificar',
  banco: 'Banco',
}
export const KIND_ORDER = {
  sinal: ['stop', 'cedencia', 'proibicao', 'obrigacao', 'regulamentacao', 'perigo', 'informacao', 'complementar', 'orientacao', 'desconhecido'],
  iluminacao: ['candeeiro', 'poste'],
  residuos: ['subterraneo', 'ecoponto', 'contentor', 'por_classificar'],
  mobiliario: ['banco'],
}

export function subLabel(p) {
  if (p.family === 'sinal') return p.sign_group_label || 'Sinal'
  if (p.family === 'iluminacao' || p.family === 'mobiliario') return p.class_label
  return [p.class_label, p.class === 'contentor' ? p.install_label : null].filter(Boolean).join(' · ')
}

export function confPct(p) {
  return p.confidence_pct ?? Math.round(100 * (p.confidence || 0))
}

export function confColor(pct) {
  return pct >= 85 ? '#1E7A4C' : pct >= 70 ? '#8A5A00' : '#B42318'
}

export const coordsOf = (p) => `${p.lat.toFixed(6)}, ${p.lon.toFixed(6)}`

export function fmtDate(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleDateString('pt-PT')
}

export const isVerified = (p) => p.status === 'validado' || p.status === 'corrigido'

// Tipos de sinal de um grupo (para o editor)
export function signTypes(tax, group) {
  if (!tax) return []
  return Object.entries(tax.familias.sinal.tipos)
    .filter(([, t]) => t.grupo === group)
    .map(([key, t]) => ({ key, nome: t.nome, codigo: t.codigo }))
}

export function signGroups(tax) {
  if (!tax) return []
  return Object.entries(tax.familias.sinal.grupos).filter(([k]) => k !== 'desconhecido')
}
