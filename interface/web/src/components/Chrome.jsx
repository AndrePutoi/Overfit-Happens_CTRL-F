// Barra lateral, cabeçalho e painéis (filtros, legenda, ajuda, perfil)
import { useEffect, useState } from 'react'
import { api, DEFAULT_TOKEN } from '../api'
import { CloseButton, Icon } from './common'
import { CONF_FAMILIES, ECO, FAMILIES, KIND_LABELS, KIND_ORDER, POR_IDENTIFICAR, iconKey, kindOf, typeKey } from '../tax'

const svg = (children) => (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {children}
  </svg>
)
const CAT_ICONS = {
  todos: svg(<><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /></>),
  sinal: svg(<><path d="M12 3 21 19H3Z" /><path d="M12 10v4" /><path d="M12 17h.01" /></>),
  iluminacao: svg(<><path d="M7 22V7a3 3 0 0 1 3-3h7" /><path d="M14 4h7l-1.5 3h-4Z" /><path d="M17.5 10v2" /><path d="M4 22h6" /></>),
  mobiliario: svg(<><path d="M4 9h16M4 13h16" /><path d="M3 17h18M6 17v4M18 17v4" /></>),
  residuos: svg(<><path d="M4 7h16" /><path d="M10 7V4h4v3" /><path d="M6 7l1 14h10l1-14" /><path d="M10 11v6M14 11v6" /></>),
}

export function Logo() {
  return (
    <svg width="52" height="52" viewBox="0 0 100 100" role="img" aria-label="CTRL+F">
      <rect width="100" height="100" rx="20" fill="#1F5FAD" />
      <rect x="6" y="6" width="88" height="88" rx="15" fill="none" stroke="#FFFFFF" strokeWidth="3" />
      <path d="M62 62l16 16" stroke="#FFFFFF" strokeWidth="11" strokeLinecap="round" />
      <circle cx="44" cy="44" r="23" fill="#FFFFFF" fillOpacity="0.14" stroke="#FFFFFF" strokeWidth="7" />
      <path d="M44 30.5 56.5 52h-25Z" fill="#FFFFFF" stroke="#C62D28" strokeWidth="4.5" strokeLinejoin="round" />
      <path d="M44 38.5v5.5" stroke="#10233F" strokeWidth="2.4" strokeLinecap="round" />
      <circle cx="44" cy="47.6" r="1.4" fill="#10233F" />
    </svg>
  )
}

export function Rail({ cat, setCat, panel, togglePanel, filterCount, initials }) {
  const cats = [['todos', 'Todos'], ['sinal', 'Sinais'], ['iluminacao', 'Iluminação'], ['residuos', 'Resíduos'], ['mobiliario', 'Bancos']]
  return (
    <nav className="rail" aria-label="Navegação principal">
      <Logo />
      <div className="rail-sep" />
      <div className="rail-label">MOSTRAR</div>
      {cats.map(([k, label]) => (
        <button key={k} className={`rail-btn${cat === k ? ' on' : ''}`} aria-pressed={cat === k} onClick={() => setCat(k)}>
          {CAT_ICONS[k]}
          <span>{label}</span>
        </button>
      ))}
      <div className="rail-sep" />
      <button className={`rail-btn${panel === 'filtros' ? ' on' : ''}`} aria-expanded={panel === 'filtros'} onClick={() => togglePanel('filtros')}>
        {svg(<path d="M3 5h18l-7 8.5V19l-4 2v-7.5Z" />)}
        <span>Filtros</span>
        {filterCount > 0 && <b className="rail-count">{filterCount}</b>}
      </button>
      <button className={`rail-btn${panel === 'legenda' ? ' on' : ''}`} aria-expanded={panel === 'legenda'} onClick={() => togglePanel('legenda')}>
        {svg(<><circle cx="5.5" cy="6" r="2" /><circle cx="5.5" cy="12" r="2" /><circle cx="5.5" cy="18" r="2" /><path d="M10 6h10M10 12h10M10 18h10" /></>)}
        <span>Legenda</span>
      </button>
      <div className="grow" />
      <button className={`rail-round${panel === 'ajuda' ? ' on' : ''}`} aria-label="Ajuda e licenças" onClick={() => togglePanel('ajuda')}>
        {svg(<><circle cx="12" cy="12" r="9" /><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .8-1 1.5V14" /><path d="M12 17h.01" /></>)}
      </button>
      <button className={`avatar-btn${panel === 'perfil' ? ' on' : ''}`} aria-label="Perfil" onClick={() => togglePanel('perfil')}>
        {initials || (
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
            <circle cx="12" cy="8" r="4" /><path d="M4 21c0-4 3.6-6.5 8-6.5s8 2.5 8 6.5" />
          </svg>
        )}
      </button>
    </nav>
  )
}

export function Header({ tab, setTab, pending, zone, onExport, isTech, complaintsOpen = 0 }) {
  const tabs = isTech
    ? [['mapa', 'Mapa'], ['catalogo', 'Catálogo'], ['rever', 'Por rever'], ['reclamacoes', 'Reclamações'], ['importar', 'Importar imagens']]
    : [['mapa', 'Mapa'], ['reclamacoes', 'Reclamações']]
  return (
    <header className="header">
      <div className="wordmark">CTRL<span>+</span>F</div>
      {tabs.map(([k, label]) => (
        <button key={k} className={`tab${tab === k ? ' on' : ''}`} aria-current={tab === k ? 'page' : undefined} onClick={() => setTab(k)}>
          {label}
          {k === 'rever' && pending > 0 && <span className="tab-badge">{pending}</span>}
          {k === 'reclamacoes' && isTech && complaintsOpen > 0 && <span className="tab-badge">{complaintsOpen}</span>}
        </button>
      ))}
      <div className="grow" />
      {zone && (
        <div className="zone-pill">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#1F5FAD" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M12 21s-7-6.2-7-11a7 7 0 0 1 14 0c0 4.8-7 11-7 11Z" /><circle cx="12" cy="10" r="2.5" />
          </svg>
          <span className="zone-txt" title={`Zona piloto: ${zone}`}>Zona piloto: {zone}</span>
        </div>
      )}
      {isTech ? (
        <button className="btn btn-primary" onClick={onExport}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M12 4v11" /><path d="m7 10 5 5 5-5" /><path d="M5 20h14" />
          </svg>
          Exportar GeoJSON / CSV
        </button>
      ) : (
        <span className="public-badge">Mapa público · só elementos verificados</span>
      )}
    </header>
  )
}

function Drawer({ title, sub, onClose, children, foot, width }) {
  return (
    <div className="drawer" role="dialog" aria-label={title} style={width ? { width } : undefined}>
      <div className="drawer-head">
        <div>
          <h2>{title}</h2>
          {sub && <div className="drawer-sub">{sub}</div>}
        </div>
        <CloseButton onClick={onClose} label={`Fechar ${title.toLowerCase()}`} />
      </div>
      <div className="drawer-body">{children}</div>
      {foot && <div className="drawer-foot">{foot}</div>}
    </div>
  )
}

function Chevron({ dir = 'down', double = false, size = 18 }) {
  const rot = { down: 0, up: 180, left: 90, right: -90 }[dir]
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round"
      strokeLinejoin="round" aria-hidden="true" style={{ transform: `rotate(${rot}deg)`, transition: 'transform 0.15s' }}>
      {double ? <><path d="m7 6 5 5 5-5" /><path d="m7 13 5 5 5-5" /></> : <path d="m6 9 6 6 6-6" />}
    </svg>
  )
}
export { Chevron }

// Linha deslizante 0–100 % para uma família. Mostra o valor enquanto se arrasta
// e só aplica o filtro quando se pára (o mapa não é redesenhado a cada píxel)
function ConfSlider({ fam, value, onCommit, countFor, total }) {
  const [v, setV] = useState(value)
  useEffect(() => { setV(value) }, [value])
  useEffect(() => {
    if (v === value) return undefined
    const t = setTimeout(() => onCommit(v), 250)
    return () => clearTimeout(t)
  }, [v]) // eslint-disable-line react-hooks/exhaustive-deps
  const n = v > 0 ? countFor(v) : total
  return (
    <div className="conf-slider">
      <div className="conf-head">
        <span className="conf-fam"><span className="dot" style={{ background: FAMILIES[fam].color }} />{FAMILIES[fam].short}</span>
        <span className="conf-val">{v > 0 ? `≥ ${v}%` : 'Todos'} · {n} de {total}</span>
      </div>
      <input type="range" min="0" max="100" step="5" value={v}
        aria-label={`Confiança mínima de ${FAMILIES[fam].short}`}
        style={{ '--pct': `${v}%`, '--cor': FAMILIES[fam].color }}
        onChange={(e) => setV(Number(e.target.value))} />
    </div>
  )
}

function FilterOption({ on, onClick, icon, swatch, label, count, sub, expand }) {
  return (
    <div className={`fopt-row${sub ? ' sub' : ''}`}>
      <button className={`fopt${on ? ' on' : ''}`} aria-pressed={on} onClick={onClick}>
        <span style={{ width: 24, display: 'flex', justifyContent: 'center' }}>
          {icon}
          {swatch && <span className="swatch" style={{ background: swatch, width: 16, height: 16 }} />}
        </span>
        <span className="label">{label}</span>
        <span className="count">{count}</span>
        <span className="check">✓</span>
      </button>
      {expand && (
        <button className={`fopt-expand${expand.open ? ' open' : ''}`} onClick={expand.onClick}
          aria-expanded={expand.open} aria-label={expand.open ? 'Esconder os tipos' : 'Ver os tipos'} title={expand.open ? 'Esconder os tipos' : 'Ver os tipos'}>
          <Chevron dir={expand.open ? 'up' : 'down'} />
        </button>
      )}
    </div>
  )
}

export function FiltersDrawer({ cat, filters, toggle, clear, base, visibleCount, onClose, tax, titleText, isTech, showArea, setShowArea }) {
  const count = (pred) => base.filter(pred).length
  // grupos abertos: começam abertos os que têm tipos escolhidos
  const [expanded, setExpanded] = useState(() => new Set(base.filter((p) => filters.types.has(typeKey(p))).map(kindOf)))
  const toggleExpand = (k) => setExpanded((e) => { const n = new Set(e); n.has(k) ? n.delete(k) : n.add(k); return n })
  // tipos de sinal presentes em cada grupo, do mais comum para o menos comum
  const typesOf = (k) => {
    const m = {}
    base.forEach((p) => {
      if (p.family !== 'sinal' || kindOf(p) !== k || !p.subclass) return
      const key = typeKey(p)
      const name = key.endsWith(`:${POR_IDENTIFICAR}`) ? 'Tipo por identificar' : p.name
      if (!m[key]) m[key] = { key, name, sample: p, n: 0 }
      m[key].n += 1
    })
    return Object.values(m).sort((a, b) => b.n - a.n)
  }
  const families = cat === 'todos' ? ['sinal', 'iluminacao', 'residuos', 'mobiliario'] : [cat]
  const colors = tax ? Object.entries(tax.cores_ecoponto) : []
  return (
    <Drawer title="Filtros" sub={titleText} onClose={onClose}
      foot={<><button className="btn btn-ghost" onClick={clear}>Limpar</button><button className="btn btn-dark" onClick={onClose}>Ver {visibleCount}</button></>}>
      {families.map((fam) => (
        <div key={fam}>
          <div className="group-title"><span className="dot" style={{ background: FAMILIES[fam].color }} />{FAMILIES[fam].label.toUpperCase()}</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 10 }}>
            {KIND_ORDER[fam].map((k) => {
              const n = count((p) => kindOf(p) === k)
              if (!n && !filters.kinds.has(k)) return null
              const subs = fam === 'sinal' ? typesOf(k) : []
              const open = expanded.has(k)
              return (
                <div key={k} style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  <FilterOption on={filters.kinds.has(k)} onClick={() => toggle('kinds', k)} icon={<Icon kind={k} color="azul" size={22} />}
                    label={KIND_LABELS[k]} count={n}
                    expand={subs.length > 1 ? { open, onClick: () => toggleExpand(k) } : null} />
                  {open && subs.map((t) => (
                    <FilterOption key={t.key} sub on={filters.types.has(t.key)} onClick={() => toggle('types', t.key)}
                      icon={<Icon el={t.sample} size={22} />} label={t.name} count={t.n} />
                  ))}
                </div>
              )
            })}
          </div>
        </div>
      ))}
      {families.some((f) => CONF_FAMILIES.includes(f)) && (
        <div>
          <div className="group-title"><span className="dot" style={{ background: '#B42318' }} />CONFIANÇA MÍNIMA</div>
          <p className="cf-note" style={{ margin: '6px 0 0' }}>Esconde as deteções menos seguras de cada família. Não apaga nada: ao limpar o filtro voltam a aparecer.</p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14, marginTop: 12 }}>
            {families.filter((f) => CONF_FAMILIES.includes(f)).map((fam) => {
              const atual = [...filters.conf].find((c) => c.startsWith(`${fam}:`))
              return (
                <ConfSlider key={fam} fam={fam} value={atual ? Number(atual.split(':')[1]) : 0}
                  onCommit={(v) => toggle('confset', `${fam}:${v}`)}
                  countFor={(v) => count((p) => p.family === fam && Math.round((p.confidence ?? 0) * 100) >= v)}
                  total={count((p) => p.family === fam)} />
              )
            })}
          </div>
        </div>
      )}
      {setShowArea && (
        <div>
          <div className="group-title"><span className="dot" style={{ background: '#1F5FAD' }} />MAPA</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 10 }}>
            <FilterOption on={showArea} onClick={() => setShowArea(!showArea)} label="Mostrar limite da zona piloto (tracejado)" />
          </div>
        </div>
      )}
      <div>
        <div className="group-title"><span className="dot" style={{ background: '#1F5FAD' }} />POSIÇÃO</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 10 }}>
          <FilterOption on={filters.position.has('fiavel')} onClick={() => toggle('position', 'fiavel')} label="Triangulada (várias câmaras)" count={count((p) => p.position_reliable)} />
          <FilterOption on={filters.position.has('aproximada')} onClick={() => toggle('position', 'aproximada')} label="Aproximada (vista numa só imagem)" count={count((p) => !p.position_reliable)} />
        </div>
      </div>
      {isTech && <div>
        <div className="group-title"><span className="dot" style={{ background: '#14532D' }} />REVISÃO</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 10 }}>
          <FilterOption on={filters.review.has('por_rever')} onClick={() => toggle('review', 'por_rever')} label="Por rever" count={count((p) => p.status === 'auto')} />
          <FilterOption on={filters.review.has('verificado')} onClick={() => toggle('review', 'verificado')} label="Verificados" count={count((p) => p.status === 'validado' || p.status === 'corrigido')} />
          <FilterOption on={filters.review.has('rejeitado')} onClick={() => toggle('review', 'rejeitado')} label="Rejeitados" count={count((p) => p.status === 'rejeitado')} />
          <FilterOption on={filters.dup.has('sim')} onClick={() => toggle('dup', 'sim')} label="Só possíveis duplicados" count={count((p) => p._dup)} />
        </div>
      </div>}
    </Drawer>
  )
}

export function LegendDrawer({ visible, hasFilters, onClose }) {
  // um item por desenho de ícone (tipo de sinal, cor de ecoponto, contentores juntos...)
  const byKey = {}
  visible.forEach((p) => {
    const k = iconKey(p)
    if (!byKey[k]) byKey[k] = { p, n: 0 }
    byKey[k].n += 1
  })
  const label = (p) => {
    if (p.family === 'sinal') return p.name
    const k = kindOf(p)
    if (k === 'ecoponto') return 'Ecoponto (ilha de reciclagem)'
    const base = KIND_LABELS[k]
    return p.family === 'residuos' && p.n_units > 1 ? `${base} · ${p.n_units} juntos` : base
  }
  const groups = Object.keys(KIND_ORDER).map((fam) => ({
    fam,
    items: Object.entries(byKey).filter(([, v]) => v.p.family === fam).sort((a, b) => b[1].n - a[1].n),
  })).filter((g) => g.items.length)
  return (
    <Drawer title="Legenda" sub={hasFilters ? 'Só o que está selecionado nos filtros' : 'Tudo o que está visível no mapa'} onClose={onClose} width={340}>
      {groups.map((g) => (
        <div key={g.fam}>
          <div className="group-title">{FAMILIES[g.fam].label.toUpperCase()}</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 8 }}>
            {g.items.map(([k, v]) => (
              <div key={k} className="legend-item">
                <Icon el={v.p} size={30} />
                <span><b>{label(v.p)}</b><small>{v.n} {v.n === 1 ? 'elemento' : 'elementos'} no mapa</small></span>
              </div>
            ))}
          </div>
        </div>
      ))}
      {!groups.length && <p className="empty">Não há elementos visíveis com os filtros atuais.</p>}
      <div>
        <div className="group-title">POSIÇÃO</div>
        <p style={{ fontSize: 13, color: '#3B4658', lineHeight: 1.5, margin: '8px 0 0' }}>
          Ao selecionar um elemento, o círculo à volta mostra a incerteza da posição: contínuo e verde se foi triangulada por várias câmaras,
          tracejado e laranja se vem de uma só imagem. Os pontos azuis são as câmaras que o viram.
        </p>
      </div>
    </Drawer>
  )
}

const HELP = [
  ['Ver o mapa', 'Escolha Todos, Sinais, Iluminação ou Resíduos na barra azul. Clique num símbolo no mapa ou numa linha da lista para ver o detalhe à direita, com a imagem onde foi detetado.'],
  ['Filtrar e ver a legenda', 'Em Filtros escolha os tipos que quer ver, por exemplo só STOP e cedência de passagem, só subterrâneos ou só posições trianguladas. Em Legenda vê o significado dos símbolos.'],
  ['Validar ou corrigir', 'No painel do elemento, carregue em Validar se a deteção estiver certa. Use Corrigir para mudar o tipo ou a cor e depois Guardar correção. Ajustar posição deixa arrastar o símbolo no mapa.'],
  ['Duplicados e imagens', 'Se o mesmo objeto aparece duas vezes, junte-os na caixa amarela. Se uma imagem mostra outro objeto, use Separar esta imagem. A estrela marca a imagem principal.'],
  ['Rever deteções', 'O separador Por rever mostra as deteções automáticas da menor para a maior confiança. Pode validar, corrigir, rejeitar falsos positivos ou juntar duplicados.'],
  ['Importar e exportar', 'Em Importar imagens envie vídeos de rua ou peça imagens do Mapillary.\nNo Catálogo exporte em GeoJSON ou CSV, com os filtros ativos.'],
]

export function HelpDrawer({ onClose, config }) {
  const [open, setOpen] = useState(0)
  const sources = (config?.sources || []).filter((s) => s.enabled)
  return (
    <Drawer title="Ajuda" onClose={onClose} width={380}>
      <p style={{ margin: '12px 0 0', fontSize: 14, lineHeight: 1.5, color: '#3B4658' }}>
        O CTRL+F deteta sinais, iluminação, contentores e ecopontos em imagens de rua e coloca-os no mapa.
      </p>
      {HELP.map(([t, text], i) => (
        <div key={t} className={`help-item${open === i ? ' open' : ''}`}>
          <button aria-expanded={open === i} onClick={() => setOpen(open === i ? -1 : i)}>
            {t}<span>{open === i ? '−' : '+'}</span>
          </button>
          {open === i && <p>{text}</p>}
        </div>
      ))}
      <div className="note">
        <b>Fontes e licenças</b>
        {sources.map((s) => (
          <span key={s.key}>
            <a href={s.url || '#'} target="_blank" rel="noreferrer">{s.name}</a> — {s.license}. {s.attribution}
          </span>
        ))}
        <span>Mapa de fundo © colaboradores do OpenStreetMap (ODbL). Mapa feito com Leaflet.</span>
        <span>Google Street View: desligado. Os termos do Google Maps Platform não permitem guardar as imagens, treinar modelos com elas nem mostrá-las sobre um mapa que não seja da Google.</span>
      </div>
      <div className="note">
        <b>Privacidade</b>
        <span>Rostos e matrículas são desfocados antes de guardar; só se mostram imagens desfocadas.</span>
      </div>
    </Drawer>
  )
}

export function ProfilePopover({ me, isTech, onReview, onLogout, municipality }) {
  if (!isTech) {
    return (
      <div className="profile" role="dialog" aria-label="Perfil">
        <div className="profile-head">
          <span className="profile-avatar" style={{ background: '#5A6478' }}>?</span>
          <div>
            <div style={{ fontSize: 16, fontWeight: 800 }}>Visitante</div>
            <div style={{ fontSize: 13, color: '#4A5468' }}>Perfil público</div>
            {municipality && <div style={{ fontSize: 12, color: '#5A6478' }}>Município de {municipality}</div>}
          </div>
        </div>
        <p style={{ margin: 0, padding: '12px 18px', fontSize: 13, lineHeight: 1.45, color: '#3B4658', borderBottom: '1px solid #EDF0F4' }}>
          Vê só os elementos já confirmados por um técnico da câmara.
        </p>
        <div className="profile-menu">
          <button onClick={onLogout}>Entrar como técnico</button>
        </div>
      </div>
    )
  }
  return (
    <div className="profile" role="dialog" aria-label="Perfil">
      <div className="profile-head">
        <span className="profile-avatar">{me?.initials || '—'}</span>
        <div>
          <div style={{ fontSize: 16, fontWeight: 800 }}>{me?.name || '—'}</div>
          <div style={{ fontSize: 13, color: '#4A5468' }}>{me?.role}</div>
          {municipality && <div style={{ fontSize: 12, color: '#5A6478' }}>Município de {municipality}</div>}
        </div>
      </div>
      <div className="profile-stats">
        <div><b>{me?.validated_today ?? 0}</b><span>validados hoje</span></div>
        <div><b>{me?.corrected_today ?? 0}</b><span>corrigidos hoje</span></div>
      </div>
      <div className="profile-menu">
        <button onClick={onReview}>Ver a fila por rever</button>
        <button className="danger" onClick={onLogout}>Terminar sessão</button>
      </div>
    </div>
  )
}

export function Login({ onEnter }) {
  const [token, setTokenText] = useState(DEFAULT_TOKEN)
  // nome do município vem da configuração (/config é pública), para servir a qualquer câmara
  const [municipality, setMunicipality] = useState(null)
  useEffect(() => {
    api.config().then((c) => setMunicipality(c?.municipality?.name || null)).catch(() => {})
  }, [])
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const go = async (mode) => {
    setBusy(true)
    setError(null)
    try {
      await onEnter(mode, token.trim())
    } catch (e) {
      setError(e.message.includes('Token') ? 'Código de acesso inválido.' : `Não foi possível ligar à API: ${e.message}`)
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="login">
      <div className="login-card">
        <Logo />
        <div className="wordmark" style={{ fontSize: 34, margin: 0 }}>CTRL<span>+</span>F</div>
        <p className="login-sub">Mapa do mobiliário urbano{municipality ? ` de ${municipality}` : ''}</p>
        <div className="login-option">
          <b>Técnico da câmara</b>
          <span>Rever, corrigir e validar as deteções, exportar o catálogo e importar imagens.</span>
          <label className="field">Código de acesso
            <input type="text" value={token} onChange={(e) => setTokenText(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && go('tecnico')} />
          </label>
          <button className="btn btn-dark" disabled={busy || !token.trim()} onClick={() => go('tecnico')}>Entrar como técnico</button>
        </div>
        <div className="login-option">
          <b>Público</b>
          <span>Ver no mapa os sinais, a iluminação e os contentores já verificados pela câmara.</span>
          <button className="btn btn-outline" disabled={busy} onClick={() => go('publico')}>Ver o mapa público</button>
        </div>
        {error && <div className="flash err" style={{ margin: 0 }}>{error}</div>}
      </div>
    </div>
  )
}
