"""Advisory reference-photo checks; these do not establish identity or accuracy."""
import cv2
import numpy as np


def reference_quality(face, rgb=None):
    area = face.get("facial_area", {})
    crop = np.asarray(face["face"], dtype=np.uint8)
    if rgb is not None:
        height, width = rgb.shape[:2]
        x, y = max(0, int(area.get("x", 0))), max(0, int(area.get("y", 0)))
        right = min(width, int(area.get("x", 0)) + int(area.get("w", 0)))
        bottom = min(height, int(area.get("y", 0)) + int(area.get("h", 0)))
        if right > x and bottom > y:
            crop = rgb[y:bottom, x:right]
    height, width = crop.shape[:2]
    # Compare sharpness at a bounded resolution; never enlarge a small face.
    scale = min(1.0, 160 / max(height, width))
    sample = cv2.resize(crop, (max(1, round(width * scale)), max(1, round(height * scale))), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(sample, cv2.COLOR_RGB2GRAY)
    brightness = float(gray.mean())
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    checks = [
        dict(key="size", label="Face size", value=f"{width} × {height} px", ok=min(width, height) >= 80,
             tip="Move closer or use a higher-resolution photo; aim for a face at least 80 pixels across."),
        dict(key="sharpness", label="Sharpness", value=round(sharpness, 1), ok=sharpness >= 35,
             tip="Hold still, clean the lens and refocus before taking another photo."),
        dict(key="brightness", label="Lighting", value=round(brightness, 1), ok=35 <= brightness <= 225,
             tip="Face a soft light and avoid a bright window behind you."),
    ]
    return dict(status="ready" if all(check["ok"] for check in checks) else "retake", checks=checks,
                advisory=True, metrics=dict(width=width, height=height, sharpness=round(sharpness, 1), brightness=round(brightness, 1)))
