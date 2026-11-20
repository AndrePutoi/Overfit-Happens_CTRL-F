"""Runner de zona: corre as etapas de `etapas.py` por ordem, guarda o estado e retoma de onde parou.

Regras:
  * `data/zonas/<zona>/estado.json` regista, por etapa: estado (pendente|feita|falhou), início/fim, segundos, comando, contagens da verificação, erro e log.
  * RETOMA: uma etapa `feita` com as saídas ainda no disco é saltada. Correr (ou refazer) uma etapa põe as seguintes em `pendente`, porque dependem dela.
  * PORTÃO: se a privacidade falhar (ou a sua verificação reprovar) a corrida pára; nada a jusante corre. Etapas `opcional` só avisam.
  * TENTATIVAS: só se repetem as falhas INTERMITENTES conhecidas do PyTorch/CUDA (padrões em FLAKY); qualquer outro erro falha à primeira, para não esconder defeitos.
  * GPU (6 GB): as etapas `gpu` correm uma de cada vez e com um lock em `data/zonas/.gpu.lock` (duas zonas em paralelo não partilham a placa). `--cpu` desliga a GPU (teste lento).
  * REDE: só as etapas `externa` (Mapillary, Overpass) usam a rede e só enviam a caixa da zona e um nome de cliente genérico; nenhuma envia imagens.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import subprocess
import time
from pathlib import Path

from .etapas import ETAPAS, ROOT, Etapa, Falha, Zona, nomes_etapas

FLAKY = re.compile(r"getCount|non-monotonic|CUDA error: (initialization|unspecified|an illegal)|CUDA driver initialization failed|cudaErrorInitializationError|Illegal instruction")
TENTATIVAS_FLAKY = 3


def _agora() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _estado_path(nome: str) -> Path:
    return ROOT / "data" / "zonas" / nome / "estado.json"


def estado_de(nome: str) -> dict:
    f = _estado_path(nome)
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    return {"zona": nome, "criado_em": _agora(), "etapas": {e.nome: {"estado": "pendente"} for e in ETAPAS}}


def _guardar(est: dict) -> None:
    f = _estado_path(est["zona"])
    f.parent.mkdir(parents=True, exist_ok=True)
    est["atualizado_em"] = _agora()
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(est, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(f)


def _ambiente() -> dict:
    git = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip() or "?"
    return {"commit": git, "python": os.sys.version.split()[0], "UMS_MODELS_DIR": os.environ.get("UMS_MODELS_DIR", str(ROOT / "models")),
            "UMS_PRIVACY_BACKEND": os.environ.get("UMS_PRIVACY_BACKEND", "yolo")}


def _cmd_str(c: list[str]) -> str:
    return " ".join(Path(x).name if x == os.sys.executable else x for x in c)


class _GpuLock:
    def __init__(self, ativo: bool):
        self.ativo, self.f = ativo, None

    def __enter__(self):
        if self.ativo:
            p = ROOT / "data" / "zonas" / ".gpu.lock"
            p.parent.mkdir(parents=True, exist_ok=True)
            self.f = open(p, "w")
            fcntl.flock(self.f, fcntl.LOCK_EX)                 # espera a vez
        return self

    def __exit__(self, *a):
        if self.f:
            fcntl.flock(self.f, fcntl.LOCK_UN)
            self.f.close()


def _correr_comando(cmd: list[str], log: Path, env: dict) -> tuple[int, str]:
    """Corre um comando a escrever no log; repete SÓ as falhas intermitentes conhecidas. -> (código, cauda do log).
    Intermitente = aborto do processo (código -6/SIGABRT, típico do `getCount is non-monotonic` do PyTorch) OU a mensagem conhecida em QUALQUER ponto da saída DESTA tentativa
    (o backtrace é enorme: a mensagem fica no início, fora de uma cauda curta)."""
    for t in range(1, TENTATIVAS_FLAKY + 1):
        inicio = log.stat().st_size if log.exists() else 0
        with open(log, "a", encoding="utf-8") as lf:
            lf.write(f"\n$ {_cmd_str(cmd)}   [tentativa {t}] {_agora()}\n")
            lf.flush()
            r = subprocess.run(cmd, cwd=ROOT, env=env, stdout=lf, stderr=subprocess.STDOUT)
        with open(log, "rb") as lf:
            lf.seek(inicio)
            desta_tentativa = lf.read().decode("utf-8", errors="replace")
        cauda = desta_tentativa[-4000:]
        intermitente = r.returncode in (-6, 134) or bool(FLAKY.search(desta_tentativa))
        if r.returncode == 0 or not intermitente or t == TENTATIVAS_FLAKY:
            return r.returncode, cauda
        time.sleep(3)
    return 1, ""


def _executar(e: Etapa, z: Zona, cpu: bool, out, estado_anterior: dict | None = None) -> dict:
    t0 = time.time()
    ant = estado_anterior or {}
    obsoleta = ant.get("estado") == "feita" or bool(ant.get("invalidada_por"))              # refeita ou invalidada: as caches de retoma já não servem
    if obsoleta and e.limpar:
        e.limpar(z)
    log = z.pasta / "logs" / f"{e.nome}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("", encoding="utf-8")
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    if cpu and e.gpu:
        env["CUDA_VISIBLE_DEVICES"] = ""
    if e.antes:
        e.antes(z)
    cmds = e.cmd(z)
    with _GpuLock(e.gpu and not cpu):
        for c in cmds:
            rc, cauda = _correr_comando(c, log, env)
            if rc != 0:
                ult = [l for l in cauda.strip().splitlines() if l.strip()][-3:]
                raise Falha(f"comando falhou (código {rc}): {_cmd_str(c)} | {' / '.join(ult)[:400]}")
    faltam = [str(p.relative_to(ROOT)) for p in e.saidas(z) if not p.exists()]
    if faltam:
        raise Falha(f"saídas em falta: {faltam}")
    contagens = e.verificar(z) if e.verificar else {}
    return {"segundos": round(time.time() - t0, 1), "contagens": contagens, "log": str(log.relative_to(ROOT)), "comandos": [_cmd_str(c) for c in cmds]}


def correr(z: Zona, so: list[str] | None = None, ate: str | None = None, refazer: list[str] | None = None, cpu: bool = False, plano: bool = False, out=print) -> dict:
    """Corre a cadeia. `so` = só estas etapas; `ate` = até esta (inclusive); `refazer` = ignora o estado 'feita' destas (e invalida as seguintes)."""
    nomes = nomes_etapas()
    for n in (so or []) + ([ate] if ate else []) + (refazer or []):
        if n not in nomes:
            raise ValueError(f"etapa desconhecida {n!r}; etapas: {nomes}")
    est = estado_de(z.nome)
    est["config"], est["ambiente"] = z.cfg, _ambiente()
    est["etapas"] = {e.nome: est["etapas"].get(e.nome, {"estado": "pendente"}) for e in ETAPAS}
    limite = nomes.index(ate) if ate else len(ETAPAS) - 1
    invalidar_desde = None
    erro_fatal = None
    for i, e in enumerate(ETAPAS):
        if i > limite or (so and e.nome not in so):
            continue
        s = est["etapas"][e.nome]
        feita = s.get("estado") == "feita" and all(p.exists() for p in e.saidas(z)) and not (refazer and e.nome in refazer)
        if plano:
            out(f"[{i + 1:2d}] {e.nome:12s} {s.get('estado', 'pendente'):9s} {e.titulo}" + ("  [GPU]" if e.gpu else "") + ("  [rede]" if e.externa else "") + ("  [PORTÃO]" if e.portao else ""))
            for c in e.cmd(z):
                out(f"       $ {_cmd_str(c)}")
            continue
        if invalidar_desde is not None and not feita:
            pass
        if feita and invalidar_desde is None:
            out(f"[{i + 1:2d}] {e.nome:12s} feita (saltada) {s.get('contagens', '')}")
            continue
        if invalidar_desde is None:
            invalidar_desde = i
            for e2 in ETAPAS[i + 1:]:                                    # esta etapa vai correr: as seguintes dependem dela
                if est["etapas"][e2.nome].get("estado") == "feita":
                    est["etapas"][e2.nome] = {"estado": "pendente", "invalidada_por": e.nome}
        out(f"[{i + 1:2d}] {e.nome:12s} a correr: {e.titulo}")
        anterior = dict(s)
        est["etapas"][e.nome] = {"estado": "a_correr", "inicio": _agora()}
        _guardar(est)
        try:
            r = _executar(e, z, cpu, out, anterior)
            est["etapas"][e.nome] = {"estado": "feita", "inicio": est["etapas"][e.nome]["inicio"], "fim": _agora(), **r}
            out(f"     ok em {r['segundos']}s {r['contagens']}")
        except Falha as ex:
            est["etapas"][e.nome] = {"estado": "falhou", "inicio": est["etapas"][e.nome]["inicio"], "fim": _agora(), "erro": str(ex), "log": str((z.pasta / 'logs' / f'{e.nome}.log').relative_to(ROOT))}
            out(f"     FALHOU: {ex}")
            if e.opcional:
                out("     (etapa opcional: a cadeia continua)")
            else:
                erro_fatal = (e.nome, str(ex), e.portao)
        _guardar(est)
        if erro_fatal:
            out(f"PARADO em '{erro_fatal[0]}'" + (" (portão de privacidade fechado: nada a jusante foi processado)" if erro_fatal[2] else ""))
            break
    if not plano:
        est["terminada"] = all(est["etapas"][e.nome].get("estado") == "feita" for e in ETAPAS)
        est["falha"] = {"etapa": erro_fatal[0], "erro": erro_fatal[1]} if erro_fatal else None
        _guardar(est)
    return est


def resumo(nome: str) -> str:
    est = estado_de(nome)
    linhas = [f"zona {nome}  (atualizado {est.get('atualizado_em', '-')})  commit {est.get('ambiente', {}).get('commit', '?')}"]
    tot = 0.0
    for e in ETAPAS:
        s = est["etapas"].get(e.nome, {"estado": "pendente"})
        tot += s.get("segundos", 0)
        extra = s.get("contagens") or s.get("erro") or ""
        linhas.append(f"  {e.nome:12s} {s.get('estado', 'pendente'):9s} {s.get('segundos', ''):>8} s  {extra}")
    linhas.append(f"  tempo total das etapas feitas: {tot / 60:.1f} min  |  terminada: {est.get('terminada', False)}")
    return "\n".join(linhas)
