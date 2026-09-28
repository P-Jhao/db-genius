"""Redact sensitive DB connection info from landing screenshots (mosaic + blur),
then regenerate the OG share image from the redacted hero screenshot."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path("/Users/spcodhu/Code/fronted/db-genius-web/public/landing")

# (filename, [(x1, y1, x2, y2), ...]) in 1600x1000 pixel space
REDACT = {
    "db-genius-database-config.jpg": [
        (318, 152, 470, 180),   # 地址 47.119.191.92:3306
        (318, 178, 380, 205),   # 数据库 blog
        (318, 203, 400, 230),   # 用户 sys_blog
    ],
    "db-genius-ai-sql-query.jpg": [
        (412, 788, 585, 845),   # 选择器标签内 (blog@47.119.191.92:3306)
    ],
    "db-genius-ai-intent-recognition.jpg": [
        (430, 786, 585, 838),   # 选择器标签内 (blog@47.119.191.92:3306)
    ],
}


def mosaic_blur(im: Image.Image, rect):
    x1, y1, x2, y2 = rect
    region = im.crop(rect)
    w, h = region.size
    # mosaic: shrink hard then upscale, then slight blur for smooth edges
    small = region.resize((max(4, w // 14), max(3, h // 14)), Image.BILINEAR)
    mosaic = small.resize((w, h), Image.NEAREST).filter(ImageFilter.GaussianBlur(2))
    im.paste(mosaic, rect)


for name, rects in REDACT.items():
    p = ROOT / name
    im = Image.open(p).convert("RGB")
    for r in rects:
        mosaic_blur(im, r)
    im.save(p, "JPEG", quality=85, optimize=True, progressive=True)
    print("redacted", name)

# ---------- regenerate OG image 1200x630 from redacted screenshot ----------
W, H = 1200, 630
og = Image.new("RGB", (W, H))
d = ImageDraw.Draw(og)
top = (13, 32, 84)
bot = (22, 93, 255)
for y in range(H):
    t = y / H
    d.line([(0, y), (W, y)], fill=tuple(round(a + (b - a) * t) for a, b in zip(top, bot)))
d.ellipse([820, -180, 1300, 300], fill=(38, 110, 255))
d.ellipse([950, 260, 1380, 690], fill=(20, 201, 201))

shot = Image.open(ROOT / "db-genius-ai-sql-query.jpg").convert("RGB")
sw, sh = shot.size
tw = 560
th = round(sh * tw / sw)
shot = shot.resize((tw, th), Image.LANCZOS)
card = Image.new("RGBA", (tw + 24, th + 24), (0, 0, 0, 0))
cd = ImageDraw.Draw(card)
cd.rounded_rectangle([0, 0, tw + 23, th + 23], radius=16, fill=(255, 255, 255, 255))
card.paste(shot.convert("RGBA"), (12, 12))
og.paste(card, (W - tw - 60, (H - th - 24) // 2), card)


def font(sz):
    for fp in [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
    ]:
        if Path(fp).exists():
            return ImageFont.truetype(fp, sz)
    return ImageFont.load_default()


d.text((70, 120), "DB-Genius", font=font(64), fill="white")
d.text((70, 215), "开源 AI 数据库管理大师", font=font(44), fill="white")
d.text((70, 300), "自然语言生成 SQL · 智能工作流自动化", font=font(24), fill=(200, 220, 255))
d.text((70, 345), "数据库对比分析 · 支持 10 种主流数据库", font=font(24), fill=(200, 220, 255))
d.rounded_rectangle([70, 430, 250, 480], radius=25, fill=(20, 201, 201))
d.text((98, 438), "开源免费", font=font(28), fill="white")
d.text((70, 520), "db-genius.com", font=font(24), fill=(150, 180, 235))

og.save(ROOT / "db-genius-og-image.jpg", "JPEG", quality=85, optimize=True)
print("og regenerated")
