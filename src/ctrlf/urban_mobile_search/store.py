"""Armazenamento (SQLite, só biblioteca padrão) de imagens, deteções, classificações e decisões do técnico.

Regras que o resto da aplicação pode assumir:
  * Reprocessar uma imagem com um modelo novo ACRESCENTA classificações e nunca altera uma deteção que uma pessoa validou, corrigiu ou rejeitou.
  * Cada decisão humana fica em `edit_log` (antes/depois, quem, quando).
  * A etiqueta efetiva de uma tarefa é a decisão humana mais recente, senão a do modelo mais recente (`Detection.effective`).
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from .models import Classification, Detection, detection_id, iou
from .settings import ATTR_TASKS, CATEGORY_MAP, FIXED_LABELS

SCHEMA = """
CREATE TABLE IF NOT EXISTS images (id TEXT PRIMARY KEY, meta TEXT, admission TEXT, anon_path TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS detections (
  id TEXT PRIMARY KEY, image_id TEXT NOT NULL, family TEXT NOT NULL, cls TEXT NOT NULL, score REAL, x1 REAL, y1 REAL, x2 REAL, y2 REAL,
  status TEXT NOT NULL DEFAULT 'auto', origin TEXT NOT NULL DEFAULT 'model', model_version TEXT, extra TEXT, created_at TEXT, updated_at TEXT);
CREATE INDEX IF NOT EXISTS ix_det_image ON detections(image_id);
CREATE INDEX IF NOT EXISTS ix_det_family ON detections(family, cls, status);
CREATE TABLE IF NOT EXISTS classifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT, detection_id TEXT NOT NULL, task TEXT NOT NULL, label TEXT NOT NULL, score REAL, model TEXT, model_version TEXT,
  source TEXT NOT NULL DEFAULT 'model', by_user TEXT, created_at TEXT, extra TEXT);
CREATE INDEX IF NOT EXISTS ix_cls_det ON classifications(detection_id, task);
CREATE TABLE IF NOT EXISTS edit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, detection_id TEXT, who TEXT, at TEXT, action TEXT, before TEXT, after TEXT);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class Store:
    def __init__(self, path: str | Path = ":memory:"):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            if self.path != ":memory:":
                self._db.execute("PRAGMA journal_mode=WAL")
            self._db.executescript(SCHEMA)
            self._db.commit()

    def close(self) -> None:
        self._db.close()

    # ------------------------------------------------------------ imagens
    def add_image(self, image_id: str, meta: dict | None = None, admission: dict | None = None, anon_path: str | None = None) -> None:
        with self._lock:
            self._db.execute("INSERT INTO images(id, meta, admission, anon_path, created_at) VALUES(?,?,?,?,?) "
                             "ON CONFLICT(id) DO UPDATE SET meta=excluded.meta, admission=excluded.admission, anon_path=COALESCE(excluded.anon_path, anon_path)",
                             (image_id, json.dumps(meta or {}, ensure_ascii=False), json.dumps(admission or {}, ensure_ascii=False), anon_path, now()))
            self._db.commit()

    def get_image(self, image_id: str) -> dict | None:
        r = self._db.execute("SELECT * FROM images WHERE id=?", (image_id,)).fetchone()
        return None if r is None else {"id": r["id"], "meta": json.loads(r["meta"] or "{}"), "admission": json.loads(r["admission"] or "{}"), "anon_path": r["anon_path"]}

    # ------------------------------------------------------------ leitura
    def _load(self, rows) -> list[Detection]:
        out = []
        for r in rows:
            cl = self._db.execute("SELECT * FROM classifications WHERE detection_id=? ORDER BY id", (r["id"],)).fetchall()
            out.append(Detection(id=r["id"], image_id=r["image_id"], family=r["family"], cls=r["cls"], score=r["score"] or 0.0, bbox=(r["x1"], r["y1"], r["x2"], r["y2"]),
                                 status=r["status"], origin=r["origin"], model_version=r["model_version"] or "", extra=json.loads(r["extra"] or "{}"),
                                 classifications=[Classification(id=c["id"], task=c["task"], label=c["label"], score=c["score"] or 0.0, model=c["model"] or "",
                                                                 model_version=c["model_version"] or "", source=c["source"], by=c["by_user"], created_at=c["created_at"],
                                                                 extra=json.loads(c["extra"] or "{}")) for c in cl]))
        return out

    def get(self, det_id: str) -> Detection | None:
        with self._lock:
            r = self._db.execute("SELECT * FROM detections WHERE id=?", (det_id,)).fetchall()
            got = self._load(r)
        return got[0] if got else None

    def list(self, image_id: str | None = None, family: str | None = None, cls: str | None = None, status: str | None = None,
             min_score: float | None = None, label: tuple[str, str] | None = None, include_rejected: bool = False, limit: int = 0) -> list[Detection]:
        """`label=(tarefa, etiqueta)` filtra pela etiqueta EFETIVA (a humana, se existir)."""
        q, a = "SELECT * FROM detections WHERE 1=1", []
        for col, v in (("image_id", image_id), ("family", family), ("cls", cls), ("status", status)):
            if v is not None:
                q += f" AND {col}=?"; a.append(v)
        if status is None and not include_rejected:
            q += " AND status != 'rejeitado'"
        if min_score is not None:
            q += " AND score>=?"; a.append(min_score)
        q += " ORDER BY image_id, score DESC"
        with self._lock:
            dets = self._load(self._db.execute(q, a).fetchall())
        if label:
            dets = [d for d in dets if d.label(label[0]) == label[1]]
        return dets[:limit] if limit else dets

    def stats(self) -> dict:
        with self._lock:
            q = lambda s: self._db.execute(s).fetchall()  # noqa: E731
            return {"imagens": q("SELECT COUNT(*) n FROM images")[0]["n"],
                    "deteccoes": q("SELECT COUNT(*) n FROM detections")[0]["n"],
                    "por_estado": {r["status"]: r["n"] for r in q("SELECT status, COUNT(*) n FROM detections GROUP BY status")},
                    "por_familia_classe": {f"{r['family']}/{r['cls']}": r["n"] for r in q("SELECT family, cls, COUNT(*) n FROM detections WHERE status!='rejeitado' GROUP BY family, cls")},
                    "classificacoes": {f"{r['task']}/{r['source']}": r["n"] for r in q("SELECT task, source, COUNT(*) n FROM classifications GROUP BY task, source")},
                    "decisoes_humanas": q("SELECT COUNT(*) n FROM edit_log")[0]["n"]}

    def history(self, det_id: str) -> list[dict]:
        with self._lock:
            return [{"who": r["who"], "at": r["at"], "action": r["action"], "before": json.loads(r["before"] or "null"), "after": json.loads(r["after"] or "null")}
                    for r in self._db.execute("SELECT * FROM edit_log WHERE detection_id=? ORDER BY id", (det_id,)).fetchall()]

    # ------------------------------------------------------------ escrita do modelo
    def _insert_det(self, d: Detection) -> None:
        t = now()
        self._db.execute("INSERT INTO detections(id,image_id,family,cls,score,x1,y1,x2,y2,status,origin,model_version,extra,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (d.id, d.image_id, d.family, d.cls, d.score, *d.bbox, d.status, d.origin, d.model_version, json.dumps(d.extra, ensure_ascii=False), t, t))

    def _insert_cls(self, det_id: str, c: Classification) -> None:
        self._db.execute("INSERT INTO classifications(detection_id,task,label,score,model,model_version,source,by_user,created_at,extra) VALUES(?,?,?,?,?,?,?,?,?,?)",
                         (det_id, c.task, c.label, c.score, c.model, c.model_version, c.source, c.by, c.created_at or now(), json.dumps(c.extra, ensure_ascii=False)))

    def merge_model_detections(self, image_id: str, dets: list[Detection], iou_thr: float = 0.6) -> dict:
        """Junta as deteções de uma corrida de modelo. -> {inseridas, atualizadas, preservadas}. Nunca mexe no que uma pessoa decidiu."""
        res = {"inseridas": 0, "atualizadas": 0, "preservadas": 0}
        with self._lock:
            existing = self._load(self._db.execute("SELECT * FROM detections WHERE image_id=?", (image_id,)).fetchall())
            for d in dets:
                match = max((e for e in existing if e.family == d.family), key=lambda e: iou(e.bbox, d.bbox), default=None)
                if match is not None and iou(match.bbox, d.bbox) < iou_thr:
                    match = None
                if match is None:
                    self._insert_det(d)
                    for c in d.classifications:
                        self._insert_cls(d.id, c)
                    existing.append(d)
                    res["inseridas"] += 1
                    continue
                if match.status == "auto" and match.origin == "model":
                    self._db.execute("UPDATE detections SET cls=?, score=?, x1=?, y1=?, x2=?, y2=?, model_version=?, extra=?, updated_at=? WHERE id=?",
                                     (d.cls, d.score, *d.bbox, d.model_version, json.dumps({**match.extra, **d.extra}, ensure_ascii=False), now(), match.id))
                    res["atualizadas"] += 1
                else:
                    res["preservadas"] += 1
                for c in d.classifications:                       # as classificações novas ficam sempre (histórico e comparação)
                    self._insert_cls(match.id, c)
            self._db.commit()
        return res

    # ------------------------------------------------------------ decisões humanas
    def _log(self, det_id: str, who: str, action: str, before, after) -> None:
        self._db.execute("INSERT INTO edit_log(detection_id,who,at,action,before,after) VALUES(?,?,?,?,?,?)",
                         (det_id, who, now(), action, json.dumps(before, ensure_ascii=False, default=str), json.dumps(after, ensure_ascii=False, default=str)))

    def _need(self, det_id: str) -> Detection:
        d = self.get(det_id)
        if d is None:
            raise KeyError(f"deteção {det_id} não existe")
        return d

    def confirm(self, det_id: str, by: str) -> Detection:
        d = self._need(det_id)
        with self._lock:
            self._db.execute("UPDATE detections SET status='validado', updated_at=? WHERE id=?", (now(), det_id))
            self._log(det_id, by, "confirmar", {"status": d.status}, {"status": "validado"})
            self._db.commit()
        return self._need(det_id)

    def reject(self, det_id: str, by: str, reason: str = "") -> Detection:
        d = self._need(det_id)
        with self._lock:
            self._db.execute("UPDATE detections SET status='rejeitado', updated_at=? WHERE id=?", (now(), det_id))
            self._log(det_id, by, "rejeitar", {"status": d.status}, {"status": "rejeitado", "motivo": reason})
            self._db.commit()
        return self._need(det_id)

    def correct_label(self, det_id: str, task: str, label: str, by: str, score: float = 1.0) -> Detection:
        """O técnico fixa a etiqueta de uma tarefa. A previsão do modelo fica guardada. Classes com etiqueta fixa (papeleira -> indiferenciado) não a aceitam."""
        d = self._need(det_id)
        fixed = FIXED_LABELS.get((d.family, d.cls), {}).get(task)
        if fixed is not None and label != fixed:
            raise ValueError(f"{d.cls} tem {task} fixo em '{fixed}' (regra); para outro valor, corrige primeiro a classe da deteção")
        with self._lock:
            self._insert_cls(det_id, Classification(task=task, label=label, score=score, model="human", source="human", by=by))
            self._db.execute("UPDATE detections SET status=CASE WHEN status='rejeitado' THEN status ELSE 'corrigido' END, updated_at=? WHERE id=?", (now(), det_id))
            self._log(det_id, by, "corrigir_etiqueta", {"task": task, "label": d.label(task)}, {"task": task, "label": label})
            self._db.commit()
        return self._need(det_id)

    def correct_class(self, det_id: str, cls: str, by: str) -> Detection:
        """Muda a classe da deteção (p. ex. contentor -> papeleira)."""
        d = self._need(det_id)
        with self._lock:
            self._db.execute("UPDATE detections SET cls=?, status='corrigido', updated_at=? WHERE id=?", (cls, now(), det_id))
            self._log(det_id, by, "corrigir_classe", {"cls": d.cls}, {"cls": cls})
            self._db.commit()
        return self._need(det_id)

    def correct_box(self, det_id: str, bbox, by: str) -> Detection:
        d = self._need(det_id)
        with self._lock:
            self._db.execute("UPDATE detections SET x1=?, y1=?, x2=?, y2=?, status='corrigido', updated_at=? WHERE id=?", (*bbox, now(), det_id))
            self._log(det_id, by, "corrigir_caixa", {"bbox": list(d.bbox)}, {"bbox": list(bbox)})
            self._db.commit()
        return self._need(det_id)

    def add_manual(self, image_id: str, family: str, cls: str, bbox, by: str, labels: dict[str, str] | None = None) -> Detection:
        """Caixa desenhada à mão (o modelo falhou). Nasce validada."""
        d = Detection(id=detection_id(image_id, family, cls, bbox), image_id=image_id, family=family, cls=cls, score=1.0, bbox=tuple(float(v) for v in bbox),
                      status="validado", origin="human", model_version="human")
        with self._lock:
            if self._db.execute("SELECT 1 FROM detections WHERE id=?", (d.id,)).fetchone():
                self._db.execute("UPDATE detections SET status='validado', origin='human', updated_at=? WHERE id=?", (now(), d.id))
            else:
                self._insert_det(d)
            for task, label in (labels or {}).items():
                self._insert_cls(d.id, Classification(task=task, label=label, score=1.0, model="human", source="human", by=by))
            self._log(d.id, by, "adicionar_manual", None, {"cls": cls, "bbox": list(bbox), "labels": labels or {}})
            self._db.commit()
        return self._need(d.id)

    # ------------------------------------------------------------ COCO (CVAT)
    def import_coco(self, coco: dict, by: str, iou_thr: float = 0.5, reject_unlisted: bool = False, create_images: bool = True) -> dict:
        """Importa um COCO verificado (export do CVAT) como DECISÕES HUMANAS.
        As imagens ligam-se pelo nome do ficheiro sem extensão (= image_id). Caixa que coincide com uma deteção (IoU) -> validada (ou corrigida,
        se a classe mudou); caixa sem par -> deteção manual. `reject_unlisted`: as deteções da imagem que ninguém listou ficam rejeitadas
        (só usar se o COCO for a verificação COMPLETA dessas imagens)."""
        cats = {c["id"]: c["name"] for c in coco["categories"]}
        imgs = {i["id"]: Path(i["file_name"]).stem for i in coco["images"]}
        res = {"validadas": 0, "corrigidas": 0, "manuais": 0, "rejeitadas": 0, "categorias_desconhecidas": 0, "imagens_novas": 0}
        by_img: dict[str, list[dict]] = {}
        for a in coco["annotations"]:
            by_img.setdefault(imgs[a["image_id"]], []).append(a)
        for image_id in imgs.values():
            if create_images and self.get_image(image_id) is None:
                self.add_image(image_id, {}, {"status": "importada_do_coco"}); res["imagens_novas"] += 1
        for image_id, anns in by_img.items():
            existing = self.list(image_id=image_id, include_rejected=True)
            used: set[str] = set()
            for a in anns:
                name = cats[a["category_id"]]
                if name not in CATEGORY_MAP:
                    res["categorias_desconhecidas"] += 1
                    continue
                fam, cls = CATEGORY_MAP[name]
                x, y, w, h = a["bbox"]
                box = (x, y, x + w, y + h)
                labels = {ATTR_TASKS[k]: str(v) for k, v in (a.get("attributes") or {}).items() if k in ATTR_TASKS and v not in (None, "")}
                for task in FIXED_LABELS.get((fam, cls), {}):          # classes com etiqueta fixa (papeleira): o atributo do CVAT é ignorado
                    labels.pop(task, None)
                m = max((e for e in existing if e.family == fam and e.id not in used), key=lambda e: iou(e.bbox, box), default=None)
                if m is not None and iou(m.bbox, box) >= iou_thr:
                    used.add(m.id)
                    with self._lock:
                        before = {"status": m.status, "cls": m.cls, "bbox": list(m.bbox)}
                        changed = cls != m.cls
                        self._db.execute("UPDATE detections SET cls=?, x1=?, y1=?, x2=?, y2=?, status=?, updated_at=? WHERE id=?",
                                         (cls, *box, "corrigido" if changed else "validado", now(), m.id))
                        for task, label in labels.items():
                            self._insert_cls(m.id, Classification(task=task, label=label, score=1.0, model="cvat", source="human", by=by))
                        self._log(m.id, by, "importar_coco", before, {"status": "corrigido" if changed else "validado", "cls": cls, "labels": labels})
                        self._db.commit()
                    res["corrigidas" if changed else "validadas"] += 1
                else:
                    self.add_manual(image_id, fam, cls, box, by, labels)
                    res["manuais"] += 1
            if reject_unlisted:
                for e in existing:
                    if e.id not in used and e.status in ("auto",):
                        self.reject(e.id, by, "não listada na verificação importada"); res["rejeitadas"] += 1
        return res

    def export_coco(self, family: str | None = None, image_ids: list[str] | None = None, include_rejected: bool = False) -> dict:
        """COCO 1.0 com as etiquetas EFETIVAS (atributos `fluxo` e `tipo`). Imagens só com deteções."""
        rev = {(f, c): n for n, (f, c) in CATEGORY_MAP.items()}
        cats = sorted({n for n in CATEGORY_MAP if family is None or CATEGORY_MAP[n][0] == family})
        cid = {n: i + 1 for i, n in enumerate(cats)}
        images, anns = {}, []
        for d in self.list(family=family, include_rejected=include_rejected):
            if image_ids is not None and d.image_id not in image_ids:
                continue
            name = rev.get((d.family, d.cls))
            if name is None or name not in cid:
                continue
            im = self.get_image(d.image_id) or {"meta": {}}
            if d.image_id not in images:
                m = im["meta"]
                images[d.image_id] = {"id": len(images) + 1, "file_name": f"{d.image_id}.jpg", "width": m.get("width", 0), "height": m.get("height", 0)}
            x1, y1, x2, y2 = d.bbox
            attrs = {"occluded": False}
            for attr, task in ATTR_TASKS.items():
                if d.label(task):
                    attrs[attr] = d.label(task)
            anns.append({"id": len(anns) + 1, "image_id": images[d.image_id]["id"], "category_id": cid[name], "bbox": [round(x1, 1), round(y1, 1), round(x2 - x1, 1), round(y2 - y1, 1)],
                         "area": round((x2 - x1) * (y2 - y1), 1), "iscrowd": 0, "segmentation": [], "score": round(d.score, 3), "attributes": attrs,
                         "ums_id": d.id, "ums_status": d.status})
        return {"licenses": [{"name": "", "id": 0, "url": ""}], "info": {"description": "urban_mobile_search"},
                "categories": [{"id": i, "name": n, "supercategory": ""} for n, i in cid.items()], "images": list(images.values()), "annotations": anns}
