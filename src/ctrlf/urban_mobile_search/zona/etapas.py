"""A cadeia de etapas de uma zona. Cada etapa = comando(s) dos scripts existentes + saídas obrigatórias + uma verificação própria.

Ordem (a mesma de Aveiro, agora sem passos manuais):
  descarregar -> vistas -> admissao -> privacidade -> deteccao -> referencias -> catalogo -> estrada -> tipos -> dedup -> entrega (-> mapa, opcional)
O resultado final de uma zona é data/zonas/<zona>/resultado/elementos_unicos.geojson.

Uma etapa é só DADOS (nome, comando, saídas, verificação): para mudar um parâmetro ou trocar um script edita-se aqui, sem tocar no runner.
A privacidade é um PORTÃO: `verificar_privacidade` confirma, vista a vista, que a imagem anonimizada existe no manifesto com o sha256 certo; se falhar, nada a jusante corre.
"""
from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ctrlf.paths import ROOT
PY = sys.executable
PREANNOT = {"sinal": "sinais", "residuos": "ecopontos", "iluminacao": "luz", "mobiliario": "bancos"}
ENTREGA_FICHEIROS = ("elementos.geojson", "elementos_unicos.geojson", "ilhas.json", "deteccoes.json", "imagens.json", "duplicados.json", "LEIA-ME.md", "manifest.json")


class Falha(RuntimeError):
    """Etapa falhou (comando com erro, saída em falta ou verificação reprovada)."""


@dataclass
class Zona:
    nome: str
    cfg: dict = field(default_factory=dict)

    @property
    def raw(self) -> Path: return ROOT / "data" / "raw" / self.nome
    @property
    def vistas(self) -> Path: return ROOT / "data" / "raw" / f"{self.nome}_vistas"
    @property
    def pasta(self) -> Path: return ROOT / "data" / "zonas" / self.nome
    @property
    def catalogo(self) -> Path: return ROOT / "data" / "catalog" / self.nome
    @property
    def anon(self) -> Path: return ROOT / "data" / "images_anon"
    @property
    def entrega_dir(self) -> Path: return ROOT / "Entrega_C"
    @property
    def resultado(self) -> Path: return self.pasta / "resultado" / "elementos_unicos.geojson"      # O RESULTADO FINAL da zona

    def coco(self, fam: str) -> Path:
        return ROOT / "data" / "preannot" / PREANNOT[fam] / self.nome / "annotations" / "instances_default.json"

    def meta_vistas(self) -> list[dict]:
        f = self.vistas / "meta.jsonl"
        return [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()] if f.exists() else []

    def entrega_zip(self) -> Path | None:
        zs = sorted(self.entrega_dir.glob(f"entrega_{self.nome}_*.zip"))
        return zs[-1] if zs else None


@dataclass
class Etapa:
    nome: str
    titulo: str
    cmd: Callable[[Zona], list[list[str]]]
    saidas: Callable[[Zona], list[Path]]
    verificar: Callable[[Zona], dict] | None = None
    antes: Callable[[Zona], None] | None = None          # limpeza de saídas que os scripts ACRESCENTAM (para uma repetição não duplicar linhas)
    limpar: Callable[[Zona], None] | None = None         # apaga as CACHES de retoma da etapa; corre quando a etapa é REFEITA ou INVALIDADA por uma anterior (as caches estão obsoletas), nunca quando só foi interrompida
    gpu: bool = False                                    # serializa com outras corridas (lock) e recebe CUDA_VISIBLE_DEVICES="" em --cpu
    opcional: bool = False                               # falhar não pára a cadeia (só avisa)
    portao: bool = False                                 # falhar fecha tudo o que vem a seguir (privacidade)
    externa: bool = False                                # usa a rede (Mapillary, Overpass): só envia a caixa da zona


# ---------------------------------------------------------------------------- verificações
def _linhas(f: Path) -> int:
    return sum(1 for l in f.read_text(encoding="utf-8").splitlines() if l.strip()) if f.exists() else 0


def v_descarregar(z: Zona) -> dict:
    n = _linhas(z.raw / "meta.jsonl")
    if n == 0:
        raise Falha(f"nenhuma imagem descarregada em {z.raw} (caixa sem cobertura Mapillary, ou token em falta)")
    faltam = [m["path"] for m in map(json.loads, (z.raw / "meta.jsonl").read_text(encoding="utf-8").splitlines()) if not (ROOT / m["path"]).exists()]
    if faltam:
        raise Falha(f"{len(faltam)} imagens do meta.jsonl não existem no disco, p. ex. {faltam[0]}")
    return {"imagens": n}


def v_vistas(z: Zona) -> dict:
    n = _linhas(z.vistas / "meta.jsonl")
    if n == 0:
        raise Falha("a conversão para vistas planas não produziu nenhuma vista")
    return {"vistas": n}


def v_admissao(z: Zona) -> dict:
    n = _linhas(z.vistas / "meta.jsonl")
    if n == 0:
        raise Falha("a admissão rejeitou todas as vistas")
    rej = z.vistas / "_rejeitadas"
    return {"admitidas": n, "rejeitadas": len(list(rej.glob("*.jpg"))) if rej.exists() else 0}


def v_privacidade(z: Zona) -> dict:
    """PORTÃO: cada vista admitida tem de estar no manifesto de anonimização com o sha256 do ficheiro anonimizado. Falha fechada."""
    man = {}
    f = z.anon / "manifest.jsonl"
    if not f.exists():
        raise Falha("não existe data/images_anon/manifest.jsonl")
    for l in f.read_text(encoding="utf-8").splitlines():
        if l.strip():
            d = json.loads(l)
            man[d["file"]] = d["sha256"]
    mal = []
    for m in z.meta_vistas():
        n = Path(m["path"]).name
        p = z.anon / n
        if n not in man or not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest() != man[n]:
            mal.append(n)
    if mal:
        raise Falha(f"PORTÃO DE PRIVACIDADE: {len(mal)} vistas sem anonimização verificada (p. ex. {mal[0]}); nada a jusante corre")
    return {"vistas_anonimizadas_verificadas": len(z.meta_vistas())}


def v_deteccao(z: Zona) -> dict:
    mf = z.pasta / "deteccoes" / "modelos.json"
    if not mf.exists():
        raise Falha("falta data/zonas/<zona>/deteccoes/modelos.json")
    return json.loads(mf.read_text(encoding="utf-8")).get("contagens", {})


def v_catalogo(z: Zona) -> dict:
    mf = z.catalogo / "manifest.json"
    d = json.loads(mf.read_text(encoding="utf-8"))
    return {k: d[k] for k in ("elementos", "observacoes", "papeleiras_descartadas") if k in d} or {"manifest": True}


def v_estrada(z: Zona) -> dict:
    d = json.loads((z.catalogo / "catalog_ajustado.geojson").read_text(encoding="utf-8"))
    return {"elementos_ajustados": len(d["features"])}


def v_dedup(z: Zona) -> dict:
    d = json.loads((z.catalogo / "dedup_v2" / "resumo.json").read_text(encoding="utf-8"))
    return {k: d[k] for k in ("elementos", "pares_pontuados", "k_posicao", "k_posicao_origem") if k in d}


def v_entrega(z: Zona) -> dict:
    zp = z.entrega_zip()
    if zp is None:
        raise Falha("não foi gerado Entrega_C/entrega_<zona>_*.zip")
    with zipfile.ZipFile(zp) as zf:
        nomes = {n.split("/", 1)[-1] for n in zf.namelist()}
        falta = [f for f in ENTREGA_FICHEIROS if f not in nomes]
        if falta:
            raise Falha(f"o pacote {zp.name} não tem {falta}")
        man = json.loads(zf.read(next(n for n in zf.namelist() if n.endswith("/manifest.json") or n == "manifest.json")))
        el = json.loads(zf.read(next(n for n in zf.namelist() if n.endswith("elementos.geojson") and "unicos" not in n)))
    import math
    def estrito(c):
        raise Falha(f"o pacote tem {c} (não é JSON válido para a interface)")
    for f in el["features"]:                                                  # nenhuma posição pode ser NaN/infinita
        if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in f["geometry"]["coordinates"]):
            raise Falha(f"elemento {f['properties']['id']} com coordenadas não finitas {f['geometry']['coordinates']}")
    with zipfile.ZipFile(zp) as zf2:
        for nome in zf2.namelist():
            if nome.endswith((".json", ".geojson")):
                json.loads(zf2.read(nome), parse_constant=estrito)             # NaN/Infinity são recusados
    c = man.get("counts", {})                                              # o manifesto guarda as contagens em `counts`
    return {"pacote": zp.name, "versao_esquema": man.get("schema_version"), "elementos": len(el["features"]), "unicos": c.get("unique_elements"), "ilhas": c.get("islands"),
            "deteccoes": c.get("detections"), "imagens": c.get("images"), "fusoes_automaticas": c.get("auto_merged_groups")}


# ---------------------------------------------------------------------------- preparações
def a_descarregar(z: Zona) -> None:
    (z.raw / "meta.jsonl").unlink(missing_ok=True)           # o downloader ACRESCENTA ao meta.jsonl (as imagens já descarregadas não se repetem): evita linhas duplicadas numa repetição


def l_deteccao(z: Zona) -> None:
    for f in (z.pasta / "deteccoes").glob("bloco_*.jsonl"):      # blocos de deteção de uma corrida anterior: obsoletos se o modelo, as imagens ou a configuração mudaram
        f.unlink()


def a_vistas(z: Zona) -> None:
    (z.vistas / "meta.jsonl").unlink(missing_ok=True)
    rej = z.vistas / "_rejeitadas"
    if rej.exists():
        for f in rej.glob("*.jpg"):                           # voltam ao sítio: a admissão decide de novo
            f.replace(z.vistas / f.name)


# ---------------------------------------------------------------------------- comandos
def c_descarregar(z: Zona) -> list[list[str]]:
    c = z.cfg
    cmd = [PY, "-m", "ctrlf.ingest.mapillary_download", "--bbox", *map(str, c["bbox"]), "--out", str(z.raw.relative_to(ROOT)), "--max", str(c.get("max", 300)), "--stride", str(c.get("stride", 1))]
    if c.get("since"):
        cmd += ["--since", c["since"]]
    if c.get("max_panoramas") is not None:
        cmd += ["--max-panoramas", str(c["max_panoramas"])]
    return [cmd]


def c_deteccao(z: Zona) -> list[list[str]]:
    return [[PY, "-m", "ctrlf.scripts.detetar_zona", z.nome]]


def c_referencias(z: Zona) -> list[list[str]]:
    return [[PY, "-m", "ctrlf.ingest.osm_vias", z.nome], [PY, "-m", "ctrlf.ingest.osm_ref", z.nome]]


def c_catalogo(z: Zona) -> list[list[str]]:
    ref = ROOT / "data" / "reference"
    cmd = [PY, "-m", "ctrlf.pipeline.export_geojson", "--city", z.nome, "--meta", str((z.vistas / "meta.jsonl").relative_to(ROOT)),
           "--luz", str(z.coco("iluminacao").relative_to(ROOT)), "--residuos", str(z.coco("residuos").relative_to(ROOT)),
           "--sinal", str(z.coco("sinal").relative_to(ROOT)), "--banco", str(z.coco("mobiliario").relative_to(ROOT)),
           "--depth", "--anon-dir", "data/images_anon", "--assoc", "rays", "--catchall", "appearance", "--filtro-papeleiras", "--out", str(z.catalogo.relative_to(ROOT))]
    luz_ref = next((p for p in (ref / f"{z.nome}_luz.geojson", ref / f"osm_{z.nome}_luz.geojson") if p.exists()), None)
    rec_ref = next((p for p in (ref / f"osm_{z.nome}_recycling.json", ref / f"osm_{z.nome}_reciclagem.json") if p.exists()), None)
    if luz_ref:
        cmd += ["--reference", str(luz_ref.relative_to(ROOT))]
    if rec_ref:
        cmd += ["--ref-residuos", str(rec_ref.relative_to(ROOT))]
    return [cmd]


def v_mapa(z: Zona) -> dict:
    f = z.catalogo / "mapa.html"
    return {"mapa": str(f.relative_to(ROOT)), "kB": round(f.stat().st_size / 1e3), "miniaturas": len(list((z.catalogo / "thumbs").glob("*.jpg"))) if (z.catalogo / "thumbs").exists() else 0}


ETAPAS: list[Etapa] = [
    Etapa("descarregar", "Descarregar imagens do Mapillary (caixa da zona)", c_descarregar, lambda z: [z.raw / "meta.jsonl"], v_descarregar, antes=a_descarregar, externa=True),
    Etapa("vistas", "Panoramas 360° -> vistas planas (as planas passam inalteradas)",
          lambda z: [[PY, "-m", "ctrlf.ingest.pano_to_perspective", str(z.raw.relative_to(ROOT)), str(z.vistas.relative_to(ROOT)), "--yaws", "0", "90", "180", "270", "--fov", "100"]],
          lambda z: [z.vistas / "meta.jsonl"], v_vistas, antes=a_vistas),
    Etapa("admissao", "Admissão: posição obrigatória + qualidade (rejeita antes de gastar GPU)",
          lambda z: [[PY, "-m", "ctrlf.ingest.admissao", str(z.vistas.relative_to(ROOT)), "--zona", z.nome, "--aplicar"]], lambda z: [z.vistas / "meta.jsonl"], v_admissao),
    Etapa("privacidade", "Privacidade: rostos e matrículas desfocados; integridade confirmada por sha256 (PORTÃO, falha fechada)",
          lambda z: [[PY, "-m", "ctrlf.privacy.anon_cache", str(z.vistas.relative_to(ROOT))]], lambda z: [z.anon / "manifest.jsonl"], v_privacidade, gpu=True, portao=True),
    Etapa("deteccao", "Deteção e classificação por família (sinais, resíduos, luz, bancos), um modelo de cada vez", c_deteccao,
          lambda z: [z.coco(f) for f in PREANNOT], v_deteccao, gpu=True, limpar=l_deteccao),
    Etapa("referencias", "Referências OSM da zona: vias, luz, reciclagem (só a caixa vai à rede)", c_referencias,
          lambda z: [ROOT / "data" / "reference" / f"osm_{z.nome}_vias.json"], None, externa=True),
    Etapa("catalogo", "Posição, associação por raios e elementos (profundidade, filtro de papeleiras)", c_catalogo,
          lambda z: [z.catalogo / "catalog.geojson", z.catalogo / "observacoes.json"], v_catalogo, gpu=True),
    Etapa("estrada", "Ajuste ao corredor da via (corrige a escala da profundidade)", lambda z: [[PY, "-m", "ctrlf.pipeline.ajustar_estrada", z.nome]],
          lambda z: [z.catalogo / "catalog_ajustado.geojson"], v_estrada),
    Etapa("tipos", "Tipo do caixote (indiferenciado/papel/embalagens/vidro) para as ilhas", lambda z: [[PY, "-m", "ctrlf.scripts.tipar_residuos_catalogo", z.nome]],
          lambda z: [z.catalogo / "residuos_tipos.json"], None, gpu=True),
    Etapa("dedup", "Deduplicação v2: p(mesmo objeto), grupos, posições", lambda z: [[PY, "-m", "ctrlf.scripts.deduplicar", "--cidade", z.nome]],
          lambda z: [z.catalogo / "dedup_v2" / "grupos.json"], v_dedup, gpu=True),
    Etapa("entrega", "Pacote de entrega (esquema 1.3) e RESULTADO FINAL: elementos únicos em GeoJSON",
          lambda z: [[PY, "-m", "ctrlf.scripts.exportar_entrega", z.nome], [PY, "-m", "ctrlf.scripts.extrair_resultado", z.nome]],
          lambda z: [z.entrega_dir, z.resultado], v_entrega),
    Etapa("mapa", "Mapa HTML da zona com as deteções (miniaturas das imagens ANONIMIZADAS); para a equipa, não faz parte da entrega", lambda z: [[PY, "-m", "ctrlf.scripts.build_map", "--city", z.nome]],
          lambda z: [z.catalogo / "mapa.html"], v_mapa, opcional=True),
]


def nomes_etapas() -> list[str]:
    return [e.nome for e in ETAPAS]
