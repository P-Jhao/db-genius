"""Build per-locale web-ready landing screenshots from public/landing/raw/.

- resize to 1600px wide, JPEG quality 82 progressive (same as make_landing_assets.py)
- output: public/landing/<locale>/<name>.jpg
- copy English versions to public/landing/<name>.jpg as root fallback / OG default
- compare screenshot is NOT regenerated (trial edition hides compare); the old
  root-level db-genius-database-compare.jpg is kept as fallback for all locales.
"""
from pathlib import Path
import shutil
from PIL import Image

ROOT = Path("/Users/spcodhu/Code/fronted/db-genius-web/public/landing")
RAW = ROOT / "raw"
LOCALES = ["zh-CN", "zh-TW", "en", "es", "fr", "ja", "ms"]
NAMES = [
    "db-genius-ai-sql-query",
    "db-genius-ai-intent-recognition",
    "db-genius-database-config",
]
TARGET_W = 1600
MAX_KB = 400

for locale in LOCALES:
    out_dir = ROOT / locale
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in NAMES:
        src = RAW / locale / f"{name}.png"
        dst = out_dir / f"{name}.jpg"
        im = Image.open(src).convert("RGB")
        w, h = im.size
        if w > TARGET_W:
            im = im.resize((TARGET_W, round(h * TARGET_W / w)), Image.LANCZOS)
        im.save(dst, "JPEG", quality=82, optimize=True, progressive=True)
        kb = dst.stat().st_size // 1024
        flag = "  <-- OVER 400KB!" if kb > MAX_KB else ""
        print(f"{locale}/{name}.jpg {im.size} {kb} KB{flag}")

# English as root-level default (overwrites old screenshots; compare jpg untouched)
for name in NAMES:
    shutil.copy2(ROOT / "en" / f"{name}.jpg", ROOT / f"{name}.jpg")
    print(f"root/{name}.jpg <= en")

print("done")
