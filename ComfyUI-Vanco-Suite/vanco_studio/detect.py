# -*- coding: utf-8 -*-
"""轻量人物检测（YOLOv8 ONNX + onnxruntime），只用于质检，不参与生成。

用法：
    from .detect import detect_persons
    counts, boxes = detect_persons(frames)      # frames: [T,H,W,C] float 0~1 或 uint8
"""
import os
import folder_paths

_SESSION = None
_INPUT = None
_CONF = 0.25
_NMS = 0.45
_SIZE = 640


_YOLO_NAME = "yolov8n.onnx"


def _model_roots():
    """所有可能的 models 根目录：本地 + extra_model_paths 注册的共享目录 + 环境变量。

    之前只查 folder_paths.models_dir（本地 ComfyUI/models），
    而桌面版的模型其实放在 ComfyUI-Shared/models，导致检测静默失效。
    """
    roots = []
    env = os.environ.get("VANCO_YOLO_DIR")
    if env:
        roots.append(env)
    try:
        roots.append(folder_paths.models_dir)
    except Exception:
        pass
    # 从已注册的模型目录反推各自的 models 根
    try:
        for dirs, _exts in (folder_paths.folder_names_and_paths or {}).values():
            for d in (dirs or []):
                roots.append(os.path.dirname(os.path.abspath(d)))
                roots.append(os.path.dirname(os.path.dirname(os.path.abspath(d))))
    except Exception:
        pass
    roots.append(r"D:\Comfy-Desktop\ComfyUI-Shared\models")
    out = []
    for r in roots:
        if r and r not in out:
            out.append(r)
    return out


def _model_path():
    for root in _model_roots():
        for sub in ("yolo", "", "detection", os.path.join("ultralytics", "bbox")):
            d = os.path.join(root, sub) if sub else root
            p = os.path.join(d, _YOLO_NAME)
            if os.path.exists(p):
                return p
    return None


def _lazy():
    global _SESSION, _INPUT
    if _SESSION is not None:
        return _SESSION
    p = _model_path()
    if not p:
        return None
    try:
        import onnxruntime as ort
        so = ort.SessionOptions()
        so.intra_op_num_threads = 2
        so.log_severity_level = 3
        _SESSION = ort.InferenceSession(p, sess_options=so, providers=["CPUExecutionProvider"])
        _INPUT = _SESSION.get_inputs()[0].name
        print("[Vanco] 人物检测模型已加载:", p)
    except Exception as e:
        print("[Vanco] 人物检测模型加载失败:", e)
        _SESSION = None
    return _SESSION


def _prep(frame_u8):
    """letterbox 到 640x640，返回 NCHW float32 (0~1) 和缩放/填充信息。"""
    import cv2
    import numpy as np
    h, w = frame_u8.shape[:2]
    r = min(_SIZE / h, _SIZE / w)
    nh, nw = int(round(h * r)), int(round(w * r))
    img = cv2.resize(frame_u8, (nw, nh), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((_SIZE, _SIZE, 3), 114, dtype=np.uint8)
    top, left = (_SIZE - nh) // 2, (_SIZE - nw) // 2
    canvas[top:top + nh, left:left + nw] = img
    x = canvas[:, :, ::-1].astype(np.float32) / 255.0        # BGR->RGB
    x = x.transpose(2, 0, 1)[None]
    return np.ascontiguousarray(x), r, left, top


def _nms(boxes, scores):
    import cv2
    if not len(boxes):
        return []
    idx = cv2.dnn.NMSBoxes(boxes, scores, _CONF, _NMS)
    return list(idx) if len(idx) else []


def detect_persons(frames, conf=0.25, max_frames=None):
    """返回 (每帧人数列表, 每帧人体框列表)。失败时返回 (None, None)。"""
    global _CONF
    s = _lazy()
    if s is None:
        return None, None
    _CONF = conf
    try:
        import numpy as np
    except Exception:
        return None, None

    if hasattr(frames, "detach"):
        arr = frames.detach().cpu().numpy()
    else:
        arr = np.asarray(frames)
    if arr.dtype != np.uint8:
        arr = (np.clip(arr, 0, 1) * 255).astype(np.uint8)
    if arr.ndim == 5:
        arr = arr[0]
    n = arr.shape[0] if max_frames is None else min(max_frames, arr.shape[0])

    counts, allboxes = [], []
    for i in range(n):
        x, r, left, top = _prep(arr[i])
        out = s.run(None, {_INPUT: x})[0]           # (1,84,8400)
        pred = out[0].T                              # (8400,84)
        cls = pred[:, 4:]
        ids = cls.argmax(1)
        scs = cls.max(1)
        m = (ids == 0) & (scs > _CONF)               # 只要 person
        sel = pred[m]
        ssc = scs[m]
        boxes = []
        for (cx, cy, bw, bh), sc in zip(sel[:, :4], ssc):
            x1 = (cx - bw / 2 - left) / r
            y1 = (cy - bh / 2 - top) / r
            boxes.append([float(x1), float(y1), float(bw / r), float(bh / r)])
        keep = _nms(boxes, [float(v) for v in ssc])
        boxes = [boxes[k] for k in keep] if keep else []
        counts.append(len(boxes))
        allboxes.append(boxes)
    return counts, allboxes
