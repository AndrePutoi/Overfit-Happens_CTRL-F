// Separadores Por rever, Catálogo e Importar imagens
import { useEffect, useMemo, useState } from 'react'
import { ElementRow } from './MapPage'
import { ConfBar, DuplicateBox, Editor, Fact, Icon, ObservationViewer, SearchBox, draftChanges, draftOf, positionText } from './common'
import { FAMILIES, confColor, confPct, coordsOf, isVerified, subLabel } from '../tax'
import { api, decisionsPath, historyExportPath } from '../api'

// ------------------------------------------------------------ Por rever

export function ReviewPage({ queue, reviewSort, setReviewSort, revId, setRevId, detail, tax, byId, actions, busy, flash, onAdjust, query, setQuery }) {
  const p = queue.find((x) => x.id === revId) || queue[0]
  const [draft, setDraft] = useState(p ? draftOf(p) : null)
  const [shown, setShown] = useState(150)
  useEffect(() => { if (p) setDraft(draftOf(p)) }, [p?.id]) // eslint-disable-line react-hooks/exhaustive-deps
  const d = p && detail && detail.id === p.id ? detail.properties : null

  const nextId = () => {
    const i = queue.findIndex((x) => x.id === p.id)
    return queue[i + 1]?.id || queue[i - 1]?.id || null
  }
  const saveAndValidate = async () => {
    const next = nextId()
    const ch = draftChanges(p, draft)
    const ok = Object.keys(ch).length
      ? await actions.patch(p.id, ch, `${p.id} corrigido e validado.`)
      : await actions.validate(p.id, `${p.id} validado.`)
    if (ok) setRevId(next, true)
  }
  const reject = async () => {
    const next = nextId()
    if (await actions.reject(p.id, `${p.id} rejeitado como falso positivo.`)) setRevId(next, true)
  }

  return (
    <div className="review">
      <section className="list-col queue" aria-label="Fila de revisão">
        <div className="list-head">
          <h1 style={{ fontSize: 21, fontWeight: 800 }}>Por rever</h1>
          <p style={{ margin: 0, fontSize: 13, color: '#4A5468' }}>{queue.length} deteções automáticas, por rever.</p>
          <SearchBox value={query} onChange={setQuery} />
          <label className="sort-row">
            <span>Ordenar</span>
            <select value={reviewSort} onChange={(e) => setReviewSort(e.target.value)} aria-label="Ordenar a fila de revisão">
              <option value="asc">Confiança: menor primeiro</option>
              <option value="desc">Confiança: maior primeiro</option>
            </select>
          </label>
        </div>
        <div className="scroll">
          {queue.slice(0, shown).map((x) => <ElementRow key={x.id} p={x} selected={p && x.id === p.id} onPick={setRevId} showThumb={false} />)}
          {queue.length > shown && <div className="more"><button className="btn btn-ghost" style={{ width: '100%' }} onClick={() => setShown(shown + 150)}>Mostrar mais</button></div>}
        </div>
      </section>
      <section className="pane" aria-label="Revisão do elemento">
        {flash && <div className={`flash${flash.err ? ' err' : ''}`} style={{ margin: 0 }} role="status">{flash.msg}</div>}
        {!p && (
          <div className="done">
            <b>{query ? 'Nenhuma deteção por rever corresponde à pesquisa' : 'Está tudo revisto nesta categoria'}</b>
            <p style={{ margin: 0, fontSize: 14, color: '#4A5468' }}>Novas deteções aparecem aqui depois de importar uma nova entrega.</p>
          </div>
        )}
        {p && draft && (
          <>
            <div className="head">
              <span className="id-chip"># {p.id}</span>
              <Icon el={p} size={30} />
              <h2>{p.name}</h2>
              <span className="id-chip" style={{ color: confColor(confPct(p)), fontWeight: 800 }}>{confPct(p)}% confiança</span>
            </div>
            <div className="cols">
              <div>
                <ObservationViewer key={p.id} detail={d} busy={busy}
                  onSetBest={(det) => actions.setBest(p.id, det)} onSplit={(det) => actions.split(p.id, det)} />
              </div>
              <div>
                <DuplicateBox p={p} detail={d} byId={byId} busy={busy} onMerge={actions.merge} onShow={setRevId} />
                <Editor p={p} draft={draft} setDraft={setDraft} tax={tax} />
                <div className="kv">
                  <Fact k="Categoria">{FAMILIES[p.family].label}</Fact>
                  <Fact k="Tipo">{subLabel(p)}</Fact>
                  <Fact k="Coordenadas" full>{coordsOf(p)}</Fact>
                  <Fact k="Precisão da posição" full>{positionText(p)}</Fact>
                  <Fact k="Fonte">{p.source?.name || '—'}</Fact>
                  <Fact k="Visto em">{p.n_views} {p.n_views === 1 ? 'imagem' : 'imagens'}</Fact>
                </div>
                <button className="btn-small" style={{ alignSelf: 'flex-start' }} onClick={() => onAdjust(p.id)}>Ajustar posição no mapa</button>
                <div className="two">
                  <button className="btn btn-danger" disabled={busy} onClick={reject}>Rejeitar (falso positivo)</button>
                  <button className="btn btn-dark" disabled={busy} onClick={saveAndValidate}>
                    {Object.keys(draftChanges(p, draft)).length ? 'Guardar correção e validar' : 'Validar'}
                  </button>
                </div>
              </div>
            </div>
          </>
        )}
      </section>
    </div>
  )
}

// ------------------------------------------------------------ Catálogo

// ordem por confiança, partilhada com a lista do mapa (sessionStorage 'ctrlf_ordem')
const CONF_SORT = { conf_desc: (a, b) => (b.confidence ?? 0) - (a.confidence ?? 0), conf_asc: (a, b) => (a.confidence ?? 0) - (b.confidence ?? 0) }
function readSort() {
  try { return sessionStorage.getItem('ctrlf_ordem') || 'padrao' } catch { return 'padrao' }
}

export function CatalogPage({ title, items: unsorted, query, setQuery, stats, exportHref, onDownload, onShowOnMap, onOpenHistory }) {
  const [shown, setShown] = useState(200)
  const [sort, setSort] = useState(readSort)
  const items = useMemo(() => (CONF_SORT[sort] ? [...unsorted].sort(CONF_SORT[sort]) : unsorted), [unsorted, sort])
  const changeSort = (next) => {
    setSort(next)
    setShown(200)
    try { sessionStorage.setItem('ctrlf_ordem', next) } catch { /* sem armazenamento */ }
  }
  useEffect(() => setShown(200), [items.length, query])
  const s = stats || {}
  const dot = (c) => <span className="dot" style={{ background: c }} />
  const cards = [
    ['Total no catálogo', s.total, '#1F5FAD'],
    ['Sinalização', s.by_family?.sinal, FAMILIES.sinal.color],
    ['Iluminação', s.by_family?.iluminacao, FAMILIES.iluminacao.color],
    ['Resíduos', s.by_family?.residuos, FAMILIES.residuos.color],
    ['Bancos', s.by_family?.mobiliario, FAMILIES.mobiliario.color],
    ['Verificados', s.verified_pct != null ? `${s.verified_pct}%` : '—', '#14532D'],
    ['Posição triangulada', s.position_reliable, '#16457F'],
    ['Duplicados por resolver', s.duplicate_groups_open, '#B26B00'],
  ]
  const statusOf = (p) => (isVerified(p) ? ['Verificado', 'ok'] : p.status === 'rejeitado' ? ['Rejeitado', 'no'] : p.status === 'fundido' ? ['Fundido', 'no'] : ['Por rever', ''])
  return (
    <div className="page">
      <div className="page-head">
        <div className="txt">
          <h1>Catálogo — {title}</h1>
          <p>Todos os elementos detetados na zona piloto, com coordenadas, tipo e grau de confiança. A exportação respeita a categoria, os filtros e a pesquisa.</p>
        </div>
        <div style={{ width: 300, maxWidth: '100%' }}><SearchBox value={query} onChange={setQuery} /></div>
        <label className="sort-row" style={{ minWidth: 300 }}>
          <span>Ordenar</span>
          <select value={sort} onChange={(e) => changeSort(e.target.value)} aria-label="Ordenar o catálogo">
            <option value="padrao">Ordem do catálogo</option>
            <option value="conf_asc">Confiança: menor primeiro</option>
            <option value="conf_desc">Confiança: maior primeiro</option>
          </select>
        </label>
        <button className="btn btn-primary" onClick={() => onDownload(exportHref('geojson'))}>Exportar GeoJSON</button>
        <button className="btn btn-outline" onClick={() => onDownload(exportHref('csv'))}>Exportar CSV</button>
        <button className="btn btn-ghost" onClick={onOpenHistory} title="Tudo o que os técnicos alteraram, e a transferência das decisões para o pipeline">Histórico de alterações</button>
      </div>
      <div className="stats">
        {cards.map(([k, v, c]) => (
          <div key={k} className="stat"><div className="k">{dot(c)}{k}</div><div className="v">{v ?? '—'}</div></div>
        ))}
      </div>
      {s.waste_unclassified > 0 && (
        <div className="banner amber">
          {s.waste_unclassified} contentores de superfície ainda não têm tipo (ilha de reciclagem ou indiferenciado). Podem ser classificados à mão em Por rever.
        </div>
      )}
      <div className="card table">
        <div className="trow th"><span>ID</span><span>ELEMENTO</span><span>TIPO</span><span>CÓDIGO</span><span>COORDENADAS</span>
          <button className={`th-sort${sort !== 'padrao' ? ' on' : ''}`}
            onClick={() => changeSort(sort === 'conf_desc' ? 'conf_asc' : sort === 'conf_asc' ? 'padrao' : 'conf_desc')}
            title="Ordenar por confiança" aria-label={`Ordenar por confiança (${sort === 'conf_desc' ? 'maior primeiro' : sort === 'conf_asc' ? 'menor primeiro' : 'sem ordem'})`}>
            CONFIANÇA <span aria-hidden="true">{sort === 'conf_desc' ? '↓' : sort === 'conf_asc' ? '↑' : '↕'}</span>
          </button><span>POSIÇÃO</span><span>ESTADO</span><span /></div>
        {items.slice(0, shown).map((p) => {
          const [st, cls] = statusOf(p)
          return (
            <div key={p.id} className="trow clickable" role="button" tabIndex={0} title="Ver no mapa"
              onClick={() => onShowOnMap(p.id)} onKeyDown={(e) => { if (e.key === 'Enter') onShowOnMap(p.id) }}>
              <span style={{ fontWeight: 700, color: '#3B4658' }}>{p.id}</span>
              <span className="name"><Icon el={p} size={24} />{p.name}</span>
              <span className="sub">{subLabel(p)}</span>
              <span className="sub">{p.code || '—'}</span>
              <span className="num">{coordsOf(p)}</span>
              <ConfBar pct={confPct(p)} small />
              <span className="sub">{p.position_reliable ? 'Triangulada' : `± ${Math.round(p.uncertainty_m)} m`}</span>
              <span className={`status ${cls}`}>{st}</span>
              <span className="btn-small" aria-hidden="true">Ver no mapa</span>
            </div>
          )
        })}
        {items.length > shown && <div className="more"><button className="btn btn-ghost" onClick={() => setShown(shown + 200)}>Mostrar mais ({items.length - shown})</button></div>}
        {!items.length && <p className="empty">Nenhum elemento corresponde à pesquisa.</p>}
      </div>
    </div>
  )
}

// ------------------------------------------------------------ Histórico de alterações

const ACTIONS = ['validar', 'corrigir', 'mover', 'rejeitar', 'repor', 'fundir', 'separar', 'melhor_imagem']
const ACTION_CLS = { validar: 'ok', corrigir: 'ok', mover: 'ok', rejeitar: 'no', repor: '', fundir: 'amber', separar: 'amber', melhor_imagem: '' }
const FIELD_LABELS = { status: 'Estado', class: 'Equipamento', subclass: 'Tipo', install_type: 'Instalação', color: 'Cor',
  address: 'Morada', best_detection_id: 'Melhor imagem', merged_into: 'Juntado a', new_element: 'Novo elemento', detections: 'Imagens' }
const STATUS_LABELS = { auto: 'Por rever', validado: 'Validado', corrigido: 'Corrigido', rejeitado: 'Rejeitado', fundido: 'Juntado' }

function distM(a, b) {
  const R = 6371000, r = (x) => (x * Math.PI) / 180
  const h = Math.sin(r(b.lat - a.lat) / 2) ** 2 + Math.cos(r(a.lat)) * Math.cos(r(b.lat)) * Math.sin(r(b.lon - a.lon) / 2) ** 2
  return 2 * R * Math.asin(Math.sqrt(h))
}

function changeText(h, tax) {
  const b = h.before || {}
  const a = h.after || {}
  const fmt = (k, v) => {
    if (v === null || v === undefined || v === '') return '—'
    if (k === 'status') return STATUS_LABELS[v] || v
    if (k === 'subclass') return tax?.familias?.sinal?.tipos?.[v]?.nome || v
    if (k === 'class') {
      for (const f of Object.values(tax?.familias || {})) if (f.classes?.[v]) return f.classes[v].label
    }
    if (k === 'install_type') return tax?.instalacao?.[v]?.label || v
    if (k === 'color') return tax?.cores_ecoponto?.[v]?.label || v
    if (Array.isArray(v)) return `${v.length}`
    if (typeof v === 'object') return JSON.stringify(v)
    return String(v)
  }
  const parts = []
  if (a.lat != null && b.lat != null) parts.push(`Posição: movida ${Math.round(distM(b, a))} m`)
  const keys = [...new Set([...Object.keys(b), ...Object.keys(a)])].filter((k) => k !== 'lat' && k !== 'lon')
  keys.forEach((k) => {
    if (JSON.stringify(b[k]) === JSON.stringify(a[k])) return
    const label = FIELD_LABELS[k] || k
    parts.push(k in b && k in a ? `${label}: ${fmt(k, b[k])} → ${fmt(k, a[k])}` : `${label}: ${fmt(k, k in a ? a[k] : b[k])}`)
  })
  return parts.join(' · ') || '—'
}

export function HistoryPage({ byId, tax, onShowOnMap, onDownload, onBack }) {
  const [data, setData] = useState(null)
  const [action, setAction] = useState(null)
  const [error, setError] = useState(null)
  useEffect(() => {
    api.history({ limit: 5000 }).then(setData).catch((e) => setError(e.message))
  }, [])
  const items = (data?.items || []).filter((h) => !action || h.action === action)
  return (
    <div className="page">
      <div className="page-head">
        <div className="txt">
          <button className="btn-link" style={{ display: 'block', padding: 0, marginBottom: 6, textAlign: 'left' }} onClick={onBack}>← Catálogo</button>
          <h1>Histórico de alterações</h1>
          <p>Tudo o que os técnicos validaram, corrigiram, moveram, rejeitaram, juntaram ou separaram, do mais recente para o mais antigo. As decisões transferidas servem para o pipeline voltar a treinar os modelos.</p>
        </div>
        <button className="btn btn-primary" onClick={() => onDownload(decisionsPath())}>Transferir decisões (pipeline)</button>
        <button className="btn btn-outline" onClick={() => onDownload(historyExportPath())}>Transferir histórico (CSV)</button>
      </div>
      {error && <div className="flash err" role="alert" style={{ margin: 0 }}>{error}</div>}
      <div className="chips">
        <button className={`chip${!action ? ' on' : ''}`} aria-pressed={!action} onClick={() => setAction(null)}>Todas · {data?.total ?? 0}</button>
        {ACTIONS.filter((k) => data?.counts?.[k]).map((k) => (
          <button key={k} className={`chip${action === k ? ' on' : ''}`} aria-pressed={action === k} onClick={() => setAction(action === k ? null : k)}>
            {data.items.find((h) => h.action === k)?.action_label || k} · {data.counts[k]}
          </button>
        ))}
      </div>
      <div className="card table">
        <div className="hrow th"><span>DATA E HORA</span><span>TÉCNICO</span><span>AÇÃO</span><span>ELEMENTO</span><span>ALTERAÇÃO</span></div>
        {!data && !error && <p className="empty">A carregar…</p>}
        {data && !items.length && <p className="empty">Ainda não há alterações{action ? ' deste tipo' : ''}.</p>}
        {items.map((h) => {
          const p = byId[h.element_id]
          const go = p ? () => onShowOnMap(h.element_id) : null   // rejeitados e juntados já não estão no mapa
          return (
            <div key={h.id} className={`hrow${go ? ' clickable' : ''}`} role={go ? 'button' : undefined} tabIndex={go ? 0 : undefined}
              title={go ? 'Ver no mapa' : 'Este elemento já não está no mapa (rejeitado ou juntado a outro)'}
              onClick={go || undefined} onKeyDown={(e) => { if (go && e.key === 'Enter') go() }}>
              <span className="num">{new Date(h.at).toLocaleString('pt-PT')}</span>
              <span>{h.who}</span>
              <span><span className={`status ${ACTION_CLS[h.action] || ''}`}>{h.action_label}</span></span>
              <span className="name">{p && <Icon el={p} size={22} />}<span><b>{h.element_name || h.element_id}</b><small>{h.element_id}</small></span></span>
              <span className="sub">{changeText(h, tax)}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ------------------------------------------------------------ Importar imagens

const JOB_STATUS = { na_fila: ['Na fila', '#F1F4F8', '#3B4658'], a_processar: ['A processar', '#E8F0FB', '#16457F'], concluido: ['Concluído', '#E7F4EC', '#14532D'], erro: ['Erro', '#FDECEA', '#B42318'] }

export function ImportPage({ config, notify, onCatalogChanged }) {
  const [jobs, setJobs] = useState([])
  const [imports, setImports] = useState([])
  const [street, setStreet] = useState('')
  const [gpx, setGpx] = useState(null)
  const [sending, setSending] = useState(false)
  const reload = () => {
    api.jobs().then(setJobs).catch(() => {})
    api.imports().then(setImports).catch(() => {})
  }
  useEffect(reload, [])
  // enquanto houver pedidos por acabar, atualizar a cada 5 s; quando um acaba, recarregar o mapa
  const active = jobs.some((j) => j.status === 'na_fila' || j.status === 'a_processar')
  useEffect(() => {
    if (!active) return undefined
    const t = setInterval(reload, 5000)
    return () => clearInterval(t)
  }, [active]) // eslint-disable-line react-hooks/exhaustive-deps
  const [seenDone, setSeenDone] = useState(null)
  useEffect(() => {
    const done = jobs.filter((j) => j.status === 'concluido').map((j) => j.id)
    if (seenDone && done.some((id) => !seenDone.includes(id))) {
      onCatalogChanged?.()
      notify('Processamento concluído: os elementos novos já estão no mapa.')
    }
    if (jobs.length) setSeenDone(done)
  }, [jobs]) // eslint-disable-line react-hooks/exhaustive-deps
  const sv = config?.sources?.find((s) => s.key === 'streetview')
  const mly = config?.sources?.find((s) => s.key === 'mapillary')

  const sendVideo = async (file) => {
    if (!file) return
    setSending(true)
    try {
      await api.uploadVideo(file, gpx, street || file.name)
      notify(`Vídeo "${file.name}" enviado. Fica na fila até o pipeline o processar.`)
      reload()
    } catch (e) {
      notify(e.message, true)
    } finally {
      setSending(false)
    }
  }
  const askSource = async () => {
    try {
      if (!street.trim()) {
        notify('Escreva primeiro o nome da rua ou do bairro.', true)
        return
      }
      await api.sourceJob('mapillary', street.trim())
      notify(`Pedido registado: imagens do Mapillary à volta de "${street.trim()}". O progresso aparece em Processamentos.`)
      reload()
    } catch (e) {
      notify(e.message, true)
    }
  }

  const icon = (path) => (
    <span><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#1F5FAD" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{path}</svg></span>
  )
  return (
    <div className="page">
      <div className="page-head">
        <div className="txt">
          <h1>Importar imagens</h1>
          <p>Junte imagens de uma rua ou bairro. O pipeline deteta os elementos, calcula as coordenadas e acrescenta-os ao catálogo.</p>
        </div>
      </div>
      <label className="field" style={{ maxWidth: 420 }}>Rua ou bairro (o pipeline procura imagens à volta deste sítio)
        <input type="text" value={street} onChange={(e) => setStreet(e.target.value)} placeholder="Ex.: Av. Dr. Lourenço Peixinho" />
      </label>
      <div className="cards">
        <div className="card icard">
          <div className="h">{icon(<><circle cx="12" cy="12" r="9" /><path d="M3 12h18" /><path d="M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18" /></>)}<h2>Mapillary (fonte aberta)</h2></div>
          <p>Imagens públicas da mesma zona, {mly?.license || 'CC BY-SA 4.0'}, já com rostos e matrículas desfocados. É a fonte das imagens atuais.</p>
          <button className="btn btn-primary" onClick={askSource} disabled={!mly?.enabled}>Pedir imagens desta rua</button>
        </div>
        <div className="card icard">
          <div className="h">{icon(<><rect x="3" y="6" width="13" height="12" rx="2" /><path d="m16 10 5-3v10l-5-3" /></>)}<h2>Vídeo gravado na rua</h2></div>
          <label className="drop">
            <b>{sending ? 'A enviar…' : 'Escolher vídeo MP4 ou MOV'}</b>
            <small>Com GPS no ficheiro, ou junte o GPX abaixo</small>
            <input type="file" accept="video/*" disabled={sending} onChange={(e) => sendVideo(e.target.files[0])} />
          </label>
          <label className="field">Percurso GPX (opcional)
            <input type="file" accept=".gpx" onChange={(e) => setGpx(e.target.files[0] || null)} />
          </label>
          <p className="cf-note">O vídeo fica guardado; o processamento automático de vídeo ainda não está ligado ao pipeline.</p>
        </div>
        <div className="card icard off">
          <div className="h">{icon(<><path d="M12 21s-7-6.2-7-11a7 7 0 0 1 14 0c0 4.8-7 11-7 11Z" /><circle cx="12" cy="10" r="2.5" /></>)}<h2>Google Street View</h2></div>
          <p>
            Desligado. Os <a href="https://cloud.google.com/maps-platform/terms" target="_blank" rel="noreferrer">termos do Google Maps Platform</a> não
            permitem guardar as imagens, usá-las para treinar modelos nem mostrá-las sobre um mapa que não seja da Google.
            {sv?.requires_authorization ? ' Só pode ser ligado com autorização escrita.' : ''}
          </p>
          <button className="btn btn-ghost" disabled>Requer autorização</button>
        </div>
      </div>
      <div className="banner">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 3 5 6v6c0 4 3 7 7 9 4-2 7-5 7-9V6Z" /></svg>
        Rostos e matrículas são desfocados antes de guardar; os vídeos originais são apagados depois de processados.
      </div>
      <div className="card list-card">
        <h2>Entregas do pipeline importadas</h2>
        {imports.map((r) => (
          <div key={r.id} className="jrow">
            <div className="a"><b>Entrega {r.generated_at ? new Date(r.generated_at).toLocaleString('pt-PT') : ''}</b><small>Importada a {new Date(r.imported_at).toLocaleString('pt-PT')} · versão {r.schema_version} · commit {r.pipeline_commit}</small></div>
            <div className="b">{r.counts?.images} imagens · {r.counts?.detections} deteções → {r.counts?.elements} elementos</div>
            <div className="b">{r.decisions_applied} decisões do técnico reaplicadas{r.decisions_skipped ? `, ${r.decisions_skipped} ignoradas` : ''}</div>
          </div>
        ))}
        {!imports.length && <p className="empty">Ainda não há entregas importadas.</p>}
      </div>
      <div className="card list-card">
        <h2>Processamentos</h2>
        {jobs.map((j) => {
          const [label, bg, fg] = JOB_STATUS[j.status] || JOB_STATUS.na_fila
          return (
            <div key={j.id} className="jrow">
              <div className="a"><b>{j.name}</b><small>{j.source_name} · pedido por {j.created_by || '—'} · {new Date(j.created_at).toLocaleString('pt-PT')}</small></div>
              <div className="b">
                {j.status === 'concluido' && j.n_elements != null
                  ? `${j.n_images} imagens · ${j.n_detections} deteções → ${j.n_elements} elementos novos`
                  : j.status === 'erro'
                    ? <span style={{ color: '#B42318' }}>{j.error || 'Falhou'}</span>
                    : j.status === 'a_processar'
                      ? `A processar: ${j.params?.etapa || '…'}`
                      : 'À espera do pipeline'}
              </div>
              <div className="c">
                <span className="progress"><span style={{ width: `${j.progress}%`, background: j.progress >= 100 ? '#1E7A4C' : '#1F5FAD' }} /></span>
                <span className="status" style={{ background: bg, color: fg }}>{label}</span>
              </div>
            </div>
          )
        })}
        {!jobs.length && <p className="empty">Sem processamentos pedidos.</p>}
      </div>
    </div>
  )
}
