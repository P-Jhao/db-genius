"""Regenerate the OG share image (1200x630) with English copy and the new
English product screenshot. Same layout/gradient as make_landing_assets.py.
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path("/Users/spcodhu/Code/fronted/db-genius-web/public/landing")

W, H = 1200, 630
og = Image.new("RGB", (W, H))
d = ImageDraw.Draw(og)

# vertical gradient dark blue
top = (13, 32, 84)
bot = (22, 93, 255)
for y in range(H):
    t = y / H
    d.line([(0, y), (W, y)], fill=tuple(round(a + (b - a) * t) for a, b in zip(top, bot)))

# decorative circles
d.ellipse([820, -180, 1300, 300], fill=(38, 110, 255))
d.ellipse([950, 260, 1380, 690], fill=(20, 201, 201))

# product screenshot, right side, rounded card
shot = Image.open(ROOT / "en" / "db-genius-ai-sql-query.jpg").convert("RGB")
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
    for p in [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
    ]:
        if Path(p).exists():
            return ImageFont.truetype(p, sz)
    return ImageFont.load_default()


d.text((70, 105), "DB-Genius", font=font(60), fill="white")
d.text((70, 195), "Open-source AI", font=font(44), fill="white")
d.text((70, 255), "Database Manager", font=font(44), fill="white")
d.text((70, 340), "Natural language to SQL · Workflow automation", font=font(20), fill=(200, 220, 255))
d.text((70, 375), "Database diff · 10 mainstream databases", font=font(20), fill=(200, 220, 255))

# badge
badge_text = "Open Source"
bf = font(28)
bw = round(d.textlength(badge_text, font=bf))
pad_x = 28
d.rounded_rectangle([70, 435, 70 + bw + pad_x * 2, 485], radius=25, fill=(20, 201, 201))
d.text((70 + pad_x, 443), badge_text, font=bf, fill="white")

d.text((70, 530), "db-genius.com", font=font(24), fill=(150, 180, 235))

og.save(ROOT / "db-genius-og-image.jpg", "JPEG", quality=85, optimize=True)
print("og", og.size, (ROOT / "db-genius-og-image.jpg").stat().st_size // 1024, "KB")
