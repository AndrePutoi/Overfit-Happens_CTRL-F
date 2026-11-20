# Erro de posição — aveiro_res_novo

315 elementos de resíduos no catálogo · 50 ecopontos OSM na zona (verdade aproximada) · gate 40 m

## Elementos vs OSM (sem emparelhar)

- **Precisão (proxy)**, elementos com ecoponto OSM a ≤ r: <=5m 2% | <=10m 6% | <=15m 12% | <=25m 28% (mais próximo mediano 48.5 m)
- **Recolha (proxy)**, ecopontos OSM com elemento a ≤ r: <=5m 26% | <=10m 46% | <=15m 48% | <=25m 60%
- método `triangulado` (n=84): <=5m 6% | <=10m 11% | <=15m 17% | <=25m 31%
- método `vista_unica_profundidade` (n=231): <=5m 0% | <=10m 5% | <=15m 10% | <=25m 27%
- vistas 1 (n=174): <=5m 1% | <=10m 6% | <=15m 11% | <=25m 29%
- vistas >=2 (n=141): <=5m 4% | <=10m 7% | <=15m 14% | <=25m 26%

## Emparelhamento 1-1 (dentro do gate)

- 33 pares · 282 elementos sem par · 17 ecopontos OSM sem par
- erro (m): {'p25': 8.28, 'p50': 11.22, 'p75': 18.28, 'p90': 27.04}
  - `triangulado` (n=12): mediana 7.33 m, p90 13.75 m
  - `vista_unica_profundidade` (n=21): mediana 14.47 m, p90 27.82 m

## Distância ou rumo? (por observação, elementos emparelhados)

- 305 observações. Distância real câmara→objeto mediana 13.8 m; estimada (todas as obs) 24.5 m
- **razão distância estimada/real**: {'p25': 1.06, 'p50': 1.59, 'p75': 2.07, 'p90': 3.38}  (1 = certo; >1 = posto longe demais)
- **erro ao longo do raio**: {'p25': 3.7, 'p50': 10.28, 'p75': 17.34, 'p90': 27.34, 'abs_mediano': 12.1} m  → mediana |erro| 12.1 m
- **erro de rumo**: {'p25': -21.2, 'p50': -5.99, 'p75': 19.2, 'p90': 53.69, 'abs_mediano': 21.1} °  → |erro| mediano 21.1°
- **erro lateral** mediano |.| = 5.0 m
- **erro de rumo por orientação da vista (yaw)** (mediana, °; se for igual em todas é um desvio de heading; se mudar com o yaw é convenção do yaw ou hfov): y0: 16.1° (n=58), y90: -4.0° (n=39), y180: -16.8° (n=136), y270: -6.6° (n=72)
## 10 ecopontos OSM subterrâneos/semi: elemento `subterraneo` <=5m 50% | <=10m 50% | <=15m 50% | <=25m 50%
