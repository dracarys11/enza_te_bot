"""Read-only diagnostic for the CDP-to-screen game-window capture pipeline."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import pyautogui
from PIL import ImageDraw

from browser_target import BrowserTarget

BASE_DIR = Path(__file__).resolve().parent
pyautogui.FAILSAFE = True


def main() -> int:
    config = json.loads((BASE_DIR / "config.json").read_text())
    with BrowserTarget(config["browser"]["cdp_url"]) as target:
        assert target.page is not None
        target.verify_and_focus()
        dom = target.page.evaluate(
            """() => ({url: location.href, screenX, screenY, outerWidth, outerHeight,
              innerWidth, innerHeight, dpr: devicePixelRatio,
              visualScale: visualViewport ? visualViewport.scale : null,
              candidates: [...document.querySelectorAll('canvas, iframe')].map(el => {
                const r = el.getBoundingClientRect(); return {tag: el.tagName.toLowerCase(), id: el.id,
                className: el.className || '', src: el.src || '', x:r.x, y:r.y, width:r.width, height:r.height,
                visible:r.width >= 160 && r.height >= 90 && getComputedStyle(el).display !== 'none' && getComputedStyle(el).visibility !== 'hidden'};
              })})"""
        )
        window = target.dynamic_game_window(config)
    full = pyautogui.screenshot()
    logical_screen = pyautogui.size()
    scale_x, scale_y = full.width / logical_screen.width, full.height / logical_screen.height
    left, top = round(window["left"] * scale_x), round(window["top"] * scale_y)
    right, bottom = round((window["left"] + window["width"]) * scale_x), round((window["top"] + window["height"]) * scale_y)
    raw = full.crop((left, top, right, bottom))
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    logs = BASE_DIR / "logs"
    logs.mkdir(exist_ok=True)
    desktop = full.copy()
    ImageDraw.Draw(desktop).rectangle((left, top, right, bottom), outline="red", width=4)
    desktop_path = logs / f"{stamp}_A_desktop_game_window.png"
    raw_path = logs / f"{stamp}_B_raw_game_window.png"
    preview_path = logs / f"{stamp}_C_scaled_preview.png"
    desktop.save(desktop_path)
    raw.save(raw_path)
    max_w, max_h = int(logical_screen.width * .80), int(logical_screen.height * .70)
    scale = min(1.0, max_w / raw.width, max_h / raw.height)
    preview = cv2.resize(np.array(raw), (round(raw.width * scale), round(raw.height * scale)), interpolation=cv2.INTER_AREA) if scale < 1 else np.array(raw)
    from PIL import Image
    Image.fromarray(preview).save(preview_path)
    print(f"browser URL: {dom['url']}")
    print(f"window.screenX/screenY: {dom['screenX']}, {dom['screenY']}")
    print(f"window.outerWidth/outerHeight: {dom['outerWidth']}, {dom['outerHeight']}")
    print(f"window.innerWidth/innerHeight: {dom['innerWidth']}, {dom['innerHeight']}")
    print(f"devicePixelRatio: {dom['dpr']}")
    print(f"browser zoom (visualViewport.scale): {dom['visualScale']}")
    print("detected canvas/iframe candidates:")
    for item in dom['candidates']:
        print(item)
    print(f"calculated absolute game_window: {window}")
    print(f"pyautogui logical screen size: {logical_screen.width} x {logical_screen.height}")
    print(f"actual full desktop screenshot dimensions: {full.width} x {full.height}")
    print(f"raw screenshot dimensions: {raw.width} x {raw.height}")
    print(f"expected raw screenshot dimensions: {round(window['width'] * scale_x)} x {round(window['height'] * scale_y)}")
    print(f"scaled preview dimensions: {preview.shape[1]} x {preview.shape[0]}")
    print(f"A desktop overlay: {desktop_path}")
    print(f"B raw game window: {raw_path}")
    print(f"C scaled preview: {preview_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
