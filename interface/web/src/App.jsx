import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, DEFAULT_TOKEN, download, exportPath, setToken } from './api'
import { ACTIVE, FAMILIES, POR_IDENTIFICAR, kindOf, typeKey } from './tax'
import { FiltersDrawer, Header, HelpDrawer, LegendDrawer, Login, ProfilePopover, Rail } from './components/Chrome'
import MapPage from './components/MapPage'
import { CatalogPage, HistoryPage, ImportPage, ReviewPage } from './components/Pages'
import { ComplaintsPage, distanceM } from './components/Complaints'

const MODE_KEY = 'ctrlf_modo'
function savedMode() {
  try {
    return sessionStorage.getItem(MODE_KEY)
  } catch {
    return null
  }
}
function saveMode(m) {
  try {
    if (m) sessionStorage.setItem(MODE_KEY, m)
    else sessionStorage.removeItem(MODE_KEY)
  } catch {
    /* sem armazenamento: o modo dura só até recarregar */
  }
}

const emptyFilters = () => ({ kinds: new Set(), types: new Set(), colors: new Set(), position: new Set(), review: new Set(), dup: new Set(), conf: new Set() })
const TITLES = { todos: 'Mobiliário urbano', sinal: FAMILIES.sinal.title, iluminacao: FAMILIES.iluminacao.title, residuos: FAMILIES.residuos.title, mobiliario: FAMILIES.mobiliario.title }

export default function App() {
  // 'tecnico' (pode rever e corrigir) ou 'publico' (só vê o que já foi verificado)
  const [mode, setMode] = useState(() => {
    const m = savedMode()
    setToken(m === 'tecnico' ? DEFAULT_TOKEN : null)
    return m
  })
  const isTech = mode === 'tecnico'
  const [tax, setTax] = useState(null)
  const [config, setConfig] = useState(null)
  // mostrar/esconder o limite (tracejado) da zona piloto no mapa; guardado no separador do browser
  const [showArea, setShowAreaState] = useState(() => {
    try { return sessionStorage.getItem('ctrlf_zona') !== 'off' } catch { return true }
  })
  const setShowArea = (v) => {
    setShowAreaState(v)
    try { sessionStorage.setItem('ctrlf_zona', v ? 'on' : 'off') } catch { /* sem armazenamento */ }
  }
  const [features, setFeatures] = useState(null)
  const [stats, setStats] = useState(null)
  const [me, setMe] = useState(null)
  const [loadError, setLoadError] = useState(null)

  const [tab, setTab] = useState('mapa')
  const [cat, setCat] = useState('todos')
  const [filters, setFilters] = useState(emptyFilters)
  const [query, setQuery] = useState('')
  const [panel, setPanel] = useState(null)
  const [selId, setSelId] = useState(null)
  const [revId, setRevId] = useState(null)
  const [detail, setDetail] = useState(null)
  const [detailVersion, setDetailVersion] = useState(0)
  const [flash, setFlash] = useState(null)
  const [toast, setToast] = useState(null)
  const [busy, setBusy] = useState(false)
  const [moving, setMoving] = useState(false)
  // reclamações: lista, ponto escolhido no mapa (posição proposta) e filtro por elemento
  const [complaints, setComplaints] = useState(null)
  const [picking, setPicking] = useState(false)
  const [picked, setPicked] = useState(null)
  const [complaintEl, setComplaintEl] = useState(null)

  // ---------- carregar dados
  const loadElements = useCallback(() => api.elements().then((fc) => setFeatures(fc.features)), [])
  const loadSide = useCallback(() => {
    if (mode !== 'tecnico') return
    api.stats().then(setStats).catch(() => {})
    api.me().then(setMe).catch(() => setMe(null))
  }, [mode])
  const loadComplaints = useCallback(() => api.complaints().then(setComplaints).catch(() => {}), [])
  useEffect(() => {
    if (!mode) return
    setComplaints(null)
    loadComplaints()
    setFeatures(null)
    setLoadError(null)
    Promise.all([api.taxonomy(), api.config(), loadElements()])
      .then(([t, c]) => { setTax(t); setConfig(c) })
      .catch((e) => setLoadError(e.message))
    loadSide()
  }, [mode, loadElements, loadSide, loadComplaints])

  const enter = async (m, token) => {
    setToken(m === 'tecnico' ? token : null)
    if (m === 'tecnico') {
      try {
        await api.me()
      } catch (e) {
        setToken(null)
        throw e
      }
    }
    saveMode(m)
    setSelId(null)
    setRevId(null)
    setTab('mapa')
    setFilters(emptyFilters())
    setPanel(null)
    setMe(null)
    setStats(null)
    setMode(m)
  }
  const leave = () => {
    setToken(null)
    saveMode(null)
    setMode(null)
    setPanel(null)
  }

  // ---------- elementos derivados
  const all = useMemo(() => {
    if (!features) return []
    const props = features.map((f) => f.properties)
    const groupCount = {}
    props.forEach((p) => {
      if (p.duplicate_group_id && ACTIVE.includes(p.status)) groupCount[p.duplicate_group_id] = (groupCount[p.duplicate_group_id] || 0) + 1
    })
    props.forEach((p) => { p._dup = isTech && !!p.duplicate_group_id && ACTIVE.includes(p.status) && groupCount[p.duplicate_group_id] > 1 })
    return props
  }, [features, isTech])
  const byId = useMemo(() => Object.fromEntries(all.map((p) => [p.id, p])), [all])

  const statusOk = useCallback((p) => {
    if (!filters.review.size) return ACTIVE.includes(p.status)
    return (filters.review.has('por_rever') && p.status === 'auto')
      || (filters.review.has('verificado') && (p.status === 'validado' || p.status === 'corrigido'))
      || (filters.review.has('rejeitado') && p.status === 'rejeitado')
  }, [filters.review])

  const inCat = useCallback((p) => cat === 'todos' || p.family === cat, [cat])
  const passFilters = useCallback((p) => {
    if (!statusOk(p)) return false
    // grupos (kinds) e tipos de sinal (types) combinam com OU
    if ((filters.kinds.size || filters.types.size) && !filters.kinds.has(kindOf(p)) && !filters.types.has(typeKey(p))) return false
    if (filters.colors.size && !filters.colors.has(p.color)) return false
    if (filters.position.size && !filters.position.has(p.position_reliable ? 'fiavel' : 'aproximada')) return false
    if (filters.dup.size && !p._dup) return false
    // confiança mínima por família: valores "familia:percentagem"
    for (const c of filters.conf) {
      const [fam, v] = c.split(':')
      if (p.family === fam && Math.round((p.confidence ?? 0) * 100) < Number(v)) return false
    }
    return true
  }, [filters, statusOk])
  const q = query.trim().toLowerCase()
  const inQuery = useCallback((p) => !q || `${p.id} ${p.name} ${p.code || ''} ${p.subclass || ''} ${p.address || ''} ${p.sign_group_label || ''} ${p.class_label || ''}`
    .toLowerCase().includes(q), [q])

  const visible = useMemo(() => all.filter((p) => inCat(p) && passFilters(p) && inQuery(p)), [all, inCat, passFilters, inQuery])
  const baseForCounts = useMemo(() => all.filter((p) => inCat(p) && (filters.review.size ? true : ACTIVE.includes(p.status))), [all, inCat, filters.review])
  // fila de revisão: por defeito da menor para a maior confiança (escolha guardada no separador do browser)
  const [reviewSort, setReviewSortState] = useState(() => {
    try { return sessionStorage.getItem('ctrlf_ordem_rever') === 'desc' ? 'desc' : 'asc' } catch { return 'asc' }
  })
  const setReviewSort = (v) => {
    setReviewSortState(v)
    try { sessionStorage.setItem('ctrlf_ordem_rever', v) } catch { /* sem armazenamento */ }
  }
  const queue = useMemo(() => visible.filter((p) => p.status === 'auto')
    .sort((a, b) => (reviewSort === 'desc' ? b.confidence - a.confidence : a.confidence - b.confidence)), [visible, reviewSort])
  const pendingTotal = useMemo(() => all.filter((p) => p.status === 'auto' && inCat(p)).length, [all, inCat])
  const filterCount = Object.values(filters).reduce((n, s) => n + s.size, 0)

  // ao mudar de categoria, filtros ou pesquisa, fecha o detalhe se o elemento deixou de estar visível
  useEffect(() => {
    if (selId && !visible.some((p) => p.id === selId)) setSelId(null)
  }, [cat, filters, query]) // eslint-disable-line react-hooks/exhaustive-deps

  const sel = selId ? byId[selId] : null
  const revEl = queue.find((p) => p.id === revId) || queue[0]
  const detailId = tab === 'rever' ? revEl?.id : sel?.id

  // ---------- detalhe do elemento aberto (observações, duplicados, histórico)
  useEffect(() => {
    if (!detailId) return
    let alive = true
    api.element(detailId).then((d) => { if (alive) setDetail(d) }).catch(() => {})
    return () => { alive = false }
  }, [detailId, detailVersion])

  // ---------- ações do técnico
  const notify = (msg, err = false) => {
    if (err) { setToast(msg); setTimeout(() => setToast(null), 6000) } else setFlash({ msg })
  }
  const run = async (fn, msg, reloadAll = false) => {
    setBusy(true)
    setFlash(null)
    try {
      const res = await fn()
      if (reloadAll) await loadElements()
      else if (res?.type === 'Feature') setFeatures((prev) => prev.map((f) => (f.id === res.id ? res : f)))
      setDetailVersion((v) => v + 1)
      loadSide()
      if (msg) setFlash({ msg })
      return res || true
    } catch (e) {
      setFlash({ msg: e.message, err: true })
      setToast(e.message)
      setTimeout(() => setToast(null), 6000)
      return false
    } finally {
      setBusy(false)
    }
  }
  const actions = {
    validate: (id, msg = 'Validado. Fica registado no histórico.') => run(() => api.validate(id), msg),
    reject: (id, msg = 'Rejeitado como falso positivo.') => run(() => api.reject(id), msg),
    restore: (id) => run(() => api.restore(id), 'Reposto: volta a estar por rever.'),
    patch: (id, body, msg = 'Correção guardada.') => run(() => api.patch(id, body), msg),
    setBest: (id, det) => run(() => api.setBest(id, det), 'Imagem principal alterada.'),
    merge: (id, into) => run(() => api.merge(id, into), `${id} juntado a ${into}: fica um só registo.`, true).then((r) => {
      if (r) { if (selId === id) setSelId(into); if (revId === id) setRevId(into) }
      return r
    }),
    split: (id, det) => run(() => api.split(id, [det]), 'Imagem separada: criado um elemento novo com ela.', true).then((r) => {
      if (r?.id && tab === 'mapa') setSelId(r.id)
      return r
    }),
  }

  // ---------- navegação
  const goTab = (t) => { setTab(t); setFlash(null); setPanel(null); setMoving(false); setPicking(false); setPicked(null) }
  const togglePanel = (p) => setPanel(panel === p ? null : p)
  const toggleFilter = (group, key) => setFilters((f) => {
    if (group === 'confset') {   // linha deslizante: "familia:valor"; 0 tira o limite dessa família
      const [fam, v] = key.split(':')
      const c = new Set([...f.conf].filter((x) => !x.startsWith(`${fam}:`)))
      if (Number(v) > 0) c.add(key)
      return { ...f, conf: c }
    }
    let s = new Set(f[group])
    if (group === 'conf') {   // um limite por família: escolher outro substitui o anterior
      const fam = key.split(':')[0]
      const had = s.has(key)
      s = new Set([...s].filter((c) => !c.startsWith(`${fam}:`)))
      if (!had) s.add(key)
    }
    else s.has(key) ? s.delete(key) : s.add(key)
    return { ...f, [group]: s }
  })
  const pick = (id) => { setSelId(id); setFlash(null); setMoving(false); setPicking(false); setPicked(null) }

  const exportHref = (fmt) => {
    const params = {}
    if (cat !== 'todos') params.family = cat
    if (filters.kinds.size) params.kind = [...filters.kinds].join(',')
    if (filters.types.size) {
      params.subclass = [...new Set([...filters.types].flatMap((t) => {
        const sub = t.split(':')[1]
        return sub === POR_IDENTIFICAR ? ['desconhecido', 'regulatory_outro'] : [sub]
      }))].join(',')
    }
    if (filters.colors.size) params.color = [...filters.colors].join(',')
    if (filters.conf.size) {
      params.min_conf_familia = [...filters.conf].map((c) => { const [f, v] = c.split(':'); return `${f}:${Number(v) / 100}` }).join(',')
    }
    if (filters.position.size === 1) params.reliable = filters.position.has('fiavel') ? 'true' : 'false'
    if (filters.review.size) {
      params.status = [...filters.review].map((r) => (r === 'rejeitado' ? 'rejeitado' : r)).join(',')
    }
    if (filters.dup.size) params.duplicates = 'true'
    if (query.trim()) params.q = query.trim()
    return exportPath(fmt, params)
  }
  const onDownload = (path) => download(path).catch((e) => notify(e.message, true))

  // ---------- reclamações
  const openByEl = useMemo(() => {
    const m = {}
    complaints?.items?.forEach((c) => { if (c.status !== 'resolvido') m[c.element_id] = (m[c.element_id] || 0) + 1 })
    return m
  }, [complaints])
  const showComplaint = (c) => {
    setTab('mapa'); setPanel(null); setMoving(false); setPicking(false); setFlash(null)
    setCat('todos')
    setSelId(c.element_id)
    const other = c.kind === 'duplicado' ? byId[c.duplicate_of] : null
    if (c.kind === 'posicao' && c.suggested_lat != null) setPicked({ lat: c.suggested_lat, lon: c.suggested_lon, label: 'Posição proposta pelo cidadão' })
    else if (other) setPicked({ lat: other.lat, lon: other.lon, label: `Repetido: ${other.id}` })
    else setPicked(null)
  }
  const report = {
    picking,
    picked,
    pin: picked,
    setPicked,
    startPick: () => { setPicking(true); setPicked(null) },
    stopPick: () => { setPicking(false); setPicked(null) },
    nearby: (p) => all.filter((o) => o.id !== p.id && o.family === p.family && ACTIVE.includes(o.status))
      .map((o) => ({ o, d: distanceM(p, o) })).filter((x) => x.d <= 60).sort((a, b) => a.d - b.d).slice(0, 6),
    onSent: () => loadComplaints(),
    openCount: (id) => openByEl[id] || 0,
    openList: (id) => { setComplaintEl(id); goTab('reclamacoes') },
  }

  const area = useMemo(() => config?.municipality?.area?.coordinates?.[0]?.map(([lon, lat]) => [lat, lon]), [config])

  if (!mode) return <Login onEnter={enter} />

  if (loadError) {
    return (
      <div className="loading" style={{ flexDirection: 'column', gap: 8, padding: 24, textAlign: 'center' }}>
        Não foi possível ligar à API.
        <small style={{ fontWeight: 600 }}>{loadError}. Confirme que o <code>docker compose up</code> está a correr e que a entrega foi importada.</small>
      </div>
    )
  }

  return (
    <div className="app">
      <Rail cat={cat} setCat={(c) => { setCat(c); setMoving(false) }} panel={panel} togglePanel={togglePanel} filterCount={filterCount}
        initials={isTech ? me?.initials : null} />

      {panel === 'filtros' && (
        <FiltersDrawer cat={cat} filters={filters} toggle={toggleFilter} clear={() => setFilters(emptyFilters())} base={baseForCounts}
          visibleCount={visible.length} onClose={() => setPanel(null)} tax={tax} titleText={TITLES[cat]} isTech={isTech}
          showArea={showArea} setShowArea={setShowArea} />
      )}
      {panel === 'legenda' && <LegendDrawer visible={visible} hasFilters={filterCount > 0} onClose={() => setPanel(null)} />}
      {panel === 'ajuda' && <HelpDrawer onClose={() => setPanel(null)} config={config} />}
      {panel === 'perfil' && (
        <ProfilePopover me={me} isTech={isTech} municipality={config?.municipality?.name}
          onReview={() => goTab('rever')} onLogout={leave} />
      )}

      <div className="main">
        <Header tab={tab} setTab={goTab} pending={pendingTotal} zone={config?.municipality?.pilot_zone_name}
          onExport={() => goTab('catalogo')} isTech={isTech}
          complaintsOpen={complaints?.counts?.por_resolver || 0} />
        {!features ? (
          <div className="loading">A carregar o catálogo…</div>
        ) : (
          <>
            {tab === 'mapa' && (
              <MapPage title={TITLES[cat]} items={visible} sel={sel} selId={selId} setSelId={pick} detail={detail}
                query={query} setQuery={setQuery} filterCount={filterCount} clearFilters={() => setFilters(emptyFilters())}
                area={area} showArea={showArea} tax={tax} byId={byId} actions={actions} busy={busy} flash={flash} moving={moving} setMoving={setMoving}
                readOnly={!isTech} report={report} />
            )}
            {isTech && tab === 'rever' && (
              <ReviewPage queue={queue} reviewSort={reviewSort} setReviewSort={(v) => { setReviewSort(v); setRevId(null) }} revId={revEl?.id} setRevId={(id, keepFlash) => { setRevId(id); if (!keepFlash) setFlash(null) }} detail={detail} tax={tax}
                byId={byId} actions={actions} busy={busy} flash={flash}
                onAdjust={(id) => { setTab('mapa'); setSelId(id); setMoving(true) }} query={query} setQuery={setQuery} />
            )}
            {isTech && tab === 'catalogo' && (
              <CatalogPage title={TITLES[cat]} items={visible} query={query} setQuery={setQuery} stats={stats} exportHref={exportHref} onDownload={onDownload}
                onShowOnMap={(id) => { goTab('mapa'); setSelId(id) }} onOpenHistory={() => goTab('historico')} />
            )}
            {isTech && tab === 'historico' && (
              <HistoryPage byId={byId} tax={tax} onDownload={onDownload} onBack={() => goTab('catalogo')}
                onShowOnMap={(id) => { setCat('todos'); goTab('mapa'); setSelId(id) }} />
            )}
            {isTech && tab === 'importar' && <ImportPage config={config} notify={notify} onCatalogChanged={() => { loadElements(); loadSide() }} />}
            {tab === 'reclamacoes' && (
              <ComplaintsPage isTech={isTech} data={complaints} reload={loadComplaints} byId={byId} onShow={showComplaint}
                actions={actions}
                elementFilter={complaintEl} clearElementFilter={() => setComplaintEl(null)} />
            )}
          </>
        )}
      </div>
      {toast && <div className="toast" role="alert">{toast}</div>}
    </div>
  )
}
