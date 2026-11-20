"""Agrupamento de duplicados: ligação média, restrições duras, proteção contra encadeamento, níveis aninhados."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ctrlf.pipeline.dedup_cluster import agrupar  # noqa: E402

fails = []


def check(name, ok, info=""):
    print(("PASS" if ok else "FAIL"), name, info)
    if not ok:
        fails.append(name)


def mesmo(rot, *xs):
    return len({rot[x] for x in xs}) == 1


r = agrupar(3, {(0, 1): .95, (1, 2): .95}, taus=[.85])[0]
check("cadeia A–B, B–C sem A–C: não se liga os três a 0,85", mesmo(r, 0, 1) != mesmo(r, 1, 2) or not mesmo(r, 0, 2), str(r))
check("cadeia: A e C nunca no mesmo grupo a 0,85", not mesmo(r, 0, 2))
r = agrupar(3, {(0, 1): .95, (1, 2): .9, (0, 2): .92}, taus=[.85])[0]
check("três mutuamente parecidos formam um grupo", mesmo(r, 0, 1, 2), str(r))
r = agrupar(2, {(0, 1): .99}, proibidos={(0, 1)}, taus=[.5])[0]
check("par proibido nunca se funde, mesmo com p = 0,99", not mesmo(r, 0, 1))
r = agrupar(3, {(0, 1): .95, (1, 2): .95, (0, 2): .95}, proibidos={(0, 2)}, taus=[.5])[0]
check("proibido por transitividade: 0 e 2 nunca juntos", not mesmo(r, 0, 2), str(r))
niv = agrupar(4, {(0, 1): .95, (2, 3): .6, (1, 2): .55, (0, 2): .55, (0, 3): .55, (1, 3): .55}, taus=[.85, .5])
check("níveis aninhados: a 0,85 só {0,1}; a 0,5 todos", mesmo(niv[0], 0, 1) and not mesmo(niv[0], 2, 3) and mesmo(niv[1], 0, 1, 2, 3), str(niv))
check("sem arestas: todos separados", len(set(agrupar(5, {}, taus=[.5])[0])) == 5)
niv = agrupar(6, {(0, 1): .9, (2, 3): .9, (4, 5): .9, (1, 2): .3}, taus=[.85, .2])
check("pares independentes ficam separados a 0,85", len(set(niv[0])) == 3, str(niv[0]))
# regressão: um par de grupos grandes com SOMA alta mas MÉDIA baixa não pode bloquear fusões boas de outros pares
ar = {(0, 1): .95, (2, 3): .95, (0, 2): .8, (0, 3): .8, (1, 2): .8, (1, 3): .8, (4, 5): .9}
r = agrupar(6, ar, taus=[.85])[0]
check("regressão: média (não soma) ordena o heap: {4,5} funde-se apesar de {0,1}x{2,3} ter soma 3,2", mesmo(r, 4, 5) and mesmo(r, 0, 1) and mesmo(r, 2, 3) and not mesmo(r, 0, 2), str(r))
# muitos pares independentes de p alto formam muitos grupos
ar = {(2 * i, 2 * i + 1): .95 for i in range(50)}
check("100 nós em 50 pares: 50 grupos", len(set(agrupar(100, ar, taus=[.85])[0])) == 50)
print("overall:", "PASS" if not fails else f"FAIL {fails}")
sys.exit(1 if fails else 0)
