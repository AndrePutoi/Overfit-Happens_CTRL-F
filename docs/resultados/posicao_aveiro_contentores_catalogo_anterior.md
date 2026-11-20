# Erro de posição — aveiro

498 elementos de resíduos no catálogo · 50 ecopontos OSM na zona (verdade aproximada) · gate 40 m

## Elementos vs OSM (sem emparelhar)

- **Precisão (proxy)**, elementos com ecoponto OSM a ≤ r: <=5m 3% | <=10m 10% | <=15m 16% | <=25m 23% (mais próximo mediano 71.2 m)
- **Recolha (proxy)**, ecopontos OSM com elemento a ≤ r: <=5m 24% | <=10m 44% | <=15m 54% | <=25m 54%
- método `triangulado` (n=170): <=5m 4% | <=10m 14% | <=15m 20% | <=25m 27%
- método `vista_unica_profundidade` (n=328): <=5m 2% | <=10m 8% | <=15m 14% | <=25m 21%
- vistas 1 (n=303): <=5m 2% | <=10m 8% | <=15m 14% | <=25m 21%
- vistas >=2 (n=195): <=5m 4% | <=10m 13% | <=15m 19% | <=25m 26%

## Emparelhamento 1-1 (dentro do gate)

- 32 pares · 466 elementos sem par · 18 ecopontos OSM sem par
- erro (m): {'p25': 4.99, 'p50': 7.34, 'p75': 11.82, 'p90': 33.3}
  - `triangulado` (n=17): mediana 7.66 m, p90 20.06 m
  - `vista_unica_profundidade` (n=15): mediana 6.3 m, p90 34.34 m

## Distância ou rumo? (por observação, elementos emparelhados)

- 410 observações. Distância real câmara→objeto mediana 16.5 m; estimada (todas as obs) 24.5 m
- **razão distância estimada/real**: {'p25': 1.1, 'p50': 1.35, 'p75': 1.69, 'p90': 2.9}  (1 = certo; >1 = posto longe demais)
- **erro ao longo do raio**: {'p25': 2.96, 'p50': 7.94, 'p75': 15.85, 'p90': 25.11, 'abs_mediano': 9.2} m  → mediana |erro| 9.2 m
- **erro de rumo**: {'p25': -6.64, 'p50': 13.29, 'p75': 36.54, 'p90': 107.65, 'abs_mediano': 17.9} °  → |erro| mediano 17.9°
- **erro lateral** mediano |.| = 5.1 m
- **erro de rumo por orientação da vista (yaw)** (mediana, °; se for igual em todas é um desvio de heading; se mudar com o yaw é convenção do yaw ou hfov): y0: 12.1° (n=85), y90: 10.2° (n=94), y180: 5.0° (n=125), y270: 19.9° (n=106)

## 4 subterrâneos do piloto: qualquer elemento <=5m 0% | <=10m 50% | <=15m 50% | <=25m 50% | elemento `subterraneo` <=5m 0% | <=10m 50% | <=15m 50% | <=25m 50%
## 10 ecopontos OSM subterrâneos/semi: elemento `subterraneo` <=5m 40% | <=10m 50% | <=15m 50% | <=25m 50%
