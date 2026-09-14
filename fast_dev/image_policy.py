"""Versioned local rendering and Qwen server-side pixel budgets."""
import json
import math

VERSION = 'pdf-pixels-v1'
DEFAULT_RENDER_SCALE = 3.0  # 216 dpi; whole-page discovery retains page context.
DEFAULT_MAX_PIXELS = 5120 * 32 * 32


def settings(cfg):
    scale = cfg.get('pdf_render_scale', DEFAULT_RENDER_SCALE)
    pixels = cfg.get('qwen_image_max_pixels', DEFAULT_MAX_PIXELS)
    if type(scale) not in (int, float) or not math.isfinite(scale) or not 1 <= scale <= 300/72:
        raise ValueError('pdf_render_scale 必须为 1 至 300/72（300 dpi）之间的数字')
    if type(pixels) is not int or not 4096 <= pixels <= 16777216:
        raise ValueError('qwen_image_max_pixels 必须为 4096 至 16777216 之间的整数')
    return {'version': VERSION, 'render_scale': float(scale), 'max_pixels': pixels}


def qwen_image_options(model, max_pixels):
    # Qwen extension lives beside image_url, not inside it. Other providers get no extension.
    supported = model.startswith(('qwen3.5-', 'qwen3.6-', 'qwen3.7-', 'qwen3.8-', 'qwen3-vl-', 'qwen-vl-'))
    return {'max_pixels': max_pixels} if supported else {}


def identity(client):
    return json.dumps({'version': VERSION, 'max_pixels': getattr(client, 'image_max_pixels', DEFAULT_MAX_PIXELS)}, sort_keys=True)
