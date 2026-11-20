"""Linha de comandos:  python -m ctrlf <comando>

  info                                   configuração, backends registados e contagens da base
  process IMG [IMG...] [--familias ...]  corre a pipeline (precisa de GPU e pesos) e grava na base
  list [--familia F] [--estado E]        deteções (efetivas) em JSON, uma por linha
  stats                                  contagens
  decide ID --confirmar|--rejeitar|--etiqueta tarefa=valor|--classe C  --por NOME
  import-coco FICHEIRO.json --por NOME [--rejeitar-nao-listadas]     export do CVAT -> decisões humanas
  export-coco SAÍDA.json [--familia F]                                etiquetas efetivas -> COCO 1.0
  zona init|run|plan|status|list NOME ... orquestração por zona (init NOME --place "Baixa, Lisboa" cria uma zona-piloto pequena a partir do OpenStreetMap): caixa geográfica -> pacote de entrega, etapa a etapa, com retoma (docs/ORQUESTRACAO.md)
  weights                                onde pôr os pesos de cada módulo (UMS_MODELS_DIR), quais existem e quais faltam
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .settings import Settings
from .store import Store


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ctrlf", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, help="ficheiro SQLite (omissão: UMS_DB ou data/ums.sqlite)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("info")
    sub.add_parser("stats")
    p = sub.add_parser("process"); p.add_argument("imagens", nargs="+", type=Path); p.add_argument("--familias", nargs="+"); p.add_argument("--locate", action="store_true")
    p = sub.add_parser("list"); p.add_argument("--familia"); p.add_argument("--estado"); p.add_argument("--imagem"); p.add_argument("--limite", type=int, default=0)
    p = sub.add_parser("decide"); p.add_argument("id"); p.add_argument("--por", required=True)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--confirmar", action="store_true"); g.add_argument("--rejeitar", action="store_true")
    g.add_argument("--etiqueta", metavar="TAREFA=VALOR"); g.add_argument("--classe")
    p = sub.add_parser("import-coco"); p.add_argument("ficheiro", type=Path); p.add_argument("--por", required=True); p.add_argument("--rejeitar-nao-listadas", action="store_true")
    p = sub.add_parser("export-coco"); p.add_argument("saida", type=Path); p.add_argument("--familia")
    sub.add_parser("weights")
    p = sub.add_parser("zona", help="orquestração por zona")
    p.add_argument("acao", choices=["run", "plan", "status", "list", "init"])
    p.add_argument("nome", nargs="?")
    p.add_argument("--bbox", nargs=4, type=float, metavar=("MINLON", "MINLAT", "MAXLON", "MAXLAT"))
    p.add_argument("--since"); p.add_argument("--max", type=int); p.add_argument("--max-panoramas", type=int); p.add_argument("--stride", type=int)
    p.add_argument("--place", help="init: nome do sítio (OpenStreetMap/Nominatim), p. ex. \"Baixa, Lisboa\"; só este texto vai à rede")
    p.add_argument("--centro", nargs=2, type=float, metavar=("LAT", "LON"), help="init: centro em vez de --place")
    p.add_argument("--raio", type=float, default=250.0, help="init: raio da caixa em metros (50 a 1500; omissão 250)")
    p.add_argument("--ate"); p.add_argument("--so", nargs="+"); p.add_argument("--refazer", nargs="+"); p.add_argument("--cpu", action="store_true", help="sem GPU (lento; para testar)")
    a = ap.parse_args(argv)

    if a.cmd == "zona":
        return _zona(a)
    s = Settings.from_env()
    if a.db:
        s.db_path = a.db
    store = Store(s.db_path)
    if a.cmd == "info":
        from .backends.legacy import default_registry
        print(json.dumps({"versao": __import__("ctrlf").__version__, "definicoes": {k: str(v) for k, v in vars(s).items() if k in ("project_root", "models_dir", "db_path", "images_dir", "device", "families")},
                          "registo": default_registry(s).describe(), "base": store.stats()}, ensure_ascii=False, indent=1))
    elif a.cmd == "weights":
        from .backends.legacy import default_registry
        rep = default_registry(s).weights_report()
        print(json.dumps({"UMS_MODELS_DIR": str(s.models_dir), "modulos": rep, "em_falta": [r["modulo"] for r in rep if not r["existe"]]}, ensure_ascii=False, indent=1))
    elif a.cmd == "stats":
        print(json.dumps(store.stats(), ensure_ascii=False, indent=1))
    elif a.cmd == "list":
        for d in store.list(image_id=a.imagem, family=a.familia, status=a.estado, limit=a.limite):
            print(json.dumps(d.to_dict(), ensure_ascii=False))
    elif a.cmd == "decide":
        if a.confirmar:
            d = store.confirm(a.id, a.por)
        elif a.rejeitar:
            d = store.reject(a.id, a.por)
        elif a.classe:
            d = store.correct_class(a.id, a.classe, a.por)
        else:
            task, _, label = a.etiqueta.partition("=")
            d = store.correct_label(a.id, task, label, a.por)
        print(json.dumps(d.to_dict(), ensure_ascii=False))
    elif a.cmd == "import-coco":
        print(json.dumps(store.import_coco(json.loads(a.ficheiro.read_text(encoding="utf-8")), a.por, reject_unlisted=a.rejeitar_nao_listadas), ensure_ascii=False))
    elif a.cmd == "export-coco":
        coco = store.export_coco(family=a.familia)
        a.saida.write_text(json.dumps(coco, ensure_ascii=False), encoding="utf-8")
        print(f"{len(coco['annotations'])} caixas em {len(coco['images'])} imagens -> {a.saida}")
    elif a.cmd == "process":
        from .pipeline import Pipeline
        if a.locate:
            s.locate = True
        pipe = Pipeline(s, store=store)
        for r in pipe.process_many([(p, None) for p in a.imagens], a.familias):
            print(json.dumps(r.to_dict(), ensure_ascii=False))
    return 0


def _zona(a) -> int:
    """`zona run|plan|status|list`: ver urban_mobile_search/zona/ e docs/ORQUESTRACAO.md."""
    from ctrlf.ingest import zonas as Z
    from .zona import ETAPAS, Zona, correr, resumo
    if a.acao == "list":
        for n, c in Z.todas().items():
            print(f"{n}\t{c.get('bbox')}")
        return 0
    if not a.nome:
        print("falta o NOME da zona"); return 2
    Z.validar_nome(a.nome)
    if a.acao == "init":
        if Z.carregar(a.nome):
            print(f"a zona {a.nome!r} já existe (data/zonas/{a.nome}/zona.json); usa outro nome"); return 2
        z = Z.criar(a.nome, lugar=a.place, centro=tuple(a.centro) if a.centro else None, raio_m=a.raio, max_imagens=a.max or 20,
                    max_panoramas=a.max_panoramas if a.max_panoramas is not None else 4, since=a.since or "2023-01-01")
        print(f"zona {a.nome!r} criada: caixa {z['bbox']} (raio {z['raio_m']:g} m) · fonte: {z['fonte_da_caixa'].get('encontrado', 'ponto dado')}")
        print(f"  ver o plano:   python -m ctrlf zona plan {a.nome}\n  correr tudo:   python -m ctrlf zona run {a.nome}")
        return 0
    cfg = Z.carregar(a.nome)
    novo = {k: v for k, v in (("bbox", a.bbox), ("since", a.since), ("max", a.max), ("max_panoramas", a.max_panoramas), ("stride", a.stride)) if v is not None}
    if cfg is None:
        if not a.bbox:
            print(f"zona {a.nome!r} nova: indica --bbox MINLON MINLAT MAXLON MAXLAT"); return 2
        cfg = {"nome": a.nome, "max": 300, "stride": 1, **novo}
        if a.acao == "run":
            Z.guardar(cfg)
    elif novo and any(cfg.get(k) != v for k, v in novo.items()):
        print(f"a zona {a.nome!r} já existe com outra configuração ({ {k: cfg.get(k) for k in novo} }); para mudar a caixa ou os limites cria outra zona (evita misturar imagens)"); return 2
    if a.acao == "status":
        print(resumo(a.nome)); return 0
    est = correr(Zona(a.nome, cfg), so=a.so, ate=a.ate, refazer=a.refazer, cpu=a.cpu, plano=(a.acao == "plan"))
    if a.acao == "run":
        print(resumo(a.nome))
        return 0 if est.get("terminada") or (a.ate or a.so) and not est.get("falha") else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
