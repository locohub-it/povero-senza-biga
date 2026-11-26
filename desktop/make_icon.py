"""Genera desktop/icon.ico dal disegno del favicon (aereo bianco su quadrato arrotondato)."""
from pathlib import Path

from PIL import Image, ImageDraw

S = 256
k = S / 32
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle([0, 0, S - 1, S - 1], radius=int(7 * k), fill="#8839ef")  # mauve Catppuccin Latte
P = lambda pts: [(x * k, y * k) for x, y in pts]
d.polygon(P([(6, 15.5), (26, 7), (21.5, 25), (15.3, 20), (12, 24.2), (11.2, 18)]), fill="#ffffff")
d.polygon(P([(11.2, 17.9), (26, 7), (14.5, 19.7)]), fill="#dcc6ff")
out = Path(__file__).with_name("icon.ico")
img.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print(out)
