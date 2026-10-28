from math import ceil, floor

from PIL import Image, ImageFilter

_CELLS = 8


def _pixel_box(box, width, height):
    left = max(0, min(width, floor(float(box.get("Left", 0)) * width)))
    top = max(0, min(height, floor(float(box.get("Top", 0)) * height)))
    right = max(left, min(width, ceil((float(box.get("Left", 0)) + float(box.get("Width", 0))) * width)))
    bottom = max(top, min(height, ceil((float(box.get("Top", 0)) + float(box.get("Height", 0))) * height)))
    return left, top, right, bottom


def blur_regions(image, boxes, radius=12):
    result = image.copy()
    for box in boxes:
        pixels = _pixel_box(box, *result.size)
        if pixels[0] == pixels[2] or pixels[1] == pixels[3]:
            continue
        region = result.crop(pixels)
        width, height = region.size
        cell = max(1, min(width, height) // _CELLS)
        mosaic = region.resize((max(1, width // cell), max(1, height // cell)), Image.BOX)
        region = mosaic.resize((width, height), Image.BILINEAR)
        result.paste(region.filter(ImageFilter.GaussianBlur(radius=max(radius, cell // 2))), pixels)
    return result
