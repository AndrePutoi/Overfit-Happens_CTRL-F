// Reclamações dos cidadãos: formulário (perfil público) e lista (público e técnico)
import { useEffect, useMemo, useState } from 'react'
import { api, complaintsExportPath, download } from '../api'
import { Editor, Icon, draftChanges, draftOf } from './common'
import { fmtDate } from '../tax'

export const KIND_INFO = {
  posicao: { label: 'Está no sítio errado', short: 'Posição errada', hint: 'Indique no mapa onde está realmente.' },
  estado: { label: 'Está partido, sujo ou vandalizado', short: 'Partido, sujo ou vandalizado', hint: 'Pode juntar uma foto.' },
  tipo: { label: 'O tipo está errado', short: 'Tipo errado', hint: 'Escolha o tipo certo.' },
  duplicado: { label: 'Aparece repetido no mapa', short: 'Duplicado', hint: 'Escolha o outro elemento.' },
  nao_mobiliario: { label: 'Não é um mobiliário urbano', short: 'Não é mobiliário urbano', hint: 'A deteção está errada.' },
  outro: { label: 'Outros', short: 'Outros', hint: 'Descreva o problema.' },
}
const KIND_ICONS = {
  posicao: <path d="M12 21s-7-6.2-7-11a7 7 0 0 1 14 0c0 4.8-7 11-7 11Z M12 7.5v5 M12 15h.01" />,
  estado: <path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.4-.6-.6-2.4Z" />,
  tipo: <path d="M4 7V4h16v3 M9 20h6 M12 4v16" />,
  duplicado: <path d="M9 9h11v11H9Z M5 15H4V4h11v1" />,
  nao_mobiliario: <path d="M12 3a9 9 0 1 0 0 18a9 9 0 1 0 0-18Z M5.6 5.6l12.8 12.8" />,
  outro: <path d="M12 3a9 9 0 1 0 0 18a9 9 0 1 0 0-18Z M8 12h.01 M12 12h.01 M16 12h.01" />,
}
const CONDITIONS = [['partido', 'Partido'], ['sujo', 'Sujo'], ['vandalizado', 'Vandalizado'], ['outro', 'Outro problema']]
export const STATUS_INFO = {
  por_resolver: { label: 'Por resolver', cls: 'st-open' },
  a_resolver: { label: 'A resolver', cls: 'st-doing' },
  resolvido: { label: 'Resolvido', cls: 'st-done' },
}

// "As minhas reclamações": os números ficam guardados só neste browser (o público não tem conta)
const MINE_KEY = 'ctrlf_minhas_reclamacoes'
export function myComplaintIds() {
  try {
    const v = JSON.parse(localStorage.getItem(MINE_KEY) || '[]')
    return Array.isArray(v) ? v : []
  } catch {
    return []
  }
}
function rememberMine(id) {
  try {
    localStorage.setItem(MINE_KEY, JSON.stringify([...new Set([...myComplaintIds(), id])]))
  } catch {
    /* sem armazenamento: a reclamação fica feita, só não aparece em "As minhas" */
  }
}

export function distanceM(a, b) {
  const R = 6371000
  const toRad = (x) => (x * Math.PI) / 180
  const dLat = toRad(b.lat - a.lat)
  const dLon = toRad(b.lon - a.lon)
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLon / 2) ** 2
  return 2 * R * Math.asin(Math.sqrt(h))
}

function KindIcon({ kind, size = 20 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {KIND_ICONS[kind]}
    </svg>
  )
}

export function StatusBadge({ status }) {
  const s = STATUS_INFO[status] || STATUS_INFO.por_resolver
  return <span className={`st-badge ${s.cls}`}>{s.label}</span>
}

// ------------------------------------------------------------ formulário (no painel do elemento)

export function ComplaintForm({ p, nearby, tax, picked, onStartPick, onStopPick, onSent, onCancel }) {
  const [kind, setKind] = useState(null)
  const [condition, setCondition] = useState(null)
  const [photo, setPhoto] = useState(null)
  const [message, setMessage] = useState('')
  const [draft, setDraft] = useState(draftOf(p))
  const [dupId, setDupId] = useState(null)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (kind === 'posicao') onStartPick()
    else onStopPick()
  }, [kind]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => onStopPick(), []) // eslint-disable-line react-hooks/exhaustive-deps

  const typeChanged = Object.keys(draftChanges(p, draft)).length > 0
  const ready = kind && (
    (kind === 'posicao' && picked) || (kind === 'estado' && condition) || (kind === 'tipo' && typeChanged) || (kind === 'duplicado' && dupId)
    || kind === 'nao_mobiliario' || (kind === 'outro' && message.trim().length >= 5)
  )
  const movedM = picked ? Math.round(distanceM(p, picked)) : null

  const send = async () => {
    setSending(true)
    setError(null)
    try {
      const fields = { element_id: p.id, kind, message: message.trim() }
      if (kind === 'posicao') Object.assign(fields, { lat: picked.lat.toFixed(7), lon: picked.lon.toFixed(7) })
      if (kind === 'estado') fields.condition = condition
      if (kind === 'tipo') {
        fields.suggested = JSON.stringify({ class: draft.class, subclass: draft.subclass, install_type: draft.install_type, color: draft.color })
      }
      if (kind === 'duplicado') fields.duplicate_of = dupId
      const c = await api.createComplaint(fields, kind === 'estado' ? photo : null)
      rememberMine(c.id)
      onSent(c)
    } catch (e) {
      setError(e.message)
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="complaint-form">
      <div className="lbl">O que se passa com este equipamento?</div>
      <div className="kind-grid">
        {Object.entries(KIND_INFO).map(([k, info]) => (
          <button key={k} className={`kind-opt${kind === k ? ' on' : ''}`} aria-pressed={kind === k} onClick={() => setKind(k)}>
            <KindIcon kind={k} />
            <span>{info.label}</span>
          </button>
        ))}
      </div>

      {kind === 'posicao' && (
        <div className="cf-block">
          {picked ? (
            <p>Posição proposta a <b>{movedM} m</b> da atual. Pode clicar de novo no mapa para a mudar.</p>
          ) : (
            <p className="cf-callout">Clique no mapa no sítio onde o equipamento está realmente.</p>
          )}
        </div>
      )}

      {kind === 'estado' && (
        <div className="cf-block">
          <div className="chips">
            {CONDITIONS.map(([c, label]) => (
              <button key={c} className={`chip${condition === c ? ' on' : ''}`} aria-pressed={condition === c} onClick={() => setCondition(c)}>{label}</button>
            ))}
          </div>
          <label className="file-pick">
            <input type="file" accept="image/jpeg,image/png,image/webp,image/heic" capture="environment"
              onChange={(e) => setPhoto(e.target.files?.[0] || null)} />
            {photo ? `Foto: ${photo.name}` : 'Juntar uma foto (opcional)'}
          </label>
          <p className="cf-note">Não fotografe pessoas nem matrículas. A foto só é vista pelos técnicos da câmara.</p>
        </div>
      )}

      {kind === 'tipo' && (
        <div className="cf-block">
          <Editor p={p} draft={draft} setDraft={setDraft} tax={tax} />
          {!typeChanged && <p className="cf-note">Escolha um tipo diferente do atual.</p>}
        </div>
      )}

      {kind === 'duplicado' && (
        <div className="cf-block">
          {nearby.length ? (
            <>
              <p>Qual é o elemento repetido?</p>
              <div className="dup-pick">
                {nearby.map(({ o, d }) => (
                  <button key={o.id} className={`dup-opt${dupId === o.id ? ' on' : ''}`} aria-pressed={dupId === o.id} onClick={() => setDupId(o.id)}>
                    <Icon el={o} size={24} />
                    <span><b>{o.name}</b><small>{o.id} · a {Math.round(d)} m</small></span>
                  </button>
                ))}
              </div>
            </>
          ) : (
            <p className="cf-note">Não há outros elementos desta categoria a menos de 60 m deste.</p>
          )}
        </div>
      )}

      {kind === 'nao_mobiliario' && (
        <div className="cf-block">
          <p>O sistema detetou aqui um equipamento que não existe ou que não é mobiliário urbano (por exemplo, um cartaz ou uma montra). Se quiser, explique no comentário.</p>
        </div>
      )}

      {kind && (
        <div className="cf-block">
          <label className="lbl" htmlFor="cf-msg">{kind === 'outro' ? 'Descreva o problema' : 'Comentário (opcional)'}</label>
          <textarea id="cf-msg" rows={kind === 'outro' ? 4 : 3} maxLength={1000} value={message} onChange={(e) => setMessage(e.target.value)}
            placeholder={kind === 'outro' ? 'Ex.: o sinal está tapado por uma árvore' : 'Acrescente o que achar útil'} />
          <p className="cf-note">Não escreva dados pessoais. O comentário só é visto pelos técnicos da câmara.</p>
        </div>
      )}

      {error && <div className="flash err" style={{ margin: 0 }} role="alert">{error}</div>}
      <div className="two">
        <button className="btn btn-ghost" onClick={onCancel}>Cancelar</button>
        <button className="btn btn-dark" disabled={!ready || sending} onClick={send}>{sending ? 'A enviar…' : 'Enviar reclamação'}</button>
      </div>
    </div>
  )
}

// ------------------------------------------------------------ cartão de uma reclamação

function Photo({ id }) {
  const [url, setUrl] = useState(null)
  const [err, setErr] = useState(null)
  useEffect(() => () => { if (url) URL.revokeObjectURL(url) }, [url])
  if (url) return <a href={url} target="_blank" rel="noreferrer"><img className="c-photo" src={url} alt="Foto enviada pelo cidadão" /></a>
  return (
    <button className="btn-small" onClick={() => api.complaintPhotoUrl(id).then(setUrl).catch((e) => setErr(e.message))}>
      {err || 'Ver foto'}
    </button>
  )
}

function PairTile({ p, id, name, onClick }) {
  return (
    <button className="c-tile" onClick={onClick} title="Ver no mapa">
      <div className="c-tile-img">
        {p?.best?.crop_url ? <img src={p.best.crop_url} alt="" loading="lazy" /> : p ? <Icon el={p} size={40} /> : null}
      </div>
      <span className="c-tile-name">{p && <Icon el={p} size={18} />}<b>{p?.name || name || id}</b></span>
      <small>{id}</small>
    </button>
  )
}

function ComplaintCard({ c, isTech, mine, el, other, onShow, onStatus, onResponse, onApply, busy }) {
  const [resp, setResp] = useState(c.response || '')
  useEffect(() => setResp(c.response || ''), [c.response])
  const active = el && ['auto', 'validado', 'corrigido'].includes(el.status)
  const apply = {
    posicao: active && 'Mover para a posição proposta',
    tipo: active && 'Aplicar o tipo proposto',
    duplicado: active && c.duplicate_of && `Juntar a ${c.duplicate_of}`,
    nao_mobiliario: active && 'Rejeitar o elemento (falso positivo)',
  }[c.kind]

  return (
    <article className={`c-card ${STATUS_INFO[c.status]?.cls || ''}`}>
      <div className="c-head">
        <span className="c-kind"><KindIcon kind={c.kind} size={18} />{KIND_INFO[c.kind]?.short}</span>
        <StatusBadge status={c.status} />
      </div>
      <div className="c-meta">
        Reclamação n.º {c.id} · {fmtDate(c.created_at)}
        {mine && <span className="c-mine">A minha</span>}
      </div>
      {c.kind === 'duplicado' ? (
        <div className="c-pair-wrap">
          <div className="c-pair">
            <PairTile p={el} id={c.element_id} name={c.element_name} onClick={() => onShow(c)} />
            <span className="c-pair-eq" aria-hidden="true">=</span>
            <PairTile p={other} id={c.duplicate_of} name={c.duplicate_name} onClick={() => onShow(c)} />
          </div>
          <button className="btn-small" onClick={() => onShow(c)}>
            Ver os dois no mapa{el && other ? ` · a ${Math.round(distanceM(el, other))} m um do outro` : ''}
          </button>
        </div>
      ) : (
      <button className="c-element" onClick={() => onShow(c)} title="Ver no mapa">
        {el ? <Icon el={el} size={26} /> : null}
        <span><b>{c.element_name || c.element_id}</b><small>{c.element_id} · ver no mapa</small></span>
      </button>
      )}

      <div className="c-body">
        {c.kind === 'posicao' && <p>Posição proposta a <b>{c.suggested_distance_m != null ? `${Math.round(c.suggested_distance_m)} m` : '—'}</b> da atual.</p>}
        {c.kind === 'estado' && <p>Estado: <b>{c.condition_label}</b>{c.has_photo && !isTech ? ' · com foto' : ''}</p>}
        {c.kind === 'tipo' && <p>Tipo proposto: <b>{c.suggested_label}</b></p>}
        {c.kind === 'duplicado' && <p>O cidadão diz que estes dois elementos são <b>o mesmo objeto</b>.</p>}
        {c.kind === 'nao_mobiliario' && <p>O cidadão diz que <b>não é mobiliário urbano</b>.</p>}
        {c.kind === 'outro' && !isTech && <p>Outro problema, descrito à câmara.</p>}
        {isTech && c.message && <blockquote>{c.message}</blockquote>}
        {isTech && c.has_photo && <Photo id={c.id} />}
        {isTech && el && !active && <p className="cf-note">O elemento está {el.status}: já não está no mapa.</p>}
      </div>

      {!isTech && c.response && (
        <div className="c-response"><b>Resposta da câmara</b>{c.response}</div>
      )}

      {isTech && (
        <div className="c-tech">
          {apply && c.status !== 'resolvido' && (
            <button className="btn btn-outline" disabled={busy} onClick={() => onApply(c)}>{apply}</button>
          )}
          <div className="seg" role="group" aria-label="Estado da reclamação">
            {Object.entries(STATUS_INFO).map(([s, info]) => (
              <button key={s} className={c.status === s ? 'on' : ''} aria-pressed={c.status === s} disabled={busy}
                onClick={() => c.status !== s && onStatus(c, s)}>{info.label}</button>
            ))}
          </div>
          <label className="lbl" htmlFor={`resp-${c.id}`}>Resposta ao cidadão (pública)</label>
          <textarea id={`resp-${c.id}`} rows={2} maxLength={1000} value={resp} onChange={(e) => setResp(e.target.value)}
            placeholder="Ex.: equipa de manutenção agendada para esta semana" />
          {resp !== (c.response || '') && (
            <button className="btn-small" disabled={busy} onClick={() => onResponse(c, resp)}>Guardar resposta</button>
          )}
          {c.updated_by && <small className="cf-note">Última alteração: {c.updated_by}, {fmtDate(c.updated_at)}</small>}
        </div>
      )}
    </article>
  )
}

// ------------------------------------------------------------ separador Reclamações

export function ComplaintsPage({ isTech, data, reload, byId, onShow, actions, elementFilter, clearElementFilter }) {
  const [status, setStatus] = useState(isTech ? 'por_resolver' : 'todas')
  const [kinds, setKinds] = useState(new Set())
  const [onlyMine, setOnlyMine] = useState(false)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)
  const mine = useMemo(() => new Set(myComplaintIds()), [data])
  useEffect(() => { reload() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const counts = data?.counts || { por_resolver: 0, a_resolver: 0, resolvido: 0 }
  const items = (data?.items || []).filter((c) => (status === 'todas' || c.status === status)
    && (!kinds.size || kinds.has(c.kind))
    && (!onlyMine || mine.has(c.id))
    && (!elementFilter || c.element_id === elementFilter || c.duplicate_of === elementFilter))

  const toggleKind = (k) => setKinds((s) => { const n = new Set(s); n.has(k) ? n.delete(k) : n.add(k); return n })
  const patch = async (c, body, msg) => {
    setBusy(true)
    try {
      await api.patchComplaint(c.id, body)
      await reload()
      if (msg) setMsg({ text: msg })
    } catch (e) {
      setMsg({ text: e.message, err: true })
    } finally {
      setBusy(false)
    }
  }
  const applySuggestion = async (c) => {
    setBusy(true)
    let ok = false
    if (c.kind === 'posicao') ok = await actions.patch(c.element_id, { lat: c.suggested_lat, lon: c.suggested_lon }, null)
    if (c.kind === 'tipo') ok = await actions.patch(c.element_id, c.suggested, null)
    if (c.kind === 'duplicado') ok = await actions.merge(c.element_id, c.duplicate_of)
    if (c.kind === 'nao_mobiliario') ok = await actions.reject(c.element_id, null)
    setBusy(false)
    if (ok) await patch(c, { status: 'resolvido', ...(c.response ? {} : { response: 'Corrigido no mapa. Obrigado pela ajuda!' }) },
      `Reclamação n.º ${c.id}: correção aplicada e marcada como resolvida.`)
  }

  const tabs = [
    ['por_resolver', 'Por resolver', counts.por_resolver],
    ['a_resolver', 'A resolver', counts.a_resolver],
    ['resolvido', 'Resolvidas', counts.resolvido],
    ['todas', 'Todas', counts.por_resolver + counts.a_resolver + counts.resolvido],
  ]

  return (
    <div className="page">
      <div className="page-head">
        <div className="txt">
          <h1>{isTech ? 'Reclamações dos cidadãos' : 'Reclamações'}</h1>
          <p>{isTech
            ? 'Problemas reportados no mapa público. Marque cada um como a resolver ou resolvido; a resposta fica visível para o cidadão.'
            : 'Para reportar um problema, abra um elemento no mapa e carregue em "Reportar um problema". Aqui acompanha o estado de todas as reclamações.'}</p>
        </div>
        {isTech && (
          <button className="btn btn-primary" onClick={() => download(complaintsExportPath()).catch((e) => setMsg({ text: e.message, err: true }))}>
            Descarregar reclamações (CSV)
          </button>
        )}
      </div>

      {msg && <div className={`flash${msg.err ? ' err' : ''}`} style={{ margin: 0 }} role="status">{msg.text}</div>}
      <div className="c-filters">
        <div className="seg big" role="tablist" aria-label="Estado">
          {tabs.map(([k, label, n]) => (
            <button key={k} role="tab" aria-selected={status === k} className={status === k ? 'on' : ''} onClick={() => setStatus(k)}>
              {label} <span className="n">{n}</span>
            </button>
          ))}
        </div>
        <div className="chips">
          {Object.entries(KIND_INFO).map(([k, info]) => (
            <button key={k} className={`chip${kinds.has(k) ? ' on' : ''}`} aria-pressed={kinds.has(k)} onClick={() => toggleKind(k)}>
              <KindIcon kind={k} size={16} />{info.short}
            </button>
          ))}
          {!isTech && mine.size > 0 && (
            <button className={`chip${onlyMine ? ' on' : ''}`} aria-pressed={onlyMine} onClick={() => setOnlyMine(!onlyMine)}>Só as minhas ({mine.size})</button>
          )}
          {elementFilter && (
            <button className="chip on" onClick={clearElementFilter}>Elemento {elementFilter} ✕</button>
          )}
        </div>
      </div>

      {!data && <p className="empty">A carregar…</p>}
      {data && !items.length && <p className="empty">Não há reclamações {status === 'todas' ? '' : `"${tabs.find((t) => t[0] === status)[1].toLowerCase()}"`} com estes filtros.</p>}
      <div className="c-grid">
        {items.map((c) => (
          <ComplaintCard key={c.id} c={c} isTech={isTech} mine={!isTech && mine.has(c.id)} el={byId[c.element_id]} other={c.duplicate_of ? byId[c.duplicate_of] : null} busy={busy}
            onShow={onShow}
            onStatus={(x, s) => patch(x, { status: s }, `Reclamação n.º ${x.id}: ${STATUS_INFO[s].label.toLowerCase()}.`)}
            onResponse={(x, r) => patch(x, { response: r }, 'Resposta guardada.')}
            onApply={applySuggestion} />
        ))}
      </div>
    </div>
  )
}
