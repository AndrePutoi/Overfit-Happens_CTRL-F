"""Agrupamento de elementos duplicados: ligação média (UPGMA) sobre p(mesmo objeto), com restrições duras e proteção contra encadeamento.

    niveis = agrupar(n, arestas={(i, j): p}, proibidos={(i, j), ...}, taus=[0.85, 0.5])   ->  uma lista de rótulos de grupo (0..) por nível, do mais exigente ao mais brando

Regras:
  * Ligação MÉDIA com pares sem aresta a contar como p = 0: um grupo só cresce se TODOS os membros se parecem em média; A–B e B–C ligados sem A–C candidatos
    dão média baixa, por isso o encadeamento (grupos de 17 elementos) deixa de acontecer.
  * Restrições duras (cannot-link): dois elementos proibidos (ex.: partilham uma imagem, classes incompatíveis) nunca ficam no mesmo grupo, nem por transitividade.
  * Os níveis são aninhados: continua-se a fundir a partir do estado do nível anterior, até a melhor média cair abaixo de cada tau.
"""
from __future__ import annotations

import heapq
from collections import defaultdict


def agrupar(n: int, arestas: dict[tuple[int, int], float], proibidos: set[tuple[int, int]] | None = None, taus: list[float] | None = None) -> list[list[int]]:
    taus = sorted(taus or [0.85, 0.5], reverse=True)
    proib = defaultdict(set)
    for a, b in (proibidos or ()):
        proib[a].add(b); proib[b].add(a)
    membros = {i: {i} for i in range(n)}
    proibido_de = {i: set(proib[i]) for i in range(n)}          # elementos proibidos a algum membro do grupo
    soma: dict[tuple[int, int], float] = {}
    viz: dict[int, set[int]] = defaultdict(set)
    for (a, b), p in arestas.items():
        if a == b or p <= 0:
            continue
        k = (min(a, b), max(a, b))
        soma[k] = soma.get(k, 0.0) + p
        viz[a].add(b); viz[b].add(a)
    heap = [(-s, a, b) for (a, b), s in soma.items()]          # chave = -MÉDIA (no início, grupos de 1: média = soma)
    heapq.heapify(heap)
    vivo = set(range(n))
    prox = n
    saida = []
    for tau in taus:
        while heap:
            negm, a, b = heap[0]
            if a not in vivo or b not in vivo:
                heapq.heappop(heap); continue
            media = -negm                                        # o heap está ordenado pela MÉDIA (não pela soma): a primeira entrada viva é a melhor
            if media < tau:
                break
            heapq.heappop(heap)
            if membros[b] & proibido_de[a] or membros[a] & proibido_de[b]:
                continue                                          # proibido: este par de grupos nunca se funde
            c = prox; prox += 1
            membros[c] = membros[a] | membros[b]
            proibido_de[c] = proibido_de[a] | proibido_de[b]
            vivo -= {a, b}; vivo.add(c)
            novos = {}
            for x in (a, b):
                for y in viz[x]:
                    if y in (a, b) or y not in vivo:
                        continue
                    kk = (min(x, y), max(x, y))
                    novos[y] = novos.get(y, 0.0) + soma.get(kk, 0.0)
            for y, s in novos.items():
                kk = (min(c, y), max(c, y)); soma[kk] = s
                viz[c].add(y); viz[y].add(c)
                heapq.heappush(heap, (-s / (len(membros[c]) * len(membros[y])), kk[0], kk[1]))
        rot, g = [0] * n, 0
        for c in sorted(vivo):
            for e in membros[c]:
                rot[e] = g
            g += 1
        saida.append(rot)
    return saida
