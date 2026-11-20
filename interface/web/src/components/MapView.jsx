import { useEffect, useMemo, useRef } from 'react'
import { Circle, CircleMarker, MapContainer, Marker, Polygon, Polyline, TileLayer, Tooltip, useMap, useMapEvents } from 'react-leaflet'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { iconFor, iconKey } from '../tax'

const iconCache = new Map()
function markerIcon(p, selected) {
  const key = `${iconKey(p)}|${selected}`
  if (!iconCache.has(key)) {
    const size = selected ? 42 : 28
    iconCache.set(key, L.divIcon({
      className: `marker-icon${selected ? ' sel' : ''}`,
      html: `<div class="pin">${iconFor(p, size)}</div>`,
      iconSize: [size, size],
      iconAnchor: [size / 2, size / 2],
    }))
  }
  return iconCache.get(key)
}

// Ajusta a vista: zona piloto no início, e segue o elemento selecionado se sair do ecrã
function Controller({ area, sel, pin }) {
  const map = useMap()
  const fitted = useRef(false)
  useEffect(() => {
    if (fitted.current) return
    // ao abrir o mapa já com um elemento escolhido (catálogo, reclamações), começar nele
    if (sel) {
      map.setView([sel.lat, sel.lon], 19)
      fitted.current = true
    } else if (area?.length) {
      map.fitBounds(area, { padding: [20, 20] })
      fitted.current = true
    }
  }, [area, map]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    // ao esconder/mostrar a lista ou o detalhe, o mapa muda de largura
    const ro = new ResizeObserver(() => map.invalidateSize())
    ro.observe(map.getContainer())
    return () => ro.disconnect()
  }, [map])
  useEffect(() => {
    // o contentor do mapa muda de tamanho quando o painel de detalhe abre ou fecha:
    // primeiro corrigir o tamanho, depois centrar o elemento se estiver fora da vista
    const t = setTimeout(() => {
      map.invalidateSize()
      if (!sel) return
      const ll = L.latLng(sel.lat, sel.lon)
      if (pin) {   // posição proposta numa reclamação: mostrar o elemento e o ponto proposto
        map.fitBounds(L.latLngBounds([ll, L.latLng(pin.lat, pin.lon)]), { padding: [80, 80], maxZoom: 19 })
        return
      }
      if (!map.getBounds().pad(-0.2).contains(ll)) map.setView(ll, Math.max(map.getZoom(), 19))
    }, 60)
    return () => clearTimeout(t)
  }, [sel?.id, sel?.lat, sel?.lon, pin?.lat, pin?.lon, !!pin?.label, map])
  return null
}

// Escolher um ponto no mapa (reclamação de posição errada)
function PickHandler({ picking, onPick }) {
  useMapEvents({ click: (e) => { if (picking) onPick({ lat: e.latlng.lat, lon: e.latlng.lng }) } })
  return null
}


// centro inicial: o meio da zona do município (vem de /config); sem zona, Portugal continental
function startCenter(area) {
  if (!area?.length) return [39.6, -8.0]
  const lat = area.reduce((s, p) => s + p[0], 0) / area.length
  const lon = area.reduce((s, p) => s + p[1], 0) / area.length
  return [lat, lon]
}

export default function MapView({ items, sel, detail, onSelect, moving, onMoved, onCancelMove, area, showArea = true, picking, onPick, pin }) {
  const markers = useMemo(() => items.map((p) => (
    <Marker key={p.id} position={[p.lat, p.lon]} icon={markerIcon(p, false)}
      eventHandlers={{ click: () => { if (!picking) onSelect(p.id) } }} title={`${p.name} · ${p.id}`} />
  )), [items, onSelect, picking])

  const cams = detail && sel && detail.id === sel.id ? detail.properties.observations_detail || [] : []
  const orig = sel?.position_original
  const showOrig = orig && orig.lat != null && (Math.abs(orig.lat - sel.lat) > 1e-6 || Math.abs(orig.lon - sel.lon) > 1e-6)

  return (
    <section className={`map-col${picking ? ' picking' : ''}`} aria-label="Mapa">
      {picking && !moving && (
        <div className="map-banner">Clique no mapa onde {sel?.name ? `o elemento "${sel.name}"` : 'o equipamento'} está realmente</div>
      )}
      {moving && (
        <div className="map-banner">
          Arraste o símbolo de {sel?.id} para a posição certa
          <button onClick={onCancelMove}>Cancelar</button>
        </div>
      )}
      <MapContainer center={startCenter(area)} zoom={area?.length ? 16 : 7} maxZoom={21} zoomControl>
        <TileLayer
          attribution='&copy; colaboradores do <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> · imagens © Mapillary, CC BY-SA 4.0'
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png" maxNativeZoom={19} maxZoom={21} />
        <Controller area={area} sel={sel} pin={pin?.label ? pin : null} />
        <PickHandler picking={picking} onPick={onPick} />
        {area && showArea && <Polygon positions={area} pathOptions={{ color: '#1F5FAD', weight: 2, dashArray: '6 6', fill: false }} />}
        {markers}
        {sel && (
          <>
            <Circle center={[sel.lat, sel.lon]} radius={sel.uncertainty_m}
              pathOptions={sel.position_reliable
                ? { color: '#1E7A4C', weight: 2, fillOpacity: 0.08 }
                : { color: '#B26B00', weight: 2, dashArray: '6 6', fillOpacity: 0.06 }} />
            {cams.map((o) => o.cam_lat != null && (
              <Polyline key={`l${o.detection_id}`} positions={[[o.cam_lat, o.cam_lon], [sel.lat, sel.lon]]}
                pathOptions={{ color: '#1F5FAD', weight: 2, dashArray: '4 6', opacity: 0.8 }} />
            ))}
            {cams.map((o) => o.cam_lat != null && (
              <CircleMarker key={`c${o.detection_id}`} center={[o.cam_lat, o.cam_lon]} radius={6}
                pathOptions={{ color: '#FFFFFF', weight: 2, fillColor: '#1F5FAD', fillOpacity: 1 }}>
                <Tooltip>Câmara · {o.captured_at ? new Date(o.captured_at).toLocaleDateString('pt-PT') : ''}</Tooltip>
              </CircleMarker>
            ))}
            {showOrig && (
              <CircleMarker center={[orig.lat, orig.lon]} radius={5} pathOptions={{ color: '#5A6478', weight: 2, fillOpacity: 0 }}>
                <Tooltip>Posição antes do ajuste à estrada ({Math.round(sel.road_adjustment_m || 0)} m)</Tooltip>
              </CircleMarker>
            )}
            {pin && (
              <>
                <Polyline positions={[[sel.lat, sel.lon], [pin.lat, pin.lon]]} pathOptions={{ color: '#7A3FC4', weight: 2, dashArray: '5 6' }} />
                <CircleMarker center={[pin.lat, pin.lon]} radius={9} pathOptions={{ color: '#FFFFFF', weight: 3, fillColor: '#7A3FC4', fillOpacity: 1 }}>
                  <Tooltip permanent direction="right" offset={[10, 0]}>{pin.label || 'Posição proposta'}</Tooltip>
                </CircleMarker>
              </>
            )}
            <Marker key={`sel-${sel.id}-${moving}`} position={[sel.lat, sel.lon]} icon={markerIcon(sel, true)}
              zIndexOffset={1000} draggable={moving}
              eventHandlers={{ dragend: (e) => { const ll = e.target.getLatLng(); onMoved(ll.lat, ll.lng) } }} />
          </>
        )}
      </MapContainer>
    </section>
  )
}
