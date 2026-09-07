"""Fit-to-screen OpenCV ROI selection with exact coordinate mapping."""
from __future__ import annotations

import cv2
import numpy as np
import pyautogui
from PIL import Image


def select_scaled_roi(image: Image.Image, title: str):
    """Select an ROI on a scaled preview and return it in original-image pixels.

    OpenCV draws the selection rectangle while dragging. Enter/Space confirms;
    Esc or c produces a zero-size selection.
    """
    original_width, original_height = image.size
    screen = pyautogui.size()
    # Reserve substantially more than a title bar for macOS window decorations,
    # menu bar, Dock, and any OpenCV client-area sizing discrepancy.
    max_width = max(1, min(int(screen.width * 0.80), screen.width - 120))
    max_height = max(1, min(int(screen.height * 0.70), screen.height - 180))
    scale = min(1.0, max_width / original_width, max_height / original_height)
    preview_width, preview_height = max(1, round(original_width * scale)), max(1, round(original_height * scale))
    original = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
    cv2.namedWindow(title, cv2.WINDOW_NORMAL)
    for _attempt in range(3):
        preview = cv2.resize(original, (preview_width, preview_height), interpolation=cv2.INTER_AREA) if scale < 1.0 else original
        cv2.resizeWindow(title, preview_width, preview_height)
        cv2.moveWindow(title, max(0, (screen.width - preview_width) // 2), max(0, (screen.height - preview_height) // 2))
        cv2.imshow(title, preview)
        cv2.waitKey(50)
        # This reports the actual drawable image/client rectangle, excluding title bar.
        _left, _top, client_width, client_height = cv2.getWindowImageRect(title)
        if client_width >= preview_width and client_height >= preview_height:
            break
        scale *= min(client_width / preview_width, client_height / preview_height, 0.95)
        preview_width, preview_height = max(1, round(original_width * scale)), max(1, round(original_height * scale))
    else:
        cv2.destroyWindow(title)
        raise RuntimeError("OpenCV could not create a client area large enough for the complete scaled preview.")
    px, py, pwidth, pheight = cv2.selectROI(title, preview, showCrosshair=True, fromCenter=False)
    cv2.destroyWindow(title)
    # Clamp after rounding so a selection on the right/bottom edge stays contained.
    x, y = round(px / scale), round(py / scale)
    right, bottom = round((px + pwidth) / scale), round((py + pheight) / scale)
    x, y = min(max(x, 0), original_width), min(max(y, 0), original_height)
    right, bottom = min(max(right, x), original_width), min(max(bottom, y), original_height)
    return (x, y, right - x, bottom - y), (px, py, pwidth, pheight), (original_width, original_height), (preview_width, preview_height), scale, (screen.width, screen.height)


def select_scaled_point(image: Image.Image, title: str):
    """Select exactly one point on a fitted preview; Enter confirms, Esc cancels."""
    original_width, original_height = image.size
    screen = pyautogui.size()
    max_width = max(1, min(int(screen.width * 0.80), screen.width - 120))
    max_height = max(1, min(int(screen.height * 0.70), screen.height - 180))
    scale = min(1.0, max_width / original_width, max_height / original_height)
    preview_width, preview_height = max(1, round(original_width * scale)), max(1, round(original_height * scale))
    preview = cv2.resize(cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR), (preview_width, preview_height),
                         interpolation=cv2.INTER_AREA) if scale < 1.0 else cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
    selected: list[tuple[int, int]] = []

    def callback(event, x, y, _flags, _param):
        if event == cv2.EVENT_LBUTTONDOWN:
            selected[:] = [(x, y)]

    cv2.namedWindow(title, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(title, preview_width, preview_height)
    cv2.moveWindow(title, max(0, (screen.width - preview_width) // 2), max(0, (screen.height - preview_height) // 2))
    cv2.setMouseCallback(title, callback)
    while True:
        frame = preview.copy()
        if selected:
            cv2.drawMarker(frame, selected[0], (0, 255, 0), cv2.MARKER_CROSS, 20, 2)
        cv2.imshow(title, frame)
        key = cv2.waitKey(30) & 0xFF
        if key in (13, 32) and selected:
            break
        if key in (27, ord("c")):
            cv2.destroyWindow(title)
            return None, (original_width, original_height), (preview_width, preview_height), scale, (screen.width, screen.height)
    cv2.destroyWindow(title)
    px, py = selected[0]
    x = min(max(round(px / scale), 0), original_width - 1)
    y = min(max(round(py / scale), 0), original_height - 1)
    return (x, y), (original_width, original_height), (preview_width, preview_height), scale, (screen.width, screen.height)
