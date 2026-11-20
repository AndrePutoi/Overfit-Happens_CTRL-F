"""Azimute e posição aproximada de UMA deteção, sem dependências pesadas (plano local; válido a dezenas de metros).

  * azimute = rumo da imagem + ângulo da coluna do centro da caixa (perspetiva, a partir do hfov)  -> sempre que há rumo
  * distância pelo PLANO DO CHÃO (IPM): d = h / tan(atan((y_base - cy) / f)), câmara a `cam_height_m`, horizonte no centro da imagem. Só quando a
    base da caixa está abaixo do horizonte e a família NÃO é `sinal` (a caixa de um sinal é a placa, não o pé do poste)
  * posição = câmara + d na direção do azimute. Para sinais fica só o azimute (`method: azimuth_only`).
Medido no projeto (contra ecopontos do OSM, só resíduos): IPM + corredor da estrada ~6 m, mas amostra pequena e só 43% das observações. É uma
ESTIMATIVA de vista única: o agrupamento por raios e a triangulação (pipeline/ do projeto) fazem melhor com várias vistas.
"""
from __future__ import annotations

import math

M_LAT = 111_320.0


def azimuth(bbox, width: int, heading: float, hfov_deg: float) -> float:
    cx = (bbox[0] + bbox[2]) / 2
    f = (width / 2) / math.tan(math.radians(hfov_deg) / 2)
    return (heading + math.degrees(math.atan((cx - width / 2) / f))) % 360


def ground_distance(bbox, width: int, height: int, hfov_deg: float, cam_height_m: float = 1.5, d_max: float = 40.0) -> float | None:
    dy = bbox[3] - height / 2
    if dy <= 1.0:
        return None
    f = (width / 2) / math.tan(math.radians(hfov_deg) / 2)
    return min(cam_height_m / math.tan(math.atan(dy / f)), d_max)


def move(lat: float, lon: float, az_deg: float, dist_m: float) -> tuple[float, float]:
    a = math.radians(az_deg)
    return lat + dist_m * math.cos(a) / M_LAT, lon + dist_m * math.sin(a) / (M_LAT * math.cos(math.radians(lat)))


def locate(family: str, bbox, meta: dict, cam_height_m: float = 1.5) -> dict | None:
    """-> {azimuth, distance_m, lat, lon, method} ou None se a imagem não tem rumo/campo de visão/dimensões (ou é panorama)."""
    w, h = meta.get("width"), meta.get("height")
    heading, hfov, lat, lon = meta.get("heading"), meta.get("hfov_deg"), meta.get("lat"), meta.get("lon")
    if None in (w, h, heading, hfov, lat, lon) or meta.get("camera_type", "perspective") != "perspective":
        return None
    az = azimuth(bbox, int(w), float(heading), float(hfov))
    out = {"azimuth": round(az, 1), "method": "azimuth_only", "distance_m": None, "lat": None, "lon": None}
    if family != "sinal":
        d = ground_distance(bbox, int(w), int(h), float(hfov), cam_height_m)
        if d is not None:
            la, lo = move(float(lat), float(lon), az, d)
            out.update(distance_m=round(d, 1), lat=round(la, 7), lon=round(lo, 7), method="ground_plane")
    return out
