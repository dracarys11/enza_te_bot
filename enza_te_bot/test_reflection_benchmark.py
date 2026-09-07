import math

import cv2
import numpy as np
from PIL import Image

from reflection_benchmark import (contour_first, deduplicate_candidate_centers,
                                  lattice_first, lattice_spacing_consistent)


# 画布 800x500 使 hex 面积占比落入 is_hex 的 area_fraction 窗口
# [0.008, 0.03]（窗口按真实 1280x720 板的 hex 密度校准；旧 360x260
# 画布上 hex 占 3.8-5.7% 被拒收）。两枚 hex 的中心偏移 (145.5, 73)
# 是 lattice_first 由单 tile 推导的格基 (0.75w, 0.5h) 的整数倍
# (i=2, j=0)——偏离格点的第二枚 hex 永远无法被局部验证（实现按
# 设计 fail-closed），且间距 163px ≤ 2.4*min(tile) 的连通性检查。
# 内圈图标用椭圆 (40, 30)：大于 size 门（否则进不了 rejects），
# 顶点数 >7 故在 is_hex 判定处被拒，且完全内含于 hex。
_HEX_RX, _HEX_RY = 45, 38
_HEX_CENTERS = ((150, 140), (295, 213))
_ICON_AXES = (40, 30)


# 8x 超采样后 INTER_AREA 缩回：消除 int32 顶点截断的亚像素偏差，
# 使 Canny 边缘精确落在理想六边形边界上（种子中心的局部验证分数
# 必须能 >= 0.99，否则格基无法建立——见 lattice_first 的 fail-closed）。
_SS = 8


def _hex_image(with_inner=False):
    image = np.zeros((500 * _SS, 800 * _SS, 3), dtype=np.uint8)
    for center in _HEX_CENTERS:
        points = np.array([[round((center[0] + _HEX_RX * math.cos(math.pi * i / 3)) * _SS),
                            round((center[1] + _HEX_RY * math.sin(math.pi * i / 3)) * _SS)]
                           for i in range(6)], dtype=np.int32)
        cv2.polylines(image, [points], True, (255, 255, 255), 5 * _SS)
        if with_inner:
            cv2.ellipse(image, tuple(c * _SS for c in center),
                        tuple(a * _SS for a in _ICON_AXES), 0, 0, 360,
                        (255, 255, 255), 2 * _SS)
    image = cv2.resize(image, (800, 500), interpolation=cv2.INTER_AREA)
    return Image.fromarray(image)


def _settings():
    return {
        "min_tile_fraction": 0.15, "max_tile_fraction": 0.5,
        "max_aspect_ratio": 1.6, "hex_canny_low": 30, "hex_canny_high": 100,
    }


def test_internal_icon_does_not_become_tile_candidate():
    _, hexes, rejects = contour_first(_hex_image(with_inner=True), _settings())
    assert len(hexes) == 2
    assert any(item["reason"] == "internal_fragment_or_non_hex" for item in rejects)


def test_one_lattice_center_at_most_one_candidate_and_duplicates_merge():
    merged = deduplicate_candidate_centers([(10, 10), (10.5, 10.2), (80, 80)], 2)
    assert len(merged) == 2


def test_lattice_spacing_consistency():
    assert lattice_spacing_consistent([(0, 0), (72, 40), (0, 80)], (72, 40))
    assert not lattice_spacing_consistent([(0, 0), (200, 200)], (72, 40))


def test_missing_local_tile_evidence_rejects_generated_center():
    analysis = lattice_first(_hex_image(), _settings(), edge_threshold=0.99)
    assert len(analysis.verified) < len(analysis.generated_centers)


def test_ambiguous_lattice_basis_fails_closed():
    try:
        lattice_first(Image.fromarray(np.zeros((260, 360, 3), dtype=np.uint8)), _settings())
    except ValueError as error:
        assert "ambiguous lattice" in str(error)
    else:
        raise AssertionError("expected ambiguous lattice to fail closed")

