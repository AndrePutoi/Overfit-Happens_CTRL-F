"""CTRL+F: liga os pedidos da página "Importar imagens" ao pipeline de deteção.

Corre no computador onde está o pipeline (com o ambiente Python do pipeline ativo), ao lado do Docker:

    python ctrlf_worker.py --pipeline <pasta do repositório da pipeline> --dados <pasta interface>\\dados

Em ciclo:
  1. lê na API os pedidos "na fila" (GET /jobs?status=na_fila), o mais antigo primeiro;
  2. cria uma zona no pipeline para o pedido (pela rua escrita pelo técnico, ou pela caixa do pedido)
     e corre as etapas (`python -m ctrlf zona run pedido_<id>`);
  3. vai mostrando na interface a etapa em curso e o progresso (PATCH /jobs/<id>);
  4. no fim, descompacta a entrega em dados/entregas/pedido_<id> e pede à API para a juntar ao
     catálogo (POST /jobs/<id>/importar). O mapa ganha os elementos novos; o resto fica igual.

Só usa a biblioteca padrão do Python. O pipeline precisa dos pesos (UMS_MODELS_DIR) e do token do
Mapillary (.env na pasta do pipeline: MAPILLARY_TOKEN=MLY|...).
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ETAPAS_PT = {
    "descarregar": "a descarregar imagens do Mapillary",
    "vistas": "a preparar as vistas",
    "admissao": "a verificar a qualidade das imagens",
    "privacidade": "a desfocar rostos e matrículas",
    "deteccao": "a detetar mobiliário urbano",
    "referencias": "a ler as ruas do OpenStreetMap",
    "catalogo": "a calcular posições",
    "estrada": "a ajustar à estrada",
    "tipos": "a classificar os contentores",
    "dedup": "a juntar duplicados",
    "entrega": "a preparar a entrega",
    "mapa": "a desenhar o mapa interno",
}


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


class Api:
    def __init__(self, base, token):
        self.base, self.token = base.rstrip("/"), token

    def call(self, method, path, body=None, timeout=60):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"X-Tecnico-Token": self.token, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode() or "null")
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"{method} {path}: {e.code} {e.read().decode(errors='replace')[:300]}") from None

    def update(self, job_id, **fields):
        try:
            self.call("PATCH", f"/jobs/{job_id}", fields)
        except Exception as e:   # noqa: BLE001  a interface só deixa de mostrar o progresso; o trabalho continua
            log(f"  (não consegui atualizar o pedido {job_id}: {e})")


def area_bbox(config):
    coords = (config.get("municipality") or {}).get("area", {}).get("coordinates", [[]])[0]
    if not coords:
        return None
    xs, ys = [c[0] for c in coords], [c[1] for c in coords]
    return [min(xs), min(ys), max(xs), max(ys)]


def read_state(pipeline, zona):
    p = pipeline / "data" / "zonas" / zona / "estado.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def progress_of(state):
    etapas = state.get("etapas") or {}
    if not etapas:
        return 2, "a preparar a zona"
    names = list(etapas)
    done = sum(1 for s in etapas.values() if s.get("estado") == "feita")
    running = next((n for n, s in etapas.items() if s.get("estado") == "a_correr"), None)
    pct = 2 + int(92 * done / len(names))
    label = ETAPAS_PT.get(running, running) if running else "a continuar"
    return pct, f"{label} ({done + (1 if running else 0)}/{len(names)})"


def pipeline_cmd(args, *extra):
    return [args.python, "-m", "ctrlf", "zona", *extra]


def pipeline_env(args):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    src = str(Path(args.pipeline).resolve() / "src")                      # o pacote `ctrlf` vive em <pipeline>/src
    env["PYTHONPATH"] = src + os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else src
    if args.pesos:
        env["UMS_MODELS_DIR"] = str(Path(args.pesos).resolve())
        env.setdefault("HF_HOME", str(Path(args.pesos).resolve() / "hf_cache"))
    env.setdefault("UMS_PRIVACY_BACKEND", "rfdetr")
    return env


def safe_extract(zp, dest):
    dest.mkdir(parents=True, exist_ok=True)
    root = dest.resolve()
    with zipfile.ZipFile(zp) as z:
        for m in z.infolist():
            target = (dest / m.filename).resolve()
            if root not in target.parents and target != root:
                raise RuntimeError(f"caminho inválido no zip: {m.filename}")
        z.extractall(dest)


def process(api, args, job, config):
    jid, zona = job["id"], f"pedido_{job['id']}"
    pipeline = Path(args.pipeline).resolve()
    log(f"Pedido {jid}: \"{job['name']}\" ({job.get('source_key')}) -> zona {zona}")

    if job.get("source_key") != "mapillary":
        api.update(jid, status="erro", error="O pipeline ainda não processa vídeos nem outras fontes; só o Mapillary.",
                   etapa="não suportado")
        log("  fonte não suportada: marcado como erro")
        return

    api.update(jid, status="a_processar", progress=1, etapa="a preparar a zona")
    env = pipeline_env(args)
    logdir = pipeline / "data" / "zonas" / zona
    bbox = (job.get("params") or {}).get("bbox")
    run_extra = ["--max", str(args.max)]

    if not (pipeline / "data" / "zonas" / zona / "zona.json").exists():
        made = False
        if not bbox and args.raio > 0:
            municipio = (config.get("municipality") or {}).get("name") or ""
            place = f"{job['name']}, {municipio}".strip(", ")
            r = subprocess.run(pipeline_cmd(args, "init", zona, "--place", place, "--raio", str(args.raio), "--max", str(args.max)),
                               cwd=pipeline, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
            made = r.returncode == 0
            log(f"  zona pela rua \"{place}\": " + ("criada" if made else f"não encontrada ({(r.stdout + r.stderr).strip()[-200:]})"))
            if made:
                run_extra = []   # a zona já guardou o limite de imagens
        if not made:
            bbox = bbox or area_bbox(config)
            if not bbox:
                api.update(jid, status="erro", error="Sem área: escreva o nome de uma rua ou configure a zona piloto.")
                return
            run_extra = ["--bbox", *map(str, bbox), "--max", str(args.max)]
    else:
        run_extra = []   # retoma de uma corrida anterior

    if args.cpu:
        run_extra.append("--cpu")
    logdir.mkdir(parents=True, exist_ok=True)
    with open(logdir / "worker.log", "a", encoding="utf-8") as out:
        proc = subprocess.Popen(pipeline_cmd(args, "run", zona, *run_extra), cwd=pipeline, env=env,
                                stdout=out, stderr=subprocess.STDOUT)
        last = None
        while proc.poll() is None:
            pct, label = progress_of(read_state(pipeline, zona))
            if (pct, label) != last:
                api.update(jid, progress=pct, etapa=label)
                log(f"  {pct:3d}% {label}")
                last = (pct, label)
            time.sleep(5)

    state = read_state(pipeline, zona)
    entrega_ok = (state.get("etapas") or {}).get("entrega", {}).get("estado") == "feita"
    if not entrega_ok:
        falha = state.get("falha") or {}
        msg = f"Etapa {falha.get('etapa', '?')}: {str(falha.get('erro', 'falhou'))[:500]} (registo: {logdir / 'worker.log'})"
        api.update(jid, status="erro", error=msg, etapa="falhou")
        log(f"  falhou: {msg}")
        return

    zips = sorted((pipeline / "Entrega_C").glob(f"entrega_{zona}_*.zip"), key=lambda p: p.stat().st_mtime)
    if not zips:
        api.update(jid, status="erro", error=f"Não encontrei Entrega_C/entrega_{zona}_*.zip")
        return
    dest = Path(args.dados).resolve() / "entregas" / zona
    api.update(jid, progress=95, etapa="a copiar a entrega para a plataforma")
    safe_extract(zips[-1], dest)
    log(f"  entrega {zips[-1].name} -> {dest}")
    try:
        r = api.call("POST", f"/jobs/{jid}/importar", {"pasta": f"entregas/{zona}"}, timeout=900)
        log(f"  importado: {r['import']['elements']} elementos, {r['import']['images']} imagens")
    except Exception as e:   # noqa: BLE001  a API já marcou o pedido como erro
        log(f"  a importação falhou: {e}")


def main():
    ap = argparse.ArgumentParser(description="Processa os pedidos de imagens da plataforma CTRL+F com o pipeline")
    ap.add_argument("--pipeline", required=True, help="pasta do repositório da pipeline (onde está src/ctrlf)")
    ap.add_argument("--dados", required=True, help="pasta dados do projeto ctrl-f (ligada à API em /data/media)")
    ap.add_argument("--pesos", help="pasta dos pesos (se UMS_MODELS_DIR ainda não estiver definida)")
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--token", default="demo-ana")
    ap.add_argument("--python", default=sys.executable, help="Python do ambiente do pipeline (por omissão, este)")
    ap.add_argument("--max", type=int, default=40, help="máximo de imagens por pedido (omissão 40: alguns minutos)")
    ap.add_argument("--raio", type=float, default=150, help="raio em metros à volta da rua pedida (0 = usar a zona piloto)")
    ap.add_argument("--cpu", action="store_true", help="sem GPU (muito mais lento)")
    ap.add_argument("--uma-vez", action="store_true", help="processa a fila uma vez e sai")
    args = ap.parse_args()

    if not (Path(args.pipeline) / "src" / "ctrlf").is_dir():
        sys.exit(f"Não encontro src/ctrlf em {args.pipeline} (é a pasta do repositório da pipeline?)")
    if not Path(args.dados).is_dir():
        sys.exit(f"Pasta de dados não encontrada: {args.dados}")
    api = Api(args.api, args.token)
    log(f"À espera de pedidos em {args.api} (Ctrl+C para parar)")
    while True:
        try:
            config = api.call("GET", "/config")
            fila = api.call("GET", "/jobs?status=na_fila&limit=10")
            if fila:
                process(api, args, fila[0], config)
                continue
        except KeyboardInterrupt:
            raise
        except Exception as e:   # noqa: BLE001  a API pode estar a reiniciar; tenta outra vez
            log(f"(erro: {e}; tento outra vez daqui a 15 s)")
            time.sleep(15)
            continue
        if args.uma_vez:
            break
        time.sleep(10)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nParado.")
