from PIL import Image, ImageFilter
import os
from collections import deque

SRC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets')
OUT_DIR = os.path.join(SRC_DIR, 'processed')
SIZE = (256, 256)


def rgb_to_hsv(r, g, b):
    r, g, b = r / 255.0, g / 255.0, b / 255.0
    mx = max(r, g, b)
    mn = min(r, g, b)
    df = mx - mn
    if df == 0:
        h = 0.0
    elif mx == r:
        h = (60.0 * ((g - b) / df) + 360.0) % 360.0
    elif mx == g:
        h = (60.0 * ((b - r) / df) + 120.0) % 360.0
    else:
        h = (60.0 * ((r - g) / df) + 240.0) % 360.0
    s = 0.0 if mx == 0 else df / mx
    return h, s, mx


def is_background(r, g, b, s_threshold=0.08, v_threshold=0.88):
    """Background: bright and nearly desaturated (white/gray)."""
    _, s, v = rgb_to_hsv(r, g, b)
    return v >= v_threshold and s <= s_threshold


def is_near_white(r, g, b, v_threshold=0.90, s_threshold=0.08):
    """Strict check for nearly-white fringe pixels (skin/peach survives)."""
    _, s, v = rgb_to_hsv(r, g, b)
    return v >= v_threshold and s <= s_threshold


def erode_alpha(img, radius=1):
    """
    Shrink the opaque region by a few pixels to remove the light-colored
    fringe that remains after background removal.
    """
    alpha = img.split()[3]
    # MinFilter expands transparent (0) pixels inward, eating the edge fringe.
    size = 1 + 2 * radius
    eroded = alpha.filter(ImageFilter.MinFilter(size=size))
    img.putalpha(eroded)
    return img


def remove_white_fringe(img, edge_dilate=16):
    """
    After flood-fill, translucent white fringe often remains along hair/clothes.
    Dilate the transparent mask to include the fringe band, then make any
    remaining light pixels in that band fully transparent.
    The source images are large (e.g. 1920x1920), so edge_dilate must be large
    enough to cover the anti-aliased fringe at full resolution.
    """
    w, h = img.size
    pixels = img.load()
    alpha = img.split()[3]

    # Expand the transparent region inward by edge_dilate pixels.
    size = 1 + 2 * edge_dilate
    dilated = alpha.filter(ImageFilter.MinFilter(size=size))
    dilated_pixels = dilated.load()

    for y in range(h):
        for x in range(w):
            # Pixel is in the dilated fringe band and still has some opacity.
            if dilated_pixels[x, y] == 0 and pixels[x, y][3] > 0:
                r, g, b, _ = pixels[x, y]
                # Use a strict saturation threshold so peach skin survives,
                # but near-white anti-aliased fringe becomes transparent.
                if is_near_white(r, g, b, v_threshold=0.76, s_threshold=0.16):
                    pixels[x, y] = (r, g, b, 0)
    return img


def remove_stray_white_pixels(img, v_threshold=0.90, s_threshold=0.10):
    """
    Remove isolated nearly-white pixels that survived inside the character.
    This catches hair/strand gaps without eroding the whole silhouette.
    """
    w, h = img.size
    pixels = img.load()
    for y in range(h):
        for x in range(w):
            r, g, b, a = pixels[x, y]
            if a > 0 and is_near_white(r, g, b, v_threshold, s_threshold):
                pixels[x, y] = (r, g, b, 0)
    return img


def remove_background(img, s_threshold=0.08, v_threshold=0.88):
    """
    Flood-fill from the image edges and remove only connected background.
    Uses HSV saturation/value to distinguish white/gray background from the
    colored character, so the body/shirt are never erased.
    """
    w, h = img.size
    pixels = img.load()
    visited = [[False for _ in range(h)] for _ in range(w)]
    queue = deque()

    def try_enqueue(x, y):
        if 0 <= x < w and 0 <= y < h and not visited[x][y]:
            visited[x][y] = True
            queue.append((x, y))

    # Seed from edges: only true background pixels.
    for x in range(w):
        r, g, b, _ = pixels[x, 0]
        if is_background(r, g, b, s_threshold, v_threshold):
            try_enqueue(x, 0)
        r, g, b, _ = pixels[x, h - 1]
        if is_background(r, g, b, s_threshold, v_threshold):
            try_enqueue(x, h - 1)
    for y in range(h):
        r, g, b, _ = pixels[0, y]
        if is_background(r, g, b, s_threshold, v_threshold):
            try_enqueue(0, y)
        r, g, b, _ = pixels[w - 1, y]
        if is_background(r, g, b, s_threshold, v_threshold):
            try_enqueue(w - 1, y)

    while queue:
        x, y = queue.popleft()
        r, g, b, a = pixels[x, y]
        pixels[x, y] = (r, g, b, 0)

        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h and not visited[nx][ny]:
                nr, ng, nb, _ = pixels[nx, ny]
                if is_background(nr, ng, nb, s_threshold, v_threshold):
                    visited[nx][ny] = True
                    queue.append((nx, ny))

    return img


frames = {
    'idle': ['pet_idle.jpg'],
    'run': ['pet_run_1.jpg', 'pet_run_2.jpg'],
    'jump': ['pet_jump.jpg'],
    'dance': ['pet_dance_1.jpg', 'pet_dance_2.jpg'],
}


os.makedirs(OUT_DIR, exist_ok=True)


def process_image(src_path):
    img = Image.open(src_path).convert('RGBA')
    img = remove_background(img)
    img = remove_white_fringe(img)
    img = remove_stray_white_pixels(img, v_threshold=0.94, s_threshold=0.06)
    bbox = img.getbbox()
    if bbox:
        img = img.crop(bbox)
        w, h = img.size
        max_dim = max(w, h)
        square = Image.new('RGBA', (max_dim, max_dim), (0, 0, 0, 0))
        square.paste(img, ((max_dim - w) // 2, (max_dim - h) // 2))
        img = square
    img = img.resize(SIZE, Image.Resampling.LANCZOS)
    img = erode_alpha(img, radius=1)
    return img


def main():
    for state, files in frames.items():
        for i, fn in enumerate(files):
            src = os.path.join(SRC_DIR, fn)
            if not os.path.exists(src):
                print(f'[WARN] missing {src}')
                continue
            img = process_image(src)
            out_name = f'{state}_{i}.png'
            out_path = os.path.join(OUT_DIR, out_name)
            img.save(out_path)
            print(f'[OK] {out_path}')


if __name__ == '__main__':
    main()

