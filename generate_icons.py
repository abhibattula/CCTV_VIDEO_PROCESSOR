"""
Run once to generate PWA icons: python generate_icons.py
Requires Pillow: pip install Pillow
"""
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("Install Pillow first: pip install Pillow")
    raise

ICONS_DIR = Path("static/icons")
ICONS_DIR.mkdir(parents=True, exist_ok=True)

def make_icon(size: int, path: Path) -> None:
    img = Image.new("RGBA", (size, size), (15, 23, 42, 255))  # dark navy bg
    draw = ImageDraw.Draw(img)

    # Camera body (rounded rect)
    margin = int(size * 0.15)
    body_rect = [margin, int(size * 0.25), size - margin, int(size * 0.80)]
    draw.rounded_rectangle(body_rect, radius=int(size * 0.08), fill=(37, 99, 235, 255))

    # Lens circle
    cx, cy = size // 2, int(size * 0.525)
    r = int(size * 0.14)
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(15, 23, 42, 255))

    # Viewfinder bump
    bump_w = int(size * 0.12)
    bump_rect = [int(size * 0.62), int(size * 0.175), int(size * 0.62) + bump_w, int(size * 0.25)]
    draw.rounded_rectangle(bump_rect, radius=int(size * 0.03), fill=(37, 99, 235, 255))

    # Lens inner highlight
    r2 = int(size * 0.06)
    draw.ellipse([cx - r2, cy - r2, cx + r2, cy + r2], fill=(96, 165, 250, 200))

    img.save(str(path), "PNG")
    print(f"  Generated {path} ({size}×{size})")

print("Generating PWA icons...")
make_icon(192, ICONS_DIR / "icon-192.png")
make_icon(512, ICONS_DIR / "icon-512.png")
print("Done.")
