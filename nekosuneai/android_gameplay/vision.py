from __future__ import annotations
import re
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np


@dataclass
class TemplateMatch:
    name: str
    confidence: float
    x: int
    y: int
    width: int
    height: int
    text: str | None = None
    details: dict = field(default_factory=dict)

    @property
    def center(self):
        return self.x + self.width // 2, self.y + self.height // 2


class TemplateVision:
    """
    Optional per-game reference image detector.

    Layout:
      templates/
        generic/
        com.example.game/
        com.another.game/

    The app scans the selected game's folder first, then generic/.
    """

    def __init__(self, templates_root: str, game_id: str, threshold: float = 0.86):
        self.templates_root = Path(templates_root)
        self.game_id = game_id or "generic"
        self.threshold = threshold

    def _folders(self):
        folders = []
        game = self.templates_root / self.game_id
        generic = self.templates_root / "generic"
        if game.exists():
            folders.append(game)
        if generic.exists() and generic != game:
            folders.append(generic)
        return folders

    def scan(self, frame: np.ndarray) -> list[TemplateMatch]:
        matches: list[TemplateMatch] = []
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        for folder in self._folders():
            for path in sorted(folder.glob("*.png")):
                template = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
                if template is None:
                    continue

                th, tw = template.shape[:2]
                fh, fw = gray.shape[:2]
                if th > fh or tw > fw:
                    continue

                result = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
                _, score, _, pos = cv2.minMaxLoc(result)

                if score >= self.threshold:
                    matches.append(
                        TemplateMatch(
                            name=f"{folder.name}/{path.stem}",
                            confidence=float(score),
                            x=int(pos[0]),
                            y=int(pos[1]),
                            width=int(tw),
                            height=int(th),
                        )
                    )
        return matches


class OnnxVision:
    """
    Optional custom ONNX model hook.

    A stock COCO YOLO model is not a universal game-UI detector. A custom model
    or a general vision-language model is usually more useful for unknown games.
    """

    def __init__(self, model_path: str, confidence: float = 0.45):
        self.model_path = Path(model_path)
        if not self.model_path.is_file():
            raise FileNotFoundError(f"YOLO model not found: {self.model_path}")
        self.confidence = confidence
        self.net = cv2.dnn.readNetFromONNX(str(self.model_path))
        self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
        self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
        self.names = (
            "person,bicycle,car,motorcycle,airplane,bus,train,truck,boat,traffic light,"
            "fire hydrant,stop sign,parking meter,bench,bird,cat,dog,horse,sheep,cow,"
            "elephant,bear,zebra,giraffe,backpack,umbrella,handbag,tie,suitcase,frisbee,"
            "skis,snowboard,sports ball,kite,baseball bat,baseball glove,skateboard,"
            "surfboard,tennis racket,bottle,wine glass,cup,fork,knife,spoon,bowl,"
            "banana,apple,sandwich,orange,broccoli,carrot,hot dog,pizza,donut,cake,"
            "chair,couch,potted plant,bed,dining table,toilet,tv,laptop,mouse,remote,"
            "keyboard,cell phone,microwave,oven,toaster,sink,refrigerator,book,clock,"
            "vase,scissors,teddy bear,hair drier,toothbrush"
        ).split(",")
        labels_path = self.model_path.with_suffix(".labels.json")
        if labels_path.exists():
            import json
            self.names = json.loads(labels_path.read_text(encoding="utf-8"))
            if not isinstance(self.names, list) or not all(isinstance(n, str) for n in self.names):
                raise ValueError("YOLO labels must be a JSON list of class names.")

    @property
    def available(self) -> bool:
        return self.net is not None

    def scan(self, frame: np.ndarray) -> list[TemplateMatch]:
        height, width = frame.shape[:2]
        scale = min(640 / width, 640 / height)
        resized = cv2.resize(frame, (round(width * scale), round(height * scale)))
        left = (640 - resized.shape[1]) // 2
        top = (640 - resized.shape[0]) // 2
        padded = np.full((640, 640, 3), 114, dtype=np.uint8)
        padded[top:top + resized.shape[0], left:left + resized.shape[1]] = resized
        self.net.setInput(cv2.dnn.blobFromImage(padded, 1 / 255.0, (640, 640), swapRB=True))
        output = self.net.forward()
        if output.ndim != 3 or output.shape[0] != 1 or output.shape[1] != 4 + len(self.names):
            raise ValueError("Expected YOLOv8 detection ONNX output [1, 4+classes, anchors]; "
                             "use a 640px export without embedded NMS and matching .labels.json.")
        rows = output[0].T
        classes = rows[:, 4:].argmax(axis=1)
        scores = rows[np.arange(len(rows)), classes + 4]
        boxes, confidences, class_ids = [], [], []
        for row, class_id, score in zip(rows, classes, scores):
            if not np.isfinite(row).all() or score < self.confidence:
                continue
            cx, cy, bw, bh = row[:4]
            x1 = int(np.clip((cx - bw / 2 - left) / scale, 0, width))
            y1 = int(np.clip((cy - bh / 2 - top) / scale, 0, height))
            x2 = int(np.clip((cx + bw / 2 - left) / scale, 0, width))
            y2 = int(np.clip((cy + bh / 2 - top) / scale, 0, height))
            if x2 <= x1 or y2 <= y1:
                continue
            boxes.append([x1, y1, x2 - x1, y2 - y1])
            confidences.append(float(score))
            class_ids.append(int(class_id))
        kept = cv2.dnn.NMSBoxesBatched(boxes, confidences, class_ids, self.confidence, 0.45)
        return [TemplateMatch("yolo/" + self.names[class_ids[i]], confidences[i], *boxes[i])
                for i in np.asarray(kept).reshape(-1)[:30]]


class OCRVision:
    def __init__(self, confidence: float = 0.6):
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as exc:
            raise RuntimeError("OCR requires dependencies: python -m pip install -r requirements.txt") from exc
        self.engine_factory = RapidOCR
        self.engine = None
        self.confidence = confidence

    def scan(self, frame: np.ndarray, regions=None) -> list[TemplateMatch]:
        """Read text in the whole frame, or only in the given normalized boxes.

        Recognition cost grows with the number of text lines, so skipping bands
        that hold nothing the agent acts on is the cheapest speed-up available.
        """
        self._ensure_engine()
        height, width = frame.shape[:2]
        matches = self._read_buttons(frame)
        remaining = 1200 - sum(len(m.text or "") for m in matches)
        for results, origin_x, origin_y, ratio_x, ratio_y in self._passes(frame, regions):
            for box, text, score in results or []:
                try:
                    score = float(score)
                except (TypeError, ValueError):
                    continue
                if not np.isfinite(score) or score < self.confidence:
                    continue
                text = " ".join(str(text).split())[:min(120, remaining)]
                points = np.asarray(box, dtype=float)
                if not text or points.shape != (4, 2) or not np.isfinite(points).all():
                    continue
                # Map OCR's resized quadrilateral back to Android screenshot pixels.
                points[:, 0] = points[:, 0]*ratio_x + origin_x
                points[:, 1] = points[:, 1]*ratio_y + origin_y
                x1, y1 = np.floor(points.min(axis=0)).astype(int)
                x2, y2 = np.ceil(points.max(axis=0)).astype(int)
                x1, x2 = np.clip([x1, x2], 0, width)
                y1, y2 = np.clip([y1, y2], 0, height)
                if x2 <= x1 or y2 <= y1:
                    continue
                matches.append(TemplateMatch("ocr/text", float(score), int(x1), int(y1),
                                             int(x2 - x1), int(y2 - y1), text=text))
                remaining -= len(text)
                if len(matches) >= 20 or remaining <= 0:
                    return matches
        return matches

    def _passes(self, frame, regions):
        """Yield (results, origin_x, origin_y, ratio_x, ratio_y) per OCR pass."""
        height, width = frame.shape[:2]
        boxes = [(0.0, 0.0, 1.0, 1.0)] if regions is None else regions
        for x1, y1, x2, y2 in boxes:
            left, top = int(x1*width), int(y1*height)
            crop = frame[top:int(y2*height), left:int(x2*width)]
            if crop.size == 0:
                continue
            crop_h, crop_w = crop.shape[:2]
            scale = min(1.0, 1280 / max(crop_h, crop_w))
            resized = (cv2.resize(crop, (round(crop_w*scale), round(crop_h*scale)))
                       if scale < 1 else crop)
            results, _ = self.engine(resized, use_cls=False)
            yield (results, left, top,
                   crop_w / resized.shape[1], crop_h / resized.shape[0])

    def read_missing_prices(self, frame, matches):
        from .coinmaster_ui import village_targets, parse_coins
        h, w = frame.shape[:2]
        recovered = []
        for target in village_targets(frame, matches):
            if target.name != "coinmaster/building_upgrade" or target.details["price_coins"] is not None:
                continue
            index = target.details["slot"] - 1
            x1, x2 = int((index+.23)*w/5), int((index+1)*w/5)-3
            y1, y2 = int(h*.947), int(h*.989)
            crop = cv2.resize(frame[y1:y2, x1:x2], None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
            for label, confidence in self._read_without_detection(crop):
                if parse_coins(label) is not None:
                    recovered.append(TemplateMatch("ocr/price", confidence, x1, y1, x2-x1, y2-y1,
                                                   text=label))
                    break
        return recovered

    def read_energy(self, frame):
        """The board's text budget runs out before the HUD, so read the pill directly."""
        from .coinmaster_ui import ENERGY_BOX, on_board
        if not on_board(frame):
            return []
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = (int(ENERGY_BOX[0]*w), int(ENERGY_BOX[1]*h),
                          int(ENERGY_BOX[2]*w), int(ENERGY_BOX[3]*h))
        crop = cv2.resize(frame[y1:y2, x1:x2], None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
        for label, score in self._read_without_detection(crop):
            if re.search(r"\d{1,3}\s*/\s*\d{1,3}", label):
                return [TemplateMatch("ocr/energy", score, x1, y1, x2-x1, y2-y1, text=label)]
        return []

    def read_spin_label(self, frame):
        """STOP or SPIN decides whether a roll is already running."""
        from .coinmaster_ui import SPIN_BOX, on_board
        if not on_board(frame):
            return []
        h, w = frame.shape[:2]
        x1, y1 = int(SPIN_BOX[0]*w), int(SPIN_BOX[1]*h)
        x2, y2 = int(SPIN_BOX[2]*w), int(SPIN_BOX[3]*h)
        crop = cv2.resize(frame[y1:y2, x1:x2], None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        for label, score in self._read_without_detection(crop):
            if label.strip().upper() in {"STOP", "SPIN"}:
                return [TemplateMatch("ocr/spin_label", score, x1, y1, x2-x1, y2-y1, text=label)]
        return []

    def _ensure_engine(self):
        if self.engine is None:
            # RapidOCR 1.2.x requires model_path whenever stage options are supplied.
            # None selects its bundled model, also supported by newer releases.
            self.engine = self.engine_factory(intra_op_num_threads=2, inter_op_num_threads=1,
                                              det_use_cuda=False, cls_use_cuda=False, rec_use_cuda=False,
                                              det_model_path=None, cls_model_path=None, rec_model_path=None,
                                              use_angle_cls=False)

    def read_dialog_text(self, frame):
        """Read a result panel's wording, so a shop offer is never mistaken for it."""
        from .coinmaster_ui import DIALOG_TEXT_BOX, has_dialog_shape
        if not has_dialog_shape(frame):
            return []
        self._ensure_engine()
        matches = []
        for results, left, top, ratio_x, ratio_y in self._passes(frame, [DIALOG_TEXT_BOX]):
            for row in results or []:
                if not isinstance(row, (list, tuple)) or len(row) != 3:
                    continue
                box, label, score = row
                try:
                    confidence = float(score)
                except (TypeError, ValueError):
                    continue
                points = np.asarray(box, dtype=float)
                if (not np.isfinite(confidence) or confidence < self.confidence
                        or points.shape != (4, 2) or not np.isfinite(points).all()):
                    continue
                x1, y1 = points.min(axis=0)
                x2, y2 = points.max(axis=0)
                matches.append(TemplateMatch(
                    "ocr/dialog", confidence, int(x1*ratio_x+left), int(y1*ratio_y+top),
                    max(1, int((x2-x1)*ratio_x)), max(1, int((y2-y1)*ratio_y)),
                    text=" ".join(str(label).split())))
        return matches

    def _read_without_detection(self, crop):
        self._ensure_engine()
        # Older RapidOCR uses an instance flag; newer versions accept use_det.
        legacy = hasattr(self.engine, "use_text_det")
        previous = self.engine.use_text_det if legacy else None
        try:
            if legacy:
                self.engine.use_text_det = False
            rows, _ = self.engine(crop, use_det=False, use_cls=False)
        finally:
            if legacy:
                self.engine.use_text_det = previous
        result = []
        for row in rows or []:
            # Without detection RapidOCR yields (text, score); with it, (box, text, score).
            if not isinstance(row, (list, tuple)) or len(row) < 2:
                continue
            label, score = row[-2], row[-1]
            try:
                confidence = float(score)
            except (TypeError, ValueError):
                continue
            if np.isfinite(confidence) and confidence >= self.confidence:
                result.append((" ".join(str(label).split()), confidence))
        return result

    def _read_buttons(self, frame: np.ndarray) -> list[TemplateMatch]:
        """Retry short labels in green button crops at a readable scale."""
        height, width = frame.shape[:2]
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, (30, 100, 65), (90, 255, 255))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        candidates = []
        for contour in contours:
            x, y, bw, bh = cv2.boundingRect(contour)
            if (0.10 * width <= bw <= 0.8 * width and 0.025 * height <= bh <= 0.18 * height
                    and 1.7 <= bw / bh <= 6 and cv2.contourArea(contour) / (bw * bh) >= 0.65):
                candidates.append((x, y, bw, bh))
        matches = []
        for x, y, bw, bh in sorted(candidates, key=lambda b: b[2] * b[3], reverse=True)[:3]:
            # Exclude the button rim; contrast helps dark lettering on a bright fill.
            dx, dy = max(1, bw // 12), max(1, bh // 6)
            crop = frame[y + dy:y + bh - dy, x + dx:x + bw - dx]
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            gray = cv2.resize(gray, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
            _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            binary = cv2.copyMakeBorder(binary, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
            # The crop is already a single isolated label, so skip text detection:
            # running it here costs more than the rest of the frame put together.
            results = self._read_without_detection(cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR))
            if len(results) != 1:
                continue
            text, score = results[0]
            if not 1 <= len(text) <= 32:
                continue
            if text.upper() in {"OK", "0K", "OK!", "0K!"}:
                text = "OK"
            matches.append(TemplateMatch("ocr/button", score, x, y, bw, bh, text=text))
        return matches


class NullVision:
    """Stands in for the ONNX detector when it is switched off."""

    def scan(self, frame) -> list[TemplateMatch]:
        return []


class HybridVision:
    def __init__(self, templates: TemplateVision, detector: OnnxVision, ocr: OCRVision | None = None,
                 game_id: str = ""):
        self.templates = templates
        self.detector = detector
        self.ocr = ocr
        self.game_id = game_id

    def scan(self, frame):
        coinmaster = self.game_id == "com.moonactive.cmboard"
        matches = self.templates.scan(frame) + self.detector.scan(frame)
        if self.ocr is not None:
            regions = None
            if coinmaster:
                from .coinmaster_ui import ocr_regions
                regions = ocr_regions(frame)
            matches.extend(self.ocr.scan(frame, regions))
        if coinmaster:
            from .coinmaster_ui import detect_ui, suppress_matches
            if self.ocr is not None:
                matches.extend(self.ocr.read_missing_prices(frame, matches))
                matches.extend(self.ocr.read_energy(frame))
                matches.extend(self.ocr.read_spin_label(frame))
                matches.extend(self.ocr.read_dialog_text(frame))
            matches = detect_ui(frame, matches) + suppress_matches(matches)
        return matches
