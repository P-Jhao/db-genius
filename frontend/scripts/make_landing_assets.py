"""Optimize raw product screenshots into web-ready assets + OG share image."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path("/Users/spcodhu/Code/fronted/db-genius-web/public/landing")

JOBS = [
    ("raw-chat-run-3.png", "db-genius-ai-sql-query.jpg", "DB-Genius AI 对话：自然语言生成 SQL 并返回查询结果"),
    ("raw-chat-run-1.png", "db-genius-ai-intent-recognition.jpg", "DB-Genius AI 意图识别与流式执行过程"),
    ("raw-compare.png", "db-genius-database-compare.jpg", "DB-Genius 数据库对比：Pre 与 Test 环境差异分析"),
    ("raw-db-config.png", "db-genius-database-config.jpg", "DB-Genius 数据库连接配置与连通性验证"),
]

TARGET_W = 1600

for src, dst, _alt in JOBS:
    im = Image.open(ROOT / src).convert("RGB")
    w, h = im.size
    if w > TARGET_W:
        im = im.resize((TARGET_W, round(h * TARGET_W / w)), Image.LANCZOS)
    im.save(ROOT / dst, "JPEG", quality=82, optimize=True, progressive=True)
    print(dst, im.size, (ROOT / dst).stat().st_size // 1024, "KB")

# ---------- OG image 1200x630 ----------
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

# text
def font(sz):
    for p in [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
    ]:
        if Path(p).exists():
            return ImageFont.truetype(p, sz)
    return ImageFont.load_default()

d.text((70, 120), "DB-Genius", font=font(64), fill="white")
d.text((70, 215), "开源 AI 数据库管理大师", font=font(44), fill="white")
d.text((70, 300), "自然语言生成 SQL · 智能工作流自动化", font=font(24), fill=(200, 220, 255))
d.text((70, 345), "数据库对比分析 · 支持 10 种主流数据库", font=font(24), fill=(200, 220, 255))
# badge
d.rounded_rectangle([70, 430, 250, 480], radius=25, fill=(20, 201, 201))
d.text((98, 438), "开源免费", font=font(28), fill="white")
d.text((70, 520), "db-genius.com", font=font(24), fill=(150, 180, 235))

og.save(ROOT / "db-genius-og-image.jpg", "JPEG", quality=85, optimize=True)
print("og", og.size, (ROOT / "db-genius-og-image.jpg").stat().st_size // 1024, "KB")

# cleanup raws
for src, _, _ in JOBS:
    (ROOT / src).unlink(missing_ok=True)
(ROOT / "raw-ai-chat.png").unlink(missing_ok=True)
(ROOT / "raw-conversations.png").unlink(missing_ok=True)
print("done")
