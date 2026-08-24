"""Apple Vision 屏幕文字识别（影刀级 OS 底座 · M1）。

能力：
  - capture_screen(region)   CGImage 截屏（可区域裁剪，需屏幕录制权限）
  - ocr_image(cgimage)       文字识别 → [{text, confidence, bounds{x,y,w,h}}]
  - locate_text(text, ...)   在截图中找目标文字（含模糊包含匹配）→ 最佳包围盒
  - render_text_image        测试辅助：CoreText 渲染文字到位图（离线确定性）

坐标约定：bounds 为图像像素坐标、左上角原点。
Vision 原生归一化包围盒为左下角原点，此处已转换。

依赖：pyobjc-framework-Vision + pyobjc-framework-Quartz（darwin）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

try:
    import Quartz
    import Vision
    from Foundation import NSData
except ImportError:  # pragma: no cover
    Quartz = None  # type: ignore
    Vision = None  # type: ignore


def _require() -> None:
    if Vision is None or Quartz is None:
        raise RuntimeError(
            "Vision/Quartz unavailable: "
            "uv pip install pyobjc-framework-Vision pyobjc-framework-Quartz")


# ---------------------------------------------------------------------------
# 截屏
# ---------------------------------------------------------------------------

def capture_screen(region: Optional[Dict[str, float]] = None):
    """截主屏 → CGImage。region={x,y,w,h}（全局点坐标，左上原点）。"""
    _require()
    disp = Quartz.CGMainDisplayID()
    if region:
        rect = Quartz.CGRectMake(region["x"], region["y"],
                                 region["w"], region["h"])
    else:
        rect = Quartz.CGDisplayBounds(disp)
    img = Quartz.CGWindowListCreateImage(
        rect,
        Quartz.kCGWindowListOptionOnScreenOnly,
        Quartz.kCGNullWindowID,
        Quartz.kCGWindowImageBoundsIgnoreFraming)
    if img is None:
        raise RuntimeError(
            "screen capture failed — check Screen Recording permission "
            "(系统设置→隐私与安全性→屏幕录制)")
    return img


def load_image(path: str):
    """从文件加载 CGImage（测试/离线 OCR 用）。"""
    _require()
    data = NSData.dataWithContentsOfFile_(path)
    src = Quartz.CGImageSourceCreateWithData(data, None)
    if src is None:
        raise FileNotFoundError(path)
    return Quartz.CGImageSourceCreateImageAtIndex(src, 0, None)


# ---------------------------------------------------------------------------
# OCR 识别
# ---------------------------------------------------------------------------

def ocr_image(cgimage, *, lang: str = "zh-Hans",
              accurate: bool = True) -> List[Dict[str, Any]]:
    """识别图像文字。返回像素坐标（左上原点）的包围盒列表。"""
    _require()
    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(
        Vision.VNRequestTextRecognitionLevelAccurate if accurate
        else Vision.VNRequestTextRecognitionLevelFast)
    langs = [l for l in (["zh-Hans", "en-US"] if lang.startswith("zh")
                         else ["en-US"]) ]
    try:
        req.setRecognitionLanguages_(langs)
    except Exception:
        pass

    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(
        cgimage, None)
    err = handler.performRequests_error_([req], None)
    if err is False:
        raise RuntimeError("Vision performRequests failed")

    w = Quartz.CGImageGetWidth(cgimage)
    h = Quartz.CGImageGetHeight(cgimage)
    out: List[Dict[str, Any]] = []
    for obs in req.results() or []:
        cands = obs.topCandidates_(1)
        if not cands:
            continue
        cand = cands[0]
        bb = obs.boundingBox()  # 归一化，左下原点
        out.append({
            "text": str(cand.string()),
            "confidence": round(float(cand.confidence()), 3),
            "bounds": {
                "x": round(bb.origin.x * w),
                "y": round((1 - bb.origin.y - bb.size.height) * h),
                "w": round(bb.size.width * w),
                "h": round(bb.size.height * h),
            },
        })
    return out


def ocr_screen(region: Optional[Dict[str, float]] = None,
               **kw) -> List[Dict[str, Any]]:
    """截屏 + 识别一步完成。"""
    return ocr_image(capture_screen(region), **kw)


def locate_text(target: str, *,
                region: Optional[Dict[str, float]] = None,
                contains: bool = True,
                min_confidence: float = 0.3,
                **kw) -> Optional[Dict[str, Any]]:
    """在屏幕上找文字 → {bounds, confidence, text}；找不到返回 None。

    多候选时取置信度最高者。
    """
    hits = ocr_screen(region, **kw)
    best = None
    for h in hits:
        ok = (target in h["text"] if contains
              else target == h["text"].strip())
        if ok and h["confidence"] >= min_confidence:
            if best is None or h["confidence"] > best["confidence"]:
                best = h
    return best


# ---------------------------------------------------------------------------
# 测试辅助：确定性文字图渲染（CoreText，无外部依赖）
# ---------------------------------------------------------------------------

def render_text_image(text: str, *, width: int = 600, height: int = 160,
                      font_size: float = 42.0,
                      bg=(1.0, 1.0, 1.0, 1.0), fg=(0, 0, 0, 1)):
    """渲染白底黑字图（供 OCR 单测，离线确定性）。返回 CGImage。"""
    _require()
    from CoreText import (CTFontCreateWithName, CTLineCreateWithAttributedString,
                          CTLineDraw, kCTFontAttributeName,
                          kCTForegroundColorAttributeName)
    from CoreFoundation import CFAttributedStringCreate

    cs = Quartz.CGColorSpaceCreateDeviceRGB()
    ctx = Quartz.CGBitmapContextCreate(
        None, width, height, 8, 0, cs,
        Quartz.kCGImageAlphaPremultipliedLast)
    Quartz.CGContextSetRGBFillColor(ctx, bg[0], bg[1], bg[2], bg[3])
    Quartz.CGContextFillRect(ctx, Quartz.CGRectMake(0, 0, width, height))

    font = CTFontCreateWithName("Helvetica", font_size, None)
    color = Quartz.CGColorCreate(cs, fg)
    attr = CFAttributedStringCreate(
        None, text, {kCTFontAttributeName: font,
                     kCTForegroundColorAttributeName: color})
    line = CTLineCreateWithAttributedString(attr)
    Quartz.CGContextSetTextPosition(ctx, 20, height / 2 - font_size / 2)
    CTLineDraw(line, ctx)

    return Quartz.CGBitmapContextCreateImage(ctx)

def save_cgimage_png(cgimage, path: str) -> None:
    """CGImage → PNG 文件（ImageIO）。"""
    from Foundation import NSURL

    url = NSURL.fileURLWithPath_(str(path))
    dest = Quartz.CGImageDestinationCreateWithURL(
        url, "public.png", 1, None)
    if dest is None:
        raise RuntimeError(f"cannot write png: {path}")
    Quartz.CGImageDestinationAddImage(dest, cgimage, None)
    if not Quartz.CGImageDestinationFinalize(dest):
        raise RuntimeError("png finalize failed")
