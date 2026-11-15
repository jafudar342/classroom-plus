"""Review-only localization of enrolled eye-region patterns, using normalized correlation."""
import hashlib
import cv2
import numpy as np
from PIL import Image, ImageOps


def eye_patch(gray, area):
    eyes = [area.get(key) for key in ("left_eye", "right_eye")]
    if any(point is None for point in eyes):
        return None
    (lx, ly), (rx, ry) = sorted(eyes)
    distance = rx - lx
    if distance < 12 or abs(ry - ly) > .35 * distance:
        return None
    cy = (ly + ry) / 2
    x, y = round(lx - .25 * distance), round(cy - .24 * distance)
    width, height = round(1.5 * distance), round(.48 * distance)
    if x < 0 or y < 0 or x + width > gray.shape[1] or y + height > gray.shape[0]:
        return None
    patch = gray[y:y+height, x:x+width]
    return patch.copy() if patch.std() >= 8 else None


def reference_patch(engine, path, approval):
    stat = path.stat()
    detector = (approval or {}).get('detector', engine.metadata.get('reference_detector', engine.metadata.get('detector', 'retinaface')))
    key = (str(path), stat.st_mtime_ns, stat.st_size, repr(approval), detector)
    cache = engine.eye_patch_cache
    if key in cache:
        return cache[key]
    patch = None
    if not approval or hashlib.sha256(path.read_bytes()).hexdigest() == approval["photo_sha256"]:
        try:
            with Image.open(path) as image:
                rgb = np.array(ImageOps.exif_transpose(image).convert("RGB"))
        except (OSError, Image.DecompressionBombError):
            cache[key] = None
            return None
        try:
            faces = engine.detect(rgb, detector=detector)
        except Exception as error:
            if getattr(error, "code", None) != "face_not_found":
                raise
            faces = []
        if approval:
            faces = [f for f in faces if all(f["facial_area"][k] == v for k,v in approval["bounding_box"].items())]
        if len(faces) == 1:
            patch = eye_patch(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY), faces[0]["facial_area"])
    if len(cache) >= 512:
        cache.clear()
    cache[key] = patch
    return patch


def search(gray, references):
    # Bound scan cost on high-resolution uploads. Map boxes back to source pixels.
    scale = min(1., 1000 / max(gray.shape))
    if min(gray.shape) * scale < 6:
        return
    frame = cv2.resize(gray, None, fx=scale, fy=scale) if scale < 1 else gray
    hits = []
    for roll, name, patch in references:
        for width in (24, 33, 45, 62, 85, 116, 159, 218, 300):
            height = round(width * patch.shape[0] / patch.shape[1])
            if height < 6 or width > frame.shape[1] or height > frame.shape[0]:
                continue
            template = cv2.resize(patch, (width, height))
            if template.std() < 6:
                continue
            scores = cv2.matchTemplate(frame, template, cv2.TM_CCOEFF_NORMED)
            for _ in range(3):
                _, score, _, (x,y) = cv2.minMaxLoc(scores)
                if score < .70:
                    break
                hits.append((score, roll, name, x, y, width, height))
                scores[max(0,y-height//2):y+height//2+1,max(0,x-width//2):x+width//2+1] = -1
    accepted = []
    for score, roll, name, x, y, w, h in sorted(hits, reverse=True):
        box = tuple(round(v/scale) for v in (x,y,w,h))
        if any(abs(x+w/2-a-w2/2) < .45*max(w,w2) and abs(y+h/2-b-h2/2) < .65*max(h,h2)
               for _,_,_,a,b,w2,h2 in accepted):
            continue
        accepted.append((score,roll,name,x,y,w,h))
        yield roll, name, float(score), box
