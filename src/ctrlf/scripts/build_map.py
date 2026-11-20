"""Mapa HTML (Leaflet) para ver o que foi detetado e a referência, sobre OpenStreetMap.

    python -m ctrlf.scripts.build_map                       # Aveiro -> data/catalog/aveiro/mapa.html
    python -m ctrlf.scripts.build_map --serve               # gera e abre em http://localhost:8765/mapa.html
    python -m ctrlf.scripts.build_map --city aveiro --out /caminho/mapa.html

Os mosaicos do OpenStreetMap só carregam se a página for servida por http (têm de levar Referer): abrir o ficheiro com duplo
clique mostra os pontos mas o fundo fica bloqueado. Por isso o `--serve`.

Camadas: deteções do catálogo (contentor, subterrâneo, sinais por família; contorno grosso = triangulado/confirmado), referência
OSM (ecopontos, papeleiras, sinais, candeeiros), candeeiros do Mapillary, posições das câmaras, caixa da zona piloto e os 4
subterrâneos do piloto. É um ficheiro único e LOCAL: os dados vão embutidos, só as peças do Leaflet e os mosaicos do mapa vêm da
rede quando se abre.

Ao clicar numa deteção mostra a(s) imagem(ns) ANONIMIZADA(S) (data/images_anon: rostos e matrículas desfocados) com a caixa
desenhada. As imagens NÃO vão embutidas: vêm de /images/<id>.jpg, que o `--serve` só serve a partir de images_anon e só para
ficheiros listados no manifest.jsonl (verificados pelo portão de privacidade). Os frames originais (data/raw) nunca são servidos.
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

from ctrlf.paths import ROOT
sys.path.insert(0, str(ROOT))
from ctrlf.geometry.geometry import single_view_position  # noqa: E402
from ctrlf.pipeline.avaliar_posicao import evaluate  # noqa: E402
PILOT = [[40.6405, -8.6560], [40.6460, -8.6440]]          # SW, NE (docs/zona-piloto-e-treino): a de Aveiro; as zonas novas usam a sua própria caixa (ingest/zonas.py)
CLASSES_MAPA = ("contentor", "subterraneo", "sinal", "poste_luz", "candeeiro", "banco")


def caixa_da_zona(city: str) -> list:
    """[[S, O], [N, E]] da zona registada em data/zonas/<city>/zona.json; senão a do piloto de Aveiro."""
    try:
        from ctrlf.ingest.zonas import caixa_swne, carregar
        z = carregar(city)
        if z:
            s, o, n, e = caixa_swne(z)
            return [[s, o], [n, e]]
    except Exception:
        pass
    return PILOT


def load(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["features"] if path.exists() else []


def pts(features, keep):
    """[[lat, lon, {props filtradas}]] de Points."""
    out = []
    for f in features:
        g = f.get("geometry") or {}
        if g.get("type") != "Point":
            continue
        lon, lat = g["coordinates"][:2]
        out.append([round(lat, 6), round(lon, 6), {k: f["properties"].get(k) for k in keep if f["properties"].get(k) is not None}])
    return out


def anon_files() -> set[str]:
    """Nomes das imagens anonimizadas verificadas (data/images_anon/manifest.jsonl) que existem no disco."""
    d = ROOT / "data" / "images_anon"
    m = d / "manifest.jsonl"
    if not m.exists():
        return set()
    names = {json.loads(l)["file"] for l in m.read_text(encoding="utf-8").splitlines() if l.strip()}
    return {n for n in names if (d / n).is_file()}


def make_thumb(image_id: str, bbox, dest: Path, side_min: int = 90) -> bool:
    """Recorte QUADRADO e anonimizado à volta da caixa (com contexto) -> miniatura 96x96. Só usa data/images_anon."""
    from PIL import Image
    src = ROOT / "data" / "images_anon" / f"{image_id}.jpg"
    if not src.is_file():
        return False
    im = Image.open(src).convert("RGB")
    x1, y1, x2, y2 = bbox
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    s = max(side_min, 1.5 * max(x2 - x1, y2 - y1)) / 2
    box = (max(0, cx - s), max(0, cy - s), min(im.width, cx + s), min(im.height, cy + s))
    im.crop(tuple(int(v) for v in box)).resize((96, 96), Image.LANCZOS).save(dest, quality=82)
    return True


def build(city: str, catalog: str = "catalog.geojson", thumbs: Path | None = None) -> dict:
    cat_doc = json.loads((ROOT / "data" / "catalog" / city / catalog).read_text(encoding="utf-8")) if (ROOT / "data" / "catalog" / city / catalog).exists() else {"features": []}
    cat = cat_doc["features"]
    if thumbs:
        thumbs.mkdir(parents=True, exist_ok=True)
    ref = ROOT / "data" / "reference"
    keep = ["id", "class", "subclass", "confidence", "n_views", "confirmado", "geo_method", "geo_residual_m", "image_id",
            "n_unidades", "ref_match", "status", "ajuste_m", "ajuste_metodo"]
    keep = [k for k in keep if k != "image_id"]
    obsf = ROOT / "data" / "catalog" / city / "observacoes.json"
    obs = json.loads(obsf.read_text(encoding="utf-8")) if obsf.exists() else {}
    ok = anon_files()
    det = {k: [] for k in CLASSES_MAPA}
    attr: dict[str, str] = {}
    for f in cat:
        pr = f["properties"]
        lon, lat = f["geometry"]["coordinates"][:2]
        p = {k: pr[k] for k in keep if pr.get(k) is not None}
        p["fonte"] = pr.get("source")
        if "confidence" in p:
            p["confidence"] = round(float(p["confidence"]), 2)
        if pr.get("attribution"):
            attr[pr.get("source")] = pr["attribution"]
        rays = []
        for x in obs.get(pr.get("id"), []):                      # raio de cada observação: câmara -> ponto estimado (azimute + distância)
            elat, elon = single_view_position(x["cam"][0], x["cam"][1], x["az"], x["dist_m"])
            rays.append([round(x["cam"][0], 6), round(x["cam"][1], 6), round(elat, 6), round(elon, 6), round(x["dist_m"], 1)])
        o = [[x["image_id"], [round(v) for v in x["bbox"]]] for x in obs.get(pr.get("id"), []) if f"{x['image_id']}.jpg" in ok]
        if not o and pr.get("image_id") and f"{pr['image_id']}.jpg" in ok and pr.get("bbox"):
            o = [[pr["image_id"], [round(v) for v in pr["bbox"]]]]
        th = 1 if (thumbs and o and make_thumb(o[0][0], o[0][1], thumbs / f"{pr['id']}.jpg")) else 0
        det.setdefault(pr.get("class", "sinal"), []).append([round(lat, 6), round(lon, 6), p, o[:3], rays, th])
    err, stats = [], {}
    try:                                                         # erro vs ecopontos OSM (só resíduos)
        ev = evaluate(city, catalog=catalog)
        stats = {"n_pares": ev["pares_1a1"]["n"], "erro_mediano_m": ev["pares_1a1"]["erro_m"].get("p50"),
                 "razao_dist": ev.get("por_observacao", {}).get("razao_distancia", {}).get("p50"),
                 "rumo_abs_graus": ev.get("por_observacao", {}).get("erro_rumo_graus", {}).get("abs_mediano"),
                 "prec10": ev["precisao_proxy"].get("<=10m"), "n_elem": ev["n_elementos"], "n_ref": ev["n_ref_osm"]}
        err = [[q["elem"][0], q["elem"][1], q["ref"][0], q["ref"][1], q["erro_m"], q["elemento"]] for q in ev["pares"]]
        by_id = {q["elemento"]: q for q in ev["pares"]}
        for k in ("contentor", "subterraneo"):
            for pt in det[k]:
                q = by_id.get(pt[2].get("id"))
                if q:
                    pt[2]["erro_vs_osm_m"] = q["erro_m"]
    except Exception as e:                                       # sem catálogo/referência: o mapa continua a funcionar
        print(f"aviso: sem avaliação de posição ({type(e).__name__}: {e})")
    cams, seen = [], set()
    meta = ROOT / "data" / "raw" / f"{city}_vistas" / "meta.jsonl"
    if meta.exists():
        for line in meta.read_text(encoding="utf-8").splitlines():
            m = json.loads(line)
            k = (round(m["lat"], 5), round(m["lon"], 5))
            if k not in seen:
                seen.add(k); cams.append([k[0], k[1], {"fonte": m.get("source"), "captured_at": m.get("captured_at")}])
    return {
        "cidade": city, "pilot": caixa_da_zona(city), "det": det, "attr": attr, "err": err, "stats": stats, "ajuste": cat_doc.get("ajuste"),
        "ref": {
            "reciclagem": pts(load(ref / f"osm_{city}_reciclagem.geojson"), ["name", "location", "recycling_type", "osm_id"]),
            "papeleiras": pts(load(ref / f"osm_{city}_papeleiras.geojson"), ["osm_id"]),
            "sinais": pts(load(ref / f"osm_{city}_sinais.geojson"), ["highway", "traffic_sign", "osm_id"]),
            "luz_osm": pts(load(ref / f"osm_{city}_luz.geojson"), ["tipo_osm", "osm_id"]),
            "luz_mly": pts(load(ref / f"mapillary_{city}_luz.geojson"), ["object_value", "last_seen_at"]),
            "subterraneos_piloto": pts(load(ref / "subterraneos_aveiro.geojson"), ["nota"]) if city == "aveiro" else [],
        },
        "cameras": cams,
    }


TEMPLATE = """<!doctype html>
<html lang="pt"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mapa de deteções — __CITY__</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet.markercluster/1.5.3/MarkerCluster.css">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet.markercluster/1.5.3/MarkerCluster.Default.css">
<style>
 html,body,#map{height:100%;margin:0}
 body{font:13px/1.4 system-ui,sans-serif}
 .box{background:#fff;padding:8px 10px;border-radius:6px;box-shadow:0 1px 5px rgba(0,0,0,.35);max-width:260px}
 .box h4{margin:0 0 4px;font-size:13px}
 .sw{display:inline-block;width:11px;height:11px;border-radius:50%;margin-right:5px;vertical-align:-1px;border:1px solid #0006}
 .sq{border-radius:2px}
 label{cursor:pointer}
 .leaflet-popup-content{max-height:68vh;overflow-y:auto}
 .thb{width:48px;height:48px;box-sizing:border-box;border:3px solid #888;border-radius:4px;background:#ccc;overflow:hidden}
 .thb img{width:100%;height:100%;object-fit:cover;display:block}
 .thb.cf{box-shadow:0 0 0 2px #000}
 .leaflet-div-icon.thd{background:none;border:none}
</style></head><body><div id="map"></div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet.markercluster/1.5.3/leaflet.markercluster.js"></script>
<script>
const D = __DATA__;
const map = L.map('map', {preferCanvas:true}).fitBounds(D.pilot, {padding:[20,20]});
// Mosaicos do OSM: o servidor recusa (403) páginas abertas como ficheiro local (sem Referer): usar scripts/build_map.py --serve
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom:20, maxNativeZoom:19,
  attribution:'© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'}).addTo(map);
if (location.protocol === 'file:') {
  const w = L.control({position:'topleft'});
  w.onAdd = () => { const d = L.DomUtil.create('div','box'); d.style.marginTop='60px';
    d.innerHTML = '<b>Sem mapa de fundo?</b> O OpenStreetMap bloqueia páginas abertas como ficheiro. Corre <code>python -m ctrlf.scripts.build_map --serve</code>.'; return d; };
  w.addTo(map);
}
L.rectangle(D.pilot, {color:'#444', weight:1, dashArray:'6 4', fill:false}).addTo(map).bindTooltip('Zona piloto');

const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const popup = p => Object.entries(p).map(([k,v]) => '<b>'+esc(k)+'</b>: '+esc(v)).join('<br>');
function popupDet(p, obs) {
  const d = document.createElement('div');
  const t = document.createElement('div'); t.innerHTML = popup(p); d.appendChild(t);
  (obs || []).forEach(([id, bb]) => {
    const w = document.createElement('div'); w.style.cssText = 'position:relative;margin-top:6px;line-height:0';
    const im = new Image(); im.src = '/images/' + id + '.jpg'; im.title = 'abrir em tamanho real';
    im.style.cssText = 'width:100%;max-width:420px;display:block;cursor:zoom-in';
    const b = document.createElement('div');
    b.style.cssText = 'position:absolute;border:2px solid #ff0;box-shadow:0 0 0 1px #000;pointer-events:none;display:none';
    im.onload = () => { const W = im.naturalWidth, H = im.naturalHeight;
      b.style.left = (bb[0]/W*100)+'%'; b.style.top = (bb[1]/H*100)+'%';
      b.style.width = ((bb[2]-bb[0])/W*100)+'%'; b.style.height = ((bb[3]-bb[1])/H*100)+'%'; b.style.display = 'block'; };
    im.onerror = () => { w.innerHTML = '<i style="line-height:1.3">imagem indisponível (abre com <code>build_map.py --serve</code>)</i>'; };
    im.onclick = () => window.open(im.src, '_blank');
    w.append(im, b); d.appendChild(w);
    const c = document.createElement('div'); c.style.cssText = 'font-size:11px;color:#555'; c.textContent = id; d.appendChild(c);
  });
  if (obs && obs.length) { const a = document.createElement('div'); a.style.cssText = 'font-size:11px;color:#555;margin-top:2px';
    a.textContent = (D.attr[p.fonte] || '') + ' (imagem anonimizada)'; d.appendChild(a); }
  return d;
}
// raios da observação: câmara -> posição estimada (azimute + distância). Ao abrir o popup destacam-se os do elemento.
let hl = null;
const hlClear = () => { if (hl) { map.removeLayer(hl); hl = null; } };
function hlShow(rays, p) {
  hlClear(); hl = L.layerGroup();
  (rays || []).forEach(([cl, co, el, eo, d]) => {
    hl.addLayer(L.polyline([[cl,co],[el,eo]], {color:'#000', weight:3, opacity:.9, dashArray:'6 4'}).bindTooltip(d+' m (estimada)'));
    hl.addLayer(L.circleMarker([cl,co], {radius:5, color:'#000', weight:2, fillColor:'#ffeb3b', fillOpacity:1}).bindTooltip('câmara'));
    hl.addLayer(L.circleMarker([el,eo], {radius:3, color:'#000', weight:1, fillColor:'#fff', fillOpacity:1}));
  });
  hl.addTo(map);
}
const bindDet = (m, p, obs, rays) => {
  m.on('popupopen', () => hlShow(rays, p)); m.on('popupclose', hlClear);
  return m.bindPopup(() => popupDet(p, obs), {maxWidth:440, minWidth:320});
};
const SIGN = {regulatory:'#d62728', warning:'#ff7f0e', information:'#1f77b4', orientacao:'#9467bd', desconhecido:'#8c8c8c'};
const signColor = s => SIGN[(s||'desconhecido').split('_')[0]] || '#8c8c8c';
let onlyConfirmed = false;
const layers = {};

function mk(list, style, key, extra) {
  const g = L.layerGroup();
  list.forEach(([lat, lon, p, obs, rays]) => {
    const st = typeof style === 'function' ? style(p) : style;
    const m = bindDet(L.circleMarker([lat, lon], st), p, obs, rays);
    m._conf = !!p.confirmado; m._g = g; g.addLayer(m);
  });
  layers[key] = g; return g;
}
// cada deteção = miniatura do recorte ANONIMIZADO (thumbs/<id>.jpg), borda da cor da classe; anel preto = confirmado (>=2 câmaras)
const KCOL = {contentor:'#2ca02c', subterraneo:'#e377c2', poste_luz:'#f9a825', candeeiro:'#ffb300', banco:'#795548'};
const KS = ['contentor','subterraneo','sinal','poste_luz','candeeiro','banco'];
const colorOf = (k, p) => k === 'sinal' ? signColor(p.subclass) : KCOL[k];
function detMarker(k, [lat, lon, p, obs, rays, th]) {
  const c = colorOf(k, p);
  const html = '<div class="thb'+(p.confirmado ? ' cf' : '')+'" style="border-color:'+c+'">'+(th ? '<img src="thumbs/'+esc(p.id)+'.jpg" alt="">' : '')+'</div>';
  const m = L.marker([lat, lon], {icon: L.divIcon({className:'thd', html, iconSize:[48,48]})});
  m._conf = !!p.confirmado;
  return bindDet(m, p, obs, rays);
}
const clusterOpts = {maxClusterRadius:38, disableClusteringAtZoom:18, showCoverageOnHover:false, spiderfyOnMaxZoom:true};
const grp = {};
KS.forEach(k => { grp[k] = L.markerClusterGroup(clusterOpts); });
function fillDet(only) {
  KS.forEach(k => {
    grp[k].clearLayers();
    grp[k].addLayers(D.det[k].filter(r => !only || r[2].confirmado).map(r => detMarker(k, r)));
  });
}
fillDet(false);
const gCont = grp.contentor, gSub = grp.subterraneo, gSin = grp.sinal, gPoste = grp.poste_luz, gCand = grp.candeeiro, gBanco = grp.banco;

function mk(list, style, key) {                            // camadas simples de pontos (referência e câmaras)
  const g = L.layerGroup();
  list.forEach(([lat, lon, p]) => g.addLayer(L.circleMarker([lat, lon], style).bindPopup(popup(p))));
  layers[key] = g; return g;
}

const sqIcon = (c, s) => L.divIcon({className:'', html:'<div style="width:'+s+'px;height:'+s+'px;background:'+c+';border:1px solid #000;opacity:.9"></div>', iconSize:[s,s]});
const refG = (list, icon) => { const g = L.layerGroup(); list.forEach(([la,lo,p]) => g.addLayer(L.marker([la,lo], {icon}).bindPopup(popup(p)))); return g; };
const gRec = L.layerGroup();
D.ref.reciclagem.forEach(([la,lo,p]) => {
  const u = (p.location||'').includes('underground');
  gRec.addLayer(L.marker([la,lo], {icon: sqIcon(u ? '#c2185b' : '#9ccc65', u ? 13 : 10)}).bindPopup(popup(p)));
});
const gPap = refG(D.ref.papeleiras, sqIcon('#ffb300', 8));
const gSinOsm = refG(D.ref.sinais, sqIcon('#bdbdbd', 8));
const gLuzOsm = refG(D.ref.luz_osm, sqIcon('#fff176', 7));
const gLuzMly = mk(D.ref.luz_mly, {radius:2.5, fillColor:'#ffd54f', fillOpacity:.7, weight:0}, 'luz_mly');
const gCam = mk(D.cameras, {radius:2.5, fillColor:'#000', fillOpacity:.5, weight:0}, 'cam');
const gPil = L.layerGroup();
D.ref.subterraneos_piloto.forEach(([la,lo,p]) => gPil.addLayer(L.circle([la,lo], {radius:12, color:'#c2185b', weight:2, fillOpacity:.15}).bindPopup('Subterrâneo do piloto<br>'+esc(p.nota||''))));

// todos os raios (desligado por omissão) e linhas de erro elemento -> ecoponto OSM emparelhado
const gRay = L.layerGroup();
KS.forEach(k => (D.det[k]||[]).forEach(([la,lo,p,obs,rays,th]) => (rays||[]).forEach(([cl,co,el,eo]) =>
  gRay.addLayer(L.polyline([[cl,co],[el,eo]], {color: k==='sinal' ? '#7f7f7f' : (KCOL[k]||'#7f7f7f'), weight:1, opacity:.45, interactive:false})))));
const errCol = e => e <= 5 ? '#2e7d32' : e <= 10 ? '#fbc02d' : e <= 20 ? '#ef6c00' : '#c62828';
const gErr = L.layerGroup();
D.err.forEach(([la,lo,rla,rlo,e,id]) => gErr.addLayer(L.polyline([[la,lo],[rla,rlo]], {color:errCol(e), weight:3, opacity:.9})
  .bindTooltip(id+': '+e+' m do ecoponto OSM')));
gCont.addTo(map); gSub.addTo(map); gSin.addTo(map); gPoste.addTo(map); gCand.addTo(map); gBanco.addTo(map); gRec.addTo(map); gPil.addTo(map); gErr.addTo(map);
const n = k => (D.det[k]||[]).length;
L.control.layers(null, {
  ['Contentor (detetado) ['+n('contentor')+']']: gCont,
  ['Subterrâneo (detetado) ['+n('subterraneo')+']']: gSub,
  ['Sinais (detetados) ['+n('sinal')+']']: gSin,
  ['Poste de luz (detetado) ['+n('poste_luz')+']']: gPoste,
  ['Candeeiro (detetado) ['+n('candeeiro')+']']: gCand,
  ['Banco (detetado) ['+n('banco')+']']: gBanco,
  ['OSM: ecopontos ['+D.ref.reciclagem.length+']']: gRec,
  ['OSM: papeleiras ['+D.ref.papeleiras.length+']']: gPap,
  ['OSM: sinais/stop/cedência ['+D.ref.sinais.length+']']: gSinOsm,
  ['OSM: candeeiros ['+D.ref.luz_osm.length+']']: gLuzOsm,
  ['Mapillary: candeeiros ['+D.ref.luz_mly.length+']']: gLuzMly,
  ['Posições das câmaras ['+D.cameras.length+']']: gCam,
  ['4 subterrâneos do piloto']: gPil,
  ['Erro: elemento → ecoponto OSM (m) ['+D.err.length+']']: gErr,
  ['Raios de todas as observações']: gRay,
}, {collapsed:false}).addTo(map);

const Legend = L.control({position:'bottomleft'});
Legend.onAdd = () => {
  const d = L.DomUtil.create('div', 'box');
  d.innerHTML = '<h4>__CITY__</h4>' +
   '<div><span class="sw" style="background:#2ca02c"></span>contentor &nbsp;<span class="sw" style="background:#e377c2"></span>subterrâneo</div>' +
   '<div><span class="sw" style="background:#d62728"></span>regulamentação <span class="sw" style="background:#ff7f0e"></span>perigo</div>' +
   '<div><span class="sw" style="background:#f9a825"></span>poste de luz &nbsp;<span class="sw" style="background:#ffb300"></span>candeeiro &nbsp;<span class="sw" style="background:#795548"></span>banco</div>' +
   '<div><span class="sw" style="background:#1f77b4"></span>informação <span class="sw" style="background:#9467bd"></span>orientação <span class="sw" style="background:#8c8c8c"></span>?</div>' +
   '<div style="margin-top:4px">Cada ponto é a <b>miniatura</b> da deteção (imagem anonimizada); a borda tem a cor da classe e o <b>anel preto</b> marca os confirmados por ≥2 câmaras. Aproxima para os ver separados.</div>' +
   '<div style="margin-top:4px"><span class="sw sq" style="background:#9ccc65"></span>ecoponto OSM &nbsp;<span class="sw sq" style="background:#c2185b"></span>subterrâneo/semi (OSM)</div>' +
   '<div style="margin-top:4px">Linhas de erro (→ ecoponto OSM): <span style="color:#2e7d32">■</span>≤5 m <span style="color:#fbc02d">■</span>≤10 <span style="color:#ef6c00">■</span>≤20 <span style="color:#c62828">■</span>&gt;20</div>' +
   '<div style="margin-top:4px">Ao clicar num ponto: <b>raio tracejado</b> câmara→posição estimada.</div>' +
   '<label style="display:block;margin-top:6px"><input type="checkbox" id="cf"> só confirmados</label>';
  L.DomEvent.disableClickPropagation(d); return d;
};
Legend.addTo(map);
if (D.stats && D.stats.n_pares) {
  const S = L.control({position:'bottomright'});
  S.onAdd = () => { const d = L.DomUtil.create('div','box'); const s = D.stats;
    d.innerHTML = '<h4>Erro de posição (resíduos vs OSM)</h4>' +
      (D.ajuste ? '<i>posição ajustada à estrada OSM (corredor '+D.ajuste.w_m+' m)</i><br>' : '') +
      s.n_pares+' pares 1-1 (de '+s.n_elem+' elementos e '+s.n_ref+' ecopontos OSM)<br>' +
      'erro mediano: <b>'+s.erro_mediano_m+' m</b><br>' +
      'distância estimada/real: <b>×'+s.razao_dist+'</b><br>' +
      'erro de rumo |mediano|: <b>'+s.rumo_abs_graus+'°</b><br>' +
      'elementos a ≤10 m de um ecoponto OSM: <b>'+Math.round(100*s.prec10)+'%</b><br>' +
      '<span style="color:#666">OSM = verdade aproximada. Detalhe: reports/posicao/'+D.cidade+'.md</span>';
    return d; };
  S.addTo(map);
}
document.getElementById('cf').addEventListener('change', e => fillDet(e.target.checked));
</script></body></html>
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", default="aveiro")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--catalog", help="ficheiro em data/catalog/<cidade>/ (omissão: catalog_ajustado.geojson se existir)")
    ap.add_argument("--serve", action="store_true", help="servir a pasta do mapa em localhost e abrir o browser")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    out = a.out or ROOT / "data" / "catalog" / a.city / "mapa.html"
    catalog = a.catalog or ("catalog_ajustado.geojson" if (ROOT / "data" / "catalog" / a.city / "catalog_ajustado.geojson").exists() else "catalog.geojson")
    data = build(a.city, catalog, out.parent / "thumbs")
    page = TEMPLATE.replace("__CITY__", html.escape(a.city.capitalize())).replace(
        "__DATA__", json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"))
    out.write_text(page, encoding="utf-8")
    d = data["det"]
    d_ = list(d)
    print(f"catálogo: {catalog} | miniaturas: {sum(p[5] for k in d_ for p in data['det'][k])}")
    print(f"{out}  ({out.stat().st_size / 1e3:.0f} kB) | deteções: " + ", ".join(f"{k} {len(v)}" for k, v in d.items())
          + f" | ref: " + ", ".join(f"{k} {len(v)}" for k, v in data["ref"].items()) + f" | câmaras {len(data['cameras'])}")

    if a.serve:
        import functools, http.server, urllib.parse, webbrowser
        anon, ok = ROOT / "data" / "images_anon", anon_files()

        class Handler(http.server.SimpleHTTPRequestHandler):
            def translate_path(self, path):
                clean = urllib.parse.unquote(path.split("?", 1)[0].split("#", 1)[0])
                if clean.startswith("/images/"):                  # só imagens anonimizadas verificadas (manifest.jsonl)
                    name = Path(clean).name
                    return str(anon / name) if name in ok else str(ROOT / "__nao_existe__")
                return super().translate_path(path)

            def log_message(self, *args):
                pass

        handler = functools.partial(Handler, directory=str(out.parent))
        srv = None
        for port in range(a.port, a.port + 20):                   # porta ocupada (ex.: um --serve parado com Ctrl+Z): tenta a seguinte
            try:
                srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
                break
            except OSError:
                print(f"porta {port} ocupada, a tentar a seguinte...")
        if srv is None:
            sys.exit(f"Sem portas livres entre {a.port} e {a.port + 19}.")
        url = f"http://localhost:{srv.server_address[1]}/{out.name}"
        print(f"a servir {out.parent} em {url}  (Ctrl+C para parar)")
        webbrowser.open(url)
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
