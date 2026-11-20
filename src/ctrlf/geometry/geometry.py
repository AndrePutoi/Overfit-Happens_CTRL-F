"""Geolocalização de um objeto a partir de imagens (secção 8 do plano).

Tudo em metros no sistema ETRS89 / PT-TM06 (EPSG:3763); entra e sai WGS84.
Convenção de azimute: graus, 0 = Norte, sentido horário (igual ao `compass_angle`
do Mapillary e ao heading do Street View).

Autoteste (sem dados nenhuns):  python -m ctrlf.geometry.geometry
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from pyproj import Transformer

_TO_M = Transformer.from_crs(4326, 3763, always_xy=True)
_TO_DEG = Transformer.from_crs(3763, 4326, always_xy=True)


def to_m(lat: float, lon: float) -> np.ndarray:
    x, y = _TO_M.transform(lon, lat)
    return np.array([x, y])


def to_deg(xy: np.ndarray) -> tuple[float, float]:
    lon, lat = _TO_DEG.transform(xy[0], xy[1])
    return lat, lon


def direction(az_deg: float) -> np.ndarray:
    """Vetor unitário (este, norte) para um azimute."""
    a = math.radians(az_deg)
    return np.array([math.sin(a), math.cos(a)])


# --------------------------------------------------------- passo 2: azimute
def bearing_offset_perspective(cx: float, width: int, hfov_deg: float) -> float:
    """Ângulo (graus) do objeto em relação ao eixo da câmara; + = direita."""
    f = (width / 2) / math.tan(math.radians(hfov_deg) / 2)
    return math.degrees(math.atan((cx - width / 2) / f))


def bearing_offset_equirect(cx: float, width: int) -> float:
    """Panorama 360°: coluna proporcional ao ângulo.  Centro da imagem = heading."""
    return (cx / width - 0.5) * 360.0


def object_azimuth(cx: float, width: int, heading: float, camera_type: str = "perspective",
                   hfov_deg: float = 65.0) -> float:
    off = (bearing_offset_equirect(cx, width) if camera_type == "equirectangular"
           else bearing_offset_perspective(cx, width, hfov_deg))
    return (heading + off) % 360.0


# ------------------------------------------- passo 3: vista única (distância)
def single_view_position(cam_lat: float, cam_lon: float, azimuth: float,
                         distance_m: float) -> tuple[float, float]:
    p = to_m(cam_lat, cam_lon) + distance_m * direction(azimuth)
    return to_deg(p)


# ------------------------------------------------------ passo 4: triangulação
@dataclass
class Ray:
    origin: np.ndarray   # metros (x, y)
    dir: np.ndarray      # unitário

    @classmethod
    def from_obs(cls, cam_lat: float, cam_lon: float, azimuth: float) -> "Ray":
        return cls(to_m(cam_lat, cam_lon), direction(azimuth))


def _lsq_point(rays: list[Ray]) -> np.ndarray:
    A = np.zeros((2, 2)); b = np.zeros(2)
    for r in rays:
        P = np.eye(2) - np.outer(r.dir, r.dir)      # projeta no perpendicular à semirreta
        A += P; b += P @ r.origin
    return np.linalg.solve(A, b)


def _perp_dist(p: np.ndarray, r: Ray) -> float:
    v = p - r.origin
    return abs(v[0] * r.dir[1] - v[1] * r.dir[0])


def _in_front(p: np.ndarray, r: Ray) -> bool:
    return float((p - r.origin) @ r.dir) > 0


def triangulate(rays: list[Ray], inlier_m: float = 2.0, min_angle_deg: float = 5.0,
                iters: int = 100, seed: int = 0):
    """Devolve (ponto_xy_metros, resíduo_rms_m, índices_inliers) ou None.

    RANSAC: tenta pares de semirretas, conta quantas passam a menos de `inlier_m`
    do ponto de cruzamento (e à frente da câmara), e reajusta com todas as boas.
    `min_angle_deg` rejeita pares quase paralelos (cruzamento mal condicionado).
    """
    n = len(rays)
    if n < 2:
        return None
    rng = np.random.default_rng(seed)
    best: list[int] = []
    pairs = [(i, j) for i in range(n) for j in range(i + 1, n)]
    if len(pairs) > iters:
        pairs = [pairs[k] for k in rng.choice(len(pairs), iters, replace=False)]
    for i, j in pairs:
        cosang = abs(float(rays[i].dir @ rays[j].dir))
        if math.degrees(math.acos(min(1.0, cosang))) < min_angle_deg:
            continue
        p = _lsq_point([rays[i], rays[j]])
        inl = [k for k, r in enumerate(rays) if _perp_dist(p, r) < inlier_m and _in_front(p, r)]
        if len(inl) > len(best):
            best = inl
    if len(best) < 2:
        return None
    p = _lsq_point([rays[k] for k in best])
    res = float(np.sqrt(np.mean([_perp_dist(p, rays[k]) ** 2 for k in best])))
    return p, res, best


# ---------------------------------------------------------------- confiança
def confidence(scores: list[float], residual_m: float | None) -> float:
    """c_e = (1 - prod(1 - s_i)) * g_e   (secção 8 do plano).

    g_e = 1/(1+(r/2)^2) com r o resíduo da triangulação em metros.
    Sem triangulação (vista única) g_e = 0.6 fixo -> fica baixo e vai para revisão.
    """
    agree = 1.0 - float(np.prod([1.0 - s for s in scores]))
    g = 0.6 if residual_m is None else 1.0 / (1.0 + (residual_m / 2.0) ** 2)
    return agree * g


# ------------------------------------------------------------------ autoteste
if __name__ == "__main__":
    # Objeto "verdadeiro" algures em Aveiro; 3 câmaras a olhar para ele de pontos diferentes.
    true_lat, true_lon = 40.64050, -8.65380
    tp = to_m(true_lat, true_lon)
    rng = np.random.default_rng(1)

    cams = [(-20, 0), (-10, -15), (5, -20), (15, -12)]      # (dx, dy) em metros
    rays = []
    for dx, dy in cams:
        cam = tp + np.array([dx, dy], float)
        lat, lon = to_deg(cam)
        true_az = math.degrees(math.atan2(tp[0] - cam[0], tp[1] - cam[1])) % 360
        noisy = true_az + rng.normal(0, 1.5)                 # 1.5° de ruído de heading
        rays.append(Ray.from_obs(lat, lon, noisy))
    # uma semirreta má (associação errada) para testar o RANSAC
    lat, lon = to_deg(tp + np.array([30.0, 5.0]))
    rays.append(Ray.from_obs(lat, lon, 20.0))

    out = triangulate(rays)
    assert out is not None
    p, res, inl = out
    err = float(np.linalg.norm(p - tp))
    print(f"triangulação: erro {err:.2f} m | resíduo {res:.2f} m | inliers {inl} de {len(rays)}")
    assert err < 2.0 and len(rays) - 1 not in inl, "RANSAC deveria ter ignorado a semirreta má"

    # vista única: câmara a 12 m a sul do objeto, a olhar para norte, objeto ao centro
    clat, clon = to_deg(tp + np.array([0.0, -12.0]))
    az = object_azimuth(cx=960, width=1920, heading=0.0, hfov_deg=65)
    lat, lon = single_view_position(clat, clon, az, 12.0)
    e1 = float(np.linalg.norm(to_m(lat, lon) - tp))
    print(f"vista única (distância exata): erro {e1:.2f} m")
    assert e1 < 0.1

    print("confiança 3 vistas, resíduo 0.5 m:", round(confidence([0.7, 0.6, 0.8], 0.5), 3))
    print("confiança 1 vista (0.8):          ", round(confidence([0.8], None), 3))
    print("geometry.py OK")
