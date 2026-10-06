"""Preview tiles: thumbnails, or drawn play/sound-bar stand-ins for items without a picture."""
import theme

try:
    from PIL import Image, ImageDraw, ImageTk
    HAVE_PIL = True
except ImportError:
    HAVE_PIL = False

GLYPH = {"audio": "♪", "video": "▶", "image": "▣"}


def placeholder(kind, size):
    img = Image.new("RGB", (size, size), theme.PANEL_BG)
    d, s = ImageDraw.Draw(img), size
    if kind == "audio":                      # sound bars
        heights = (0.22, 0.5, 0.8, 0.45, 0.65, 0.3)
        w = s * 0.085
        x = s * 0.5 - len(heights) * w * 1.5 / 2
        for h in heights:
            d.rounded_rectangle([x, s * (0.5 - h / 2), x + w, s * (0.5 + h / 2)],
                                radius=max(1, int(w / 2)), fill=theme.LIGHT_VIOLET)
            x += w * 1.5
    else:                                    # play button
        d.ellipse([s * .22, s * .22, s * .78, s * .78], outline=theme.LIGHT_VIOLET, width=max(2, s // 40))
        d.polygon([(s * .43, s * .35), (s * .43, s * .65), (s * .67, s * .5)], fill=theme.LIGHT_VIOLET)
    return img


def with_play_badge(img):
    """A small play badge in the corner, so a video frame is recognisable next to photos."""
    img = img.copy()
    d, (w, h) = ImageDraw.Draw(img), img.size
    r = max(7, min(w, h) // 7)
    cx, cy = r + 4, h - r - 4
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(0, 0, 0))
    d.polygon([(cx - r * .3, cy - r * .5), (cx - r * .3, cy + r * .5), (cx + r * .55, cy)], fill=(255, 255, 255))
    return img


def tile_image(pil, kind, box_w, box_h):
    """PIL image that fits inside box_w x box_h: the thumbnail (badged if video) or a drawn stand-in."""
    if pil is None:
        return placeholder(kind, min(box_w, box_h))
    img = pil.copy()
    img.thumbnail((box_w, box_h))
    return with_play_badge(img) if kind == "video" else img


def photo(pil, kind, box_w, box_h):
    """Tk image for a tile (None without Pillow)."""
    return ImageTk.PhotoImage(tile_image(pil, kind, box_w, box_h)) if HAVE_PIL else None
