"""Opt-in local ONNX detector. Loaded lazily and never installs a GPU driver."""
from __future__ import annotations
from pathlib import Path

def available_providers():
    try:
        import onnxruntime as ort
        return ort.get_available_providers()
    except ImportError:
        return []

def select_provider(preference="auto", available=None):
    available = available if available is not None else available_providers()
    mapping = {"directml": "DmlExecutionProvider",
               "cuda": "CUDAExecutionProvider", "cpu": "CPUExecutionProvider"}
    if preference not in ("auto", *mapping):
        raise ValueError("Unknown vision compute option")
    if preference == "auto":
        return next((p for p in ("CUDAExecutionProvider", "DmlExecutionProvider",
                                  "CPUExecutionProvider") if p in available), None)
    requested = mapping[preference]
    return requested if requested in available else (
        "CPUExecutionProvider" if "CPUExecutionProvider" in available else None)

def model_status(path, preference="auto"):
    if not path:
        return {"enabled": False, "reason": "No ONNX model configured"}
    model = Path(path)
    if not model.is_file() or model.suffix.lower() != ".onnx":
        return {"enabled": False, "reason": "ONNX model file missing"}
    provider = select_provider(preference)
    if provider is None:
        return {"enabled": False, "reason": "onnxruntime is not installed"}
    return {"enabled": True, "provider": provider, "model_path": str(model)}

def detect(image, path, preference="auto"):
    """Return raw model output metadata; model-specific postprocessing is not assumed."""
    state = model_status(path, preference)
    if not state["enabled"]:
        return state
    import numpy as np
    import onnxruntime as ort
    session = ort.InferenceSession(state["model_path"], providers=[state["provider"]])
    tensor = session.get_inputs()[0]
    shape = tensor.shape
    if len(shape) != 4 or not all(isinstance(n, int) and 0 < n <= 4096 for n in shape[2:]):
        return {"enabled": False, "reason": "Unsupported dynamic ONNX input dimensions"}
    import cv2
    rgb = cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2BGR)
    resized = cv2.resize(rgb, (shape[3], shape[2]))
    inp = (resized[..., ::-1].transpose(2, 0, 1).astype("float32") / 255.0)[None, ...]
    outputs = session.run(None, {tensor.name: inp})
    return {"enabled": True, "provider": state["provider"],
            "output_shapes": [list(x.shape) for x in outputs],
            "note": "Raw ONNX output only; game-action detection is not enabled"}
