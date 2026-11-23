#!/usr/bin/env python3
"""Crop KiCad schematic plots to their drawn content. Heuristic described in docs/05-cropping-schematic-plots.md.

    kicaddy run <engine>/kicaddy/crop.py plot.png out.png           # plot without the drawing sheet: trim, pad, fit
    kicaddy run <engine>/kicaddy/crop.py --framed plot.png out.png  # with frame and title block: mask them first

Needs Pillow.
"""

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageChops

FUZZ = 24  # per-channel distance from the background that counts as ink (out of 255)
PAD_MM = 3.0  # margin kept around the content
MAX_SIZE = (1600, 1200)  # px; about what a terminal image viewer shows without rescaling
MIN_DPI = 150  # below this the default 1.27 mm text is under ~7.5 px tall; tile instead of shrinking
OVERLAP_MM = 10  # tile overlap, so a symbol cut by one tile edge is whole in its neighbour
LINE_COVERAGE = 0.95  # a row/column this full of ink is a ruled line, not drawing content
BORDER_COVERAGE = 0.8  # frame lines span the page minus its margins
EDGE_SEARCH = 0.12  # the frames lie within this fraction of the page from each edge


def ink_mask(image):
    """Binary 'L' mask of pixels that differ from the background (the top-left pixel)."""
    if image.mode == "RGBA" and image.getpixel((0, 0))[3] == 0:
        return image.getchannel("A").point(lambda a: 255 if a > FUZZ else 0)
    rgb = image.convert("RGB")
    background = Image.new("RGB", rgb.size, rgb.getpixel((0, 0)))
    r, g, b = ImageChops.difference(rgb, background).split()
    return ImageChops.lighter(ImageChops.lighter(r, g), b).point(lambda d: 255 if d > FUZZ else 0)


def _rows(mask):
    """Ink coverage (0-1) of every row, via a box-filter resize: no per-pixel Python loop."""
    return [v / 255 for v in mask.resize((1, mask.height), Image.BOX).tobytes()]


def _cols(mask):
    return [v / 255 for v in mask.resize((mask.width, 1), Image.BOX).tobytes()]


def _border(coverage, indices):
    """Inner edge of the drawing-sheet border, scanning `indices` from a page edge inward.

    The default sheet has two ruled frames (outer, and inner 2 mm further in, the reference band
    between them). Take the first two bands of near-full rows/columns met from the edge and return
    the index just inside the second. Lines further in are drawing content, however long."""
    bands = []
    for i in indices:
        if coverage[i] <= BORDER_COVERAGE:
            continue
        if bands and abs(i - bands[-1][1]) == 1:
            bands[-1][1] = i
        elif len(bands) == 2:
            break
        else:
            bands.append([i, i])
    if not bands:
        return None
    last = bands[-1][1]
    return last + (1 if indices[1] > indices[0] else -1)


def drawing_sheet_mask(mask):
    """Return (inner_box, title_block_box) for a plot that includes KiCad's default drawing sheet.

    inner_box: area inside the inner border (drops the frame and the reference band).
    title_block_box: the title block rectangle in full-image coordinates, or None.
    """
    w, h = mask.size
    rows, cols = _rows(mask), _cols(mask)
    reach_y, reach_x = int(h * EDGE_SEARCH), int(w * EDGE_SEARCH)
    top = _border(rows, range(0, reach_y)) or 0
    bottom = _border(rows, range(h - 1, h - reach_y, -1)) or h - 1
    left = _border(cols, range(0, reach_x)) or 0
    right = _border(cols, range(w - 1, w - reach_x, -1)) or w - 1
    inner = (left + 1, top + 1, right, bottom)

    # Title block: its top edge is a horizontal rule that runs into the right border, and a vertical
    # rule drops from that rule's left end to the bottom border. Probe a strip next to the border
    # (8 % of the inner width lies inside a 110 mm title block even on A0) for full rows in the
    # lower half, then confirm each candidate, topmost first, by the vertical rule.
    strip = _rows(mask.crop((right - max(4, int((right - left) * 0.08)), 0, right, h)))
    for y in range((top + bottom) // 2, bottom):
        if strip[y] <= LINE_COVERAGE:
            continue
        row = mask.crop((left, y, right, y + 1)).tobytes()
        x0 = len(row) - 1
        while x0 > 0 and row[x0 - 1]:
            x0 -= 1
        x0 += left
        drop = _cols(mask.crop((x0 - 2, y, x0 + 3, bottom)))
        if max(drop) > LINE_COVERAGE:
            return inner, (x0 - 2, y - 2, right, bottom)
    return inner, None


def crop(image, dpi, framed=False):
    """Crop a KiCad plot to its content. Returns rows of images: [[one]], or a tile grid if too big."""
    image = image.convert("RGB") if image.mode not in ("RGB", "RGBA") else image
    mask = ink_mask(image)
    keep = None
    if framed:  # only ink inside the inner border and outside the title block is drawing content
        inner, title_block = drawing_sheet_mask(mask)
        keep = Image.new("L", mask.size, 0)
        keep.paste(255, inner)
        if title_block:
            keep.paste(0, title_block)
        mask = ImageChops.multiply(mask, keep)
    box = mask.getbbox()
    if box is None:
        raise ValueError("plot has no content")
    pad = round(PAD_MM / 25.4 * dpi)
    l, t, r, b = box
    box = (max(0, l - pad), max(0, t - pad), min(image.width, r + pad), min(image.height, b + pad))
    content = image.crop(box)
    if keep is not None:  # the padding can reach back into the frame or title block; paint those background
        background = Image.new(content.mode, content.size, image.getpixel((0, 0)))
        content = Image.composite(content, background, keep.crop(box))

    nx, ny, scale = layout(content.width, content.height, dpi)
    if scale < 1.0:
        content = content.resize((round(content.width * scale), round(content.height * scale)), Image.LANCZOS)
    if nx == ny == 1:
        return [[content]]
    tw, th = min(MAX_SIZE[0], content.width), min(MAX_SIZE[1], content.height)
    step_x = (content.width - tw) / (nx - 1) if nx > 1 else 0
    step_y = (content.height - th) / (ny - 1) if ny > 1 else 0
    return [
        [content.crop((x, y, x + tw, y + th)) for x in (round(i * step_x) for i in range(nx))]
        for y in (round(j * step_y) for j in range(ny))
    ]


def layout(width, height, dpi):
    """Pick the tile grid: the fewest tiles that keep the output at >= MIN_DPI (or the source dpi,
    if lower), each grid scaled to just fit MAX_SIZE tiles with OVERLAP_MM between neighbours.
    Scaling every candidate grid to fit means an extra row or column is only added when it is
    needed for legibility, and then every tile is fully used. Returns (nx, ny, scale <= 1)."""
    need = min(MIN_DPI, dpi)
    overlap = OVERLAP_MM / 25.4 * dpi  # px at source scale
    tw, th = MAX_SIZE
    for n in range(1, 257):
        fits = []
        for nx in (d for d in range(1, n + 1) if n % d == 0):
            ny = n // nx
            # nx tiles of width tw overlapping by overlap*s cover nx*tw - (nx-1)*overlap*s >= width*s
            scale = min(1.0, nx * tw / (width + (nx - 1) * overlap), ny * th / (height + (ny - 1) * overlap))
            if dpi * scale >= need:
                fits.append((scale, nx, ny))
        if fits:
            scale, nx, ny = max(fits)
            return nx, ny, scale
    raise ValueError(f"{width}x{height} px at {dpi} dpi needs more than 256 tiles")


def region(image, dpi, box):
    """The part of a sheetless plot inside `box` (x0, y0, x1, y1 in mm from the page's top-left corner), clipped
    to the page and scaled down to fit MAX_SIZE: (image, scale <= 1). ValueError when the box misses the page."""
    px = [round(v / 25.4 * dpi) for v in box]
    x0, y0, x1, y1 = max(0, px[0]), max(0, px[1]), min(image.width, px[2]), min(image.height, px[3])
    if x1 <= x0 or y1 <= y0:
        raise ValueError("the box is outside the page")
    part = image.crop((x0, y0, x1, y1))
    scale = min(1.0, MAX_SIZE[0] / part.width, MAX_SIZE[1] / part.height)
    if scale < 1.0:
        part = part.resize((max(1, round(part.width * scale)), max(1, round(part.height * scale))), Image.LANCZOS)
    return part, scale


def save(grid, out_path):
    """Write a single image to out_path, or tiles as <stem>_r<row>c<col>; return the paths."""
    out_path = Path(out_path)
    for old in out_path.parent.glob(f"{out_path.stem}_r*c*{out_path.suffix}"):
        old.unlink()
    if len(grid) == 1 and len(grid[0]) == 1:
        grid[0][0].save(out_path)
        return [out_path]
    out_path.unlink(missing_ok=True)
    paths = []
    for r, row in enumerate(grid):
        for c, image in enumerate(row):
            path = out_path.with_name(f"{out_path.stem}_r{r}c{c}{out_path.suffix}")
            image.save(path)
            paths.append(path)
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("plot", help="PNG plotted by KiCad")
    parser.add_argument("out", help="output PNG")
    parser.add_argument("--dpi", type=float, help="plot resolution; default read from the PNG, else 300")
    parser.add_argument("--framed", action="store_true", help="plot includes the default drawing sheet")
    args = parser.parse_args()
    image = Image.open(args.plot)
    dpi = args.dpi or (image.info.get("dpi") or (300,))[0]
    for path in save(crop(image, dpi, framed=args.framed), args.out):
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
