import { useState } from 'react'
import { iconSvg, iconFor, confColor, ECO, signGroups, signTypes } from '../tax'

// el: elemento (ícone específico do tipo); kind/color: ícone genérico do grupo
export function Icon({ el, kind, color, size = 28 }) {
  const html = el ? iconFor(el, size) : iconSvg(kind, color, size)
  return <span style={{ display: 'inline-flex', flexShrink: 0 }} dangerouslySetInnerHTML={{ __html: html }} />
}

export function CloseButton({ onClick, label = 'Fechar' }) {
  return (
    <button className="close-btn" onClick={onClick} aria-label={label}>
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true">
        <path d="M6 6l12 12M18 6 6 18" />
      </svg>
    </button>
  )
}

export function SearchBox({ value, onChange, placeholder = 'Pesquisar por nome, ID ou tipo' }) {
  return (
    <label className="search">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#4A5468" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
        <circle cx="11" cy="11" r="6.5" />
        <path d="m16 16 4.5 4.5" />
      </svg>
      <span className="sr-only">Pesquisar</span>
      <input type="search" placeholder={placeholder} value={value} onChange={(e) => onChange(e.target.value)} />
    </label>
  )
}

export function ConfBar({ pct, small }) {
  const fill = { height: '100%', width: `${pct}%`, background: confColor(pct) }
  if (small) {
    return (
      <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span className="minibar"><span style={fill} /></span>
        <b>{pct}%</b>
      </span>
    )
  }
  return (
    <span className="confbar">
      <span className="track"><span style={fill} /></span>
      <b>{pct}%</b>
    </span>
  )
}

export function Fact({ k, children, full }) {
  return (
    <div className={`fact${full ? ' full' : ''}`}>
      <span className="k">{k}</span>
      <span className="v">{children}</span>
    </div>
  )
}

export function positionText(p) {
  const m = Math.round(p.uncertainty_m)
  if (p.geo_method === 'manual') return <>± {m} m <small>· ajustada pelo técnico</small></>
  if (p.position_reliable) return <>± {m} m <small>· {p.auto_merged ? 'combinada de várias deteções' : `triangulada (${p.n_views} câmaras)`}</small></>
  return <>± {m} m <small>· aproximada (vista numa só imagem)</small></>
}

// Região da imagem a mostrar em modo aproximado: o objeto ao centro, com margem,
// na proporção 4:3 da caixa de visualização (sem sair da imagem)
function zoomRegion(W, H, [x1, y1, x2, y2]) {
  const bw = x2 - x1
  const bh = y2 - y1
  let rw = Math.max(bw * 2.4, ((bh * 2.4) * 4) / 3, 160)
  rw = Math.min(rw, W, (H * 4) / 3)
  const rh = (rw * 3) / 4
  const cx = (x1 + x2) / 2
  const cy = (y1 + y2) / 2
  const rx = Math.min(Math.max(cx - rw / 2, 0), W - rw)
  const ry = Math.min(Math.max(cy - rh / 2, 0), H - rh)
  return { rx, ry, rw, rh }
}

// Imagem da observação com a caixa da deteção desenhada por cima.
// zoomed: mostra só a zona à volta do objeto (aproximado); senão, a imagem completa.
export function ImageWithBox({ obs, label, onZoom, zoomed = false, onToggleZoom }) {
  if (!obs || !obs.image_url) {
    return (
      <div className="imgbox">
        <div className="noimg">Sem imagem disponível</div>
      </div>
    )
  }
  const W = obs.width || obs.image_width
  const H = obs.height || obs.image_height
  const bb = obs.bbox || [0, 0, 0, 0]
  const [x1, y1, x2, y2] = bb
  const pct = (v) => `${v}%`
  let imgStyle
  let box = null
  let frameStyle
  if (zoomed && W && H) {
    const { rx, ry, rw, rh } = zoomRegion(W, H, bb)
    frameStyle = { aspectRatio: '4 / 3' }
    imgStyle = { position: 'absolute', maxWidth: 'none', width: pct((100 * W) / rw), left: pct((-100 * rx) / rw), top: pct((-100 * ry) / rh) }
    // aproximada: sem caixa, o objeto já está ao centro
  } else if (W && H) {
    box = { left: pct((100 * x1) / W), top: pct((100 * y1) / H), width: pct((100 * (x2 - x1)) / W), height: pct((100 * (y2 - y1)) / H) }
  }
  return (
    <div>
      <div className="imgbox" style={frameStyle}>
        <img src={obs.image_url} alt="Imagem de rua com o elemento assinalado" style={imgStyle} />
        {box && <div className="bbox" style={box} />}
        <span className="tag bl">Rostos e matrículas desfocados</span>
        {label && <span className="tag br">{label}</span>}
        <span className="img-btns">
          {onToggleZoom && <button className="zoom-btn" onClick={onToggleZoom}>{zoomed ? 'Imagem completa' : 'Aproximar'}</button>}
          {onZoom && <button className="zoom-btn" onClick={onZoom}>Ampliar</button>}
        </span>
      </div>
      <div className="img-credit">Imagem © {obs.source_name || 'Mapillary'} e colaboradores · {obs.license || 'CC BY-SA 4.0'}</div>
    </div>
  )
}

export function Lightbox({ obs, onClose }) {
  return (
    <div className="lightbox" role="dialog" aria-label="Imagem ampliada" onClick={onClose}>
      <CloseButton onClick={onClose} />
      <div onClick={(e) => e.stopPropagation()} style={{ width: '100%', display: 'flex', justifyContent: 'center' }}>
        <ImageWithBox obs={obs} />
      </div>
    </div>
  )
}

// Fila de miniaturas (recortes) das observações do elemento
export function ObservationStrip({ obs, current, onPick }) {
  if (!obs || obs.length < 2) return null
  return (
    <div className="obs-strip">
      {obs.map((o, i) => (
        <button key={o.detection_id} className={`obs-thumb${i === current ? ' on' : ''}`} onClick={() => onPick(i)}
          title={`Imagem ${i + 1} · pontuação ${Math.round(o.score * 100)}%`}>
          {o.crop_url ? <img src={o.crop_url} alt="" loading="lazy" /> : null}
          {o.is_best && <span className="star">★</span>}
        </button>
      ))}
    </div>
  )
}

// Visualização de uma observação + ações sobre ela (melhor imagem, separar)
export function ObservationViewer({ detail, onSetBest, onSplit, busy }) {
  const obs = detail?.observations_detail || []
  const [idx, setIdx] = useState(0)
  const [zoom, setZoom] = useState(false)
  const [zoomed, setZoomed] = useState(true)
  const i = Math.min(idx, Math.max(0, obs.length - 1))
  const o = obs[i]
  return (
    <div>
      <ImageWithBox obs={o} label={obs.length ? `Imagem ${i + 1} de ${obs.length}` : null} zoomed={zoomed}
        onToggleZoom={o ? () => setZoomed(!zoomed) : null} onZoom={o ? () => setZoom(true) : null} />
      <ObservationStrip obs={obs} current={i} onPick={setIdx} />
      {o && (onSetBest || onSplit) && obs.length > 1 && (
        <div className="obs-actions">
          {!o.is_best && onSetBest && (
            <button className="btn-small" disabled={busy} onClick={() => onSetBest(o.detection_id)}>Usar como imagem principal</button>
          )}
          {onSplit && (
            <button className="btn-small" disabled={busy} onClick={() => { onSplit(o.detection_id); setIdx(0) }}>
              Separar esta imagem (é outro objeto)
            </button>
          )}
        </div>
      )}
      {zoom && o && <Lightbox obs={o} onClose={() => setZoom(false)} />}
    </div>
  )
}

// ---------- editor de tipo (sinais, iluminação, resíduos)

export const draftOf = (p) => ({ class: p.class, subclass: p.subclass, install_type: p.install_type, color: p.color, sign_group: p.sign_group })

export function draftChanges(p, d) {
  const out = {}
  for (const k of ['class', 'subclass', 'install_type', 'color']) if ((d[k] ?? null) !== (p[k] ?? null)) out[k] = d[k] ?? null
  return out
}

function Chip({ on, onClick, children, swatch }) {
  return (
    <button className={`chip${on ? ' on' : ''}`} aria-pressed={on} onClick={onClick}>
      {swatch && <span className="swatch" style={{ background: swatch }} />}
      {children}
    </button>
  )
}

export function Editor({ p, draft, setDraft, tax }) {
  const set = (patch) => setDraft({ ...draft, ...patch })
  if (p.family === 'sinal') {
    const types = signTypes(tax, draft.sign_group)
    return (
      <div className="editor">
        <div>
          <div className="lbl">Grupo do sinal</div>
          <div className="chips">
            {signGroups(tax).map(([g, label]) => (
              <Chip key={g} on={draft.sign_group === g} onClick={() => set({ sign_group: g, subclass: signTypes(tax, g)[0]?.key })}>{label}</Chip>
            ))}
          </div>
        </div>
        {types.length > 0 && (
          <div>
            <div className="lbl">Sinal</div>
            <div className="chips">
              {types.map((t) => (
                <Chip key={t.key} on={draft.subclass === t.key} onClick={() => set({ subclass: t.key })}>
                  {t.nome}{t.codigo && <small>{t.codigo}</small>}
                </Chip>
              ))}
            </div>
          </div>
        )}
      </div>
    )
  }
  if (p.family === 'mobiliario') {
    return (
      <div className="editor">
        <div>
          <div className="lbl">Tipo de mobiliário</div>
          <div className="chips"><Chip on>Banco</Chip></div>
          <p className="cf-note" style={{ marginTop: 8 }}>Por agora o pipeline só deteta bancos. Se não for um banco, rejeite o elemento.</p>
        </div>
      </div>
    )
  }
  if (p.family === 'iluminacao') {
    return (
      <div className="editor">
        <div>
          <div className="lbl">Tipo de iluminação</div>
          <div className="chips">
            <Chip on={draft.class === 'candeeiro'} onClick={() => set({ class: 'candeeiro' })}>Candeeiro</Chip>
            <Chip on={draft.class === 'poste_luz'} onClick={() => set({ class: 'poste_luz' })}>Poste de iluminação</Chip>
          </div>
        </div>
      </div>
    )
  }
  const colors = tax ? Object.entries(tax.cores_ecoponto) : []
  const showColor = draft.class === 'subterraneo' || draft.install_type === 'ilha'
  return (
    <div className="editor">
      <div>
        <div className="lbl">Equipamento</div>
        <div className="chips">
          <Chip on={draft.class === 'contentor'} onClick={() => set({ class: 'contentor', install_type: draft.class === 'contentor' ? draft.install_type : null })}>Contentor de superfície</Chip>
          <Chip on={draft.class === 'subterraneo'} onClick={() => set({ class: 'subterraneo', install_type: 'subterraneo' })}>Subterrâneo</Chip>
        </div>
      </div>
      {draft.class === 'contentor' && (
        <div>
          <div className="lbl">Tipo</div>
          <div className="chips">
            <Chip on={draft.install_type === 'ilha'} onClick={() => set({ install_type: 'ilha' })}>Ilha de reciclagem</Chip>
            <Chip on={draft.install_type === 'indiferenciado'} onClick={() => set({ install_type: 'indiferenciado', color: null })}>Indiferenciado</Chip>
          </div>
        </div>
      )}
      {showColor && (
        <div>
          <div className="lbl">Cor do ecoponto</div>
          <div className="chips">
            {colors.map(([c, info]) => (
              <Chip key={c} on={draft.color === c} swatch={ECO[c]} onClick={() => set({ color: draft.color === c ? null : c })}>
                {info.label} · {info.residuo}
              </Chip>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ---------- caixa de duplicados

export function DuplicateBox({ p, detail, byId, onMerge, onShow, busy }) {
  const dup = detail?.duplicates
  if (!dup) return null
  const others = (dup.others || []).filter((o) => ['auto', 'validado', 'corrigido'].includes(o.status))
  if (!others.length) return null
  return (
    <div className="dup-box">
      <div className="t">
        {dup.level === 'provavel' ? 'Provável duplicado' : 'Possível duplicado'}
        {dup.confidence != null && <span className="dup-conf"> · {Math.round(dup.confidence * 100)}% de probabilidade</span>}
      </div>
      {others.map((o) => {
        const keepOther = dup.suggested_keep === o.id
        return (
          <div key={o.id} style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <p>
              <b>{o.id}</b> ({byId[o.id]?.name || o.name}) está a {o.distance_m != null ? `${Math.round(o.distance_m)} m` : 'poucos metros'}
              {o.shared_image ? ', mas aparece na mesma imagem (em regra são objetos diferentes).' : '.'}
              {' '}Sugestão do sistema: manter {dup.suggested_keep === p.id ? 'este' : dup.suggested_keep}.
            </p>
            <div className="btns">
              {keepOther ? (
                <button className="btn btn-amber" disabled={busy} onClick={() => onMerge(p.id, o.id)}>Juntar este a {o.id}</button>
              ) : (
                <button className="btn btn-amber" disabled={busy} onClick={() => onMerge(o.id, p.id)}>Juntar {o.id} a este</button>
              )}
              <button className="btn-small" onClick={() => onShow(o.id)}>Ver {o.id}</button>
            </div>
          </div>
        )
      })}
    </div>
  )
}
