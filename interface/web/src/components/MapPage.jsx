import { useEffect, useMemo, useState } from 'react'
import MapView from './MapView'
import { ComplaintForm } from './Complaints'
import { Chevron } from './Chrome'
import {
  CloseButton, ConfBar, DuplicateBox, Editor, Fact, Icon, ObservationViewer, SearchBox, draftChanges, draftOf, positionText,
} from './common'
import { ECO, FAMILIES, confColor, confPct, coordsOf, fmtDate, isVerified, subLabel } from '../tax'

const PAGE = 150

export function ElementRow({ p, selected, onPick, showThumb = true }) {
  const pct = confPct(p)
  return (
    <button className={`row${selected ? ' sel' : ''}`} aria-pressed={selected} onClick={() => onPick(p.id)}>
      <div className="row-main">
        <div className="row-meta">{subLabel(p)} • {p.id}</div>
        <div className="row-name"><Icon el={p} size={24} /><span>{p.name}</span></div>
        <div className="row-tags">
          <span style={{ color: confColor(pct) }}>{pct}% confiança</span>
          {isVerified(p) && <span style={{ color: '#1E7A4C' }}>✓ Verificado</span>}
          {p.status === 'rejeitado' && <span style={{ color: '#B42318' }}>Rejeitado</span>}
          {p._dup && <span className="tag-amber">Possível duplicado</span>}
          {!p.position_reliable && <span className="tag-grey">± {Math.round(p.uncertainty_m)} m</span>}
        </div>
      </div>
      {showThumb && (
        <div className="thumb" aria-hidden="true">
          {p.best?.crop_url ? <img src={p.best.crop_url} alt="" loading="lazy" /> : <Icon el={p} size={36} />}
        </div>
      )}
    </button>
  )
}

const SORTS = {
  padrao: { label: 'Ordem do catálogo', fn: null },
  conf_asc: { label: 'Confiança: menor primeiro', fn: (a, b) => (a.confidence ?? 0) - (b.confidence ?? 0) },
  conf_desc: { label: 'Confiança: maior primeiro', fn: (a, b) => (b.confidence ?? 0) - (a.confidence ?? 0) },
}

function ListCol({ title, items: unsorted, selId, onPick, query, setQuery, filterCount, clearFilters, onCollapse }) {
  const [shown, setShown] = useState(PAGE)
  const [sort, setSort] = useState(() => {
    try { return SORTS[sessionStorage.getItem('ctrlf_ordem')] ? sessionStorage.getItem('ctrlf_ordem') : 'padrao' } catch { return 'padrao' }
  })
  const items = useMemo(() => (SORTS[sort].fn ? [...unsorted].sort(SORTS[sort].fn) : unsorted), [unsorted, sort])
  const changeSort = (v) => {
    setSort(v)
    setShown(PAGE)
    try { sessionStorage.setItem('ctrlf_ordem', v) } catch { /* sem armazenamento */ }
  }
  useEffect(() => setShown(PAGE), [items.length, query])
  return (
    <section className="list-col" aria-label="Lista de elementos">
      <div className="list-head">
        <div className="title">
          <h1>{title}</h1>
          <span className="n">{items.length} {items.length === 1 ? 'elemento' : 'elementos'}</span>
          <button className="collapse-btn" onClick={onCollapse} aria-label="Esconder a lista" title="Esconder a lista"><Chevron dir="left" double /></button>
        </div>
        <SearchBox value={query} onChange={setQuery} />
        <label className="sort-row">
          <span>Ordenar</span>
          <select value={sort} onChange={(e) => changeSort(e.target.value)} aria-label="Ordenar a lista">
            {Object.entries(SORTS).map(([k, s]) => <option key={k} value={k}>{s.label}</option>)}
          </select>
        </label>
        {filterCount > 0 && (
          <div className="filters-on">
            {filterCount} {filterCount === 1 ? 'filtro ativo' : 'filtros ativos'}
            <button className="btn-link" onClick={clearFilters}>Limpar</button>
          </div>
        )}
      </div>
      <div className="scroll">
        {items.slice(0, shown).map((p) => <ElementRow key={p.id} p={p} selected={p.id === selId} onPick={onPick} />)}
        {items.length > shown && (
          <div className="more"><button className="btn btn-ghost" style={{ width: '100%' }} onClick={() => setShown(shown + PAGE)}>Mostrar mais ({items.length - shown})</button></div>
        )}
        {!items.length && <p className="empty">Nenhum elemento corresponde à pesquisa ou aos filtros.</p>}
      </div>
    </section>
  )
}

function Detail({ p, detail, tax, byId, actions, busy, flash, onClose, onShow, onStartMove, readOnly, report }) {
  const [editing, setEditing] = useState(false)
  const [reporting, setReporting] = useState(false)
  const [sent, setSent] = useState(null)
  useEffect(() => { setReporting(false); setSent(null) }, [p.id])
  const [draft, setDraft] = useState(draftOf(p))
  useEffect(() => { setEditing(false); setDraft(draftOf(p)) }, [p.id]) // eslint-disable-line react-hooks/exhaustive-deps
  const d = detail && detail.id === p.id ? detail.properties : null
  const pct = confPct(p)
  const v = isVerified(p)

  const save = async () => {
    const ch = draftChanges(p, draft)
    if (Object.keys(ch).length) await actions.patch(p.id, ch, 'Correção guardada e registada no histórico.')
    setEditing(false)
  }

  const ilha = p.ilha
  const typeFacts = p.family === 'residuos'
    ? [
        <Fact key="eq" k="Equipamento">{p.class_label}</Fact>,
        <Fact key="ti" k="Tipo">{p.install_label || 'Por classificar'}</Fact>,
        p.color && <Fact key="co" k="Cor do ecoponto" full>{p.color_label} ({p.color_waste})</Fact>,
        p.n_units > 1 && <Fact key="nu" k="Contentores juntos">{p.n_units}</Fact>,
        p.fluxo_sugerido && !ilha?.composicao?.length && (
          <Fact key="fx" k="Tipo sugerido pelo modelo" full>
            <span className="ilha-comp">
              <span className="ilha-chip"><i style={{ background: ECO[p.fluxo_sugerido.color] || '#8A94A6' }} />{p.fluxo_sugerido.label}
                {p.fluxo_sugerido.p != null && ` · ${Math.round(p.fluxo_sugerido.p * 100)}%`}</span>
            </span>
            <small className="ilha-note">Sugestão automática, ainda pouco fiável: confirme na imagem e corrija o tipo.</small>
          </Fact>
        ),
        ilha?.composicao?.length > 0 && (
          <Fact key="il" k="Composição sugerida" full>
            <span className="ilha-comp">
              {ilha.composicao.map((c) => (
                <span key={c.fluxo} className="ilha-chip"><i style={{ background: ECO[c.color] || '#8A94A6' }} />{c.n} × {c.label}</span>
              ))}
            </span>
            <small className="ilha-note">Sugestão automática, ainda pouco fiável: confirme na imagem e corrija o tipo.</small>
          </Fact>
        ),
      ]
    : p.family === 'sinal'
      ? [<Fact key="gr" k="Grupo">{p.sign_group_label}</Fact>, <Fact key="cd" k="Código">{p.code || '—'}</Fact>]
      : [<Fact key="tp" k="Tipo">{p.class_label}</Fact>]

  return (
    <aside className="detail" aria-label="Detalhe do elemento">
      <div className="detail-head">
        <div className="top">{FAMILIES[p.family].label}<CloseButton onClick={onClose} label="Fechar detalhe" /></div>
        <span className="id-chip"># {p.id}</span>
        <div className="detail-title"><Icon el={p} size={32} /><h2>{p.name}</h2></div>
      </div>
      <div style={{ margin: '0 20px' }}>
        <ObservationViewer key={p.id} detail={d} busy={busy}
          onSetBest={readOnly ? null : (det) => actions.setBest(p.id, det)}
          onSplit={readOnly ? null : (det) => actions.split(p.id, det)} />
      </div>

      {reporting && readOnly && (
        <div style={{ padding: '16px 20px' }}>
          <ComplaintForm p={p} nearby={report.nearby(p)} tax={tax} picked={report.picked}
            onStartPick={report.startPick} onStopPick={report.stopPick}
            onCancel={() => setReporting(false)}
            onSent={(c) => { setReporting(false); setSent(c); report.onSent(c) }} />
        </div>
      )}

      {!reporting && (!editing || readOnly) && (
        <>
          {!readOnly && p.clip_suspect && (
            <div className="warn-note">
              <b>Atenção:</b> a verificação automática (CLIP) acha que a melhor imagem pode não ser {p.family === 'sinal' ? 'um sinal deste tipo' : 'um contentor'} (por exemplo, uma caixa elétrica). Confirme na imagem.
            </div>
          )}
          {!readOnly && p.auto_merged && p.merged_from?.length > 0 && (
            <div className="info-note">
              Juntado automaticamente pelo sistema a partir de {p.merged_from.length + 1} deteções ({[p.id, ...p.merged_from].join(', ')}). Se forem objetos diferentes, use "Separar esta imagem".
            </div>
          )}
          <div className="facts">
            {typeFacts}
            <Fact k="Coordenadas" full>{coordsOf(p)}</Fact>
            <Fact k="Precisão da posição" full>{positionText(p)}</Fact>
            {p.address && <Fact k="Morada aproximada" full>{p.address}</Fact>}
            <Fact k="Fonte">{p.source?.name || '—'}</Fact>
            <Fact k="Detetado em">{fmtDate(p.first_seen_at)}</Fact>
            <Fact k="Grau de confiança da deteção" full><ConfBar pct={pct} /></Fact>
            <Fact k="Deteções agrupadas" full>
              <span style={{ fontWeight: 600 }}>Visto em {p.n_views} {p.n_views === 1 ? 'imagem' : 'imagens'}, registado uma única vez</span>
            </Fact>
          </div>
          {readOnly ? (
            <>
              <div className="grow" />
              {sent && (
                <div className="flash" role="status">
                  Reclamação n.º {sent.id} enviada. Pode acompanhar o estado no separador Reclamações.
                </div>
              )}
              <div className="verified-note">
                <b>✓ Verificado pela câmara</b>
                Confirmado por um técnico em {fmtDate(p.updated_at)}.
              </div>
              <div style={{ margin: '0 12px 16px' }}>
                <button className="btn btn-outline" style={{ width: '100%' }} onClick={() => { setSent(null); setReporting(true) }}>
                  Reportar um problema
                </button>
              </div>
            </>
          ) : (<>
          {report?.openCount(p.id) > 0 && (
            <div className="complaint-note">
              <b>{report.openCount(p.id)} {report.openCount(p.id) === 1 ? 'reclamação' : 'reclamações'} de cidadãos por tratar</b>
              <button className="btn-small" onClick={() => report.openList(p.id)}>Ver</button>
            </div>
          )}
          <div style={{ margin: '0 20px 12px' }}>
            <DuplicateBox p={p} detail={d} byId={byId} busy={busy} onMerge={actions.merge} onShow={onShow} />
          </div>
          {flash && <div className={`flash${flash.err ? ' err' : ''}`} role="status">{flash.msg}</div>}
          <div className="grow" />
          <div className={`action-box${v ? ' ok' : p.status === 'rejeitado' ? ' no' : ''}`}>
            <div className="t">{v ? 'Verificado por um técnico' : p.status === 'rejeitado' ? 'Rejeitado (falso positivo)' : 'Deteção automática por rever'}</div>
            <p>
              {v ? `Confirmado por ${p.updated_by || 'um técnico'}. Pode corrigir o tipo ou a posição se algo mudou na rua.`
                : p.status === 'rejeitado' ? 'Não aparece no mapa por omissão nem nas exportações.'
                  : 'Confirme se o tipo está certo. Use Corrigir para mudar o tipo ou a cor antes de validar.'}
            </p>
            {p.status === 'rejeitado' ? (
              <button className="btn btn-dark" disabled={busy} onClick={() => actions.restore(p.id)}>Repor</button>
            ) : (
              <>
                <div className="two">
                  <button className="btn btn-outline" disabled={busy} onClick={() => setEditing(true)}>Corrigir</button>
                  <button className="btn btn-dark" disabled={busy || v} onClick={() => actions.validate(p.id)}>{v ? '✓ Verificado' : 'Validar'}</button>
                </div>
                <div className="two">
                  <button className="btn-small" disabled={busy} onClick={onStartMove}>Ajustar posição</button>
                  <button className="btn-small" style={{ color: '#B42318' }} disabled={busy} onClick={() => actions.reject(p.id)}>Rejeitar</button>
                </div>
              </>
            )}
          </div>
          {d?.history?.length > 0 && (
            <div style={{ margin: '0 20px 16px', fontSize: 12, color: '#5A6478', display: 'flex', flexDirection: 'column', gap: 4 }}>
              <b style={{ color: '#3B4658' }}>Histórico</b>
              {d.history.slice(0, 5).map((h, i) => (
                <span key={i}>{new Date(h.at).toLocaleString('pt-PT')} · {h.who} · {h.action.replace('_', ' ')}</span>
              ))}
            </div>
          )}
          </>)}
        </>
      )}

      {editing && !readOnly && (
        <div style={{ padding: '18px 20px', display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div className="editing-note">A corrigir — as alterações aparecem logo no mapa e na lista.</div>
          <Editor p={p} draft={draft} setDraft={setDraft} tax={tax} />
          <div className="two">
            <button className="btn btn-ghost" onClick={() => { setDraft(draftOf(p)); setEditing(false) }}>Cancelar</button>
            <button className="btn btn-dark" disabled={busy} onClick={save}>Guardar correção</button>
          </div>
        </div>
      )}
    </aside>
  )
}

export default function MapPage(props) {
  const { title, items, sel, selId, setSelId, detail, query, setQuery, filterCount, clearFilters, area, showArea,
    tax, byId, actions, busy, flash, moving, setMoving, readOnly, report } = props
  const [listOpen, setListOpen] = useState(true)
  return (
    <div className="layout">
      {listOpen ? (
        <ListCol title={title} items={items} selId={selId} onPick={setSelId} query={query} setQuery={setQuery}
          filterCount={filterCount} clearFilters={clearFilters} onCollapse={() => setListOpen(false)} />
      ) : (
        <div className="list-collapsed">
          <button className="collapse-btn" onClick={() => setListOpen(true)} aria-label="Mostrar a lista" title="Mostrar a lista"><Chevron dir="right" double /></button>
          <span className="vlabel">{title} · {items.length}</span>
        </div>
      )}
      <MapView items={items} sel={sel} detail={detail} onSelect={setSelId} area={area} showArea={showArea} moving={moving}
        picking={report?.picking} onPick={report?.setPicked} pin={report?.pin}
        onCancelMove={() => setMoving(false)}
        onMoved={async (lat, lon) => {
          setMoving(false)
          await actions.patch(sel.id, { lat, lon }, 'Posição corrigida. O elemento passa a ter posição definida pelo técnico.')
        }} />
      {sel && (
        <Detail p={sel} detail={detail} tax={tax} byId={byId} actions={actions} busy={busy} flash={flash} readOnly={readOnly} report={report}
          onClose={() => setSelId(null)} onShow={setSelId} onStartMove={() => setMoving(true)} />
      )}
    </div>
  )
}
