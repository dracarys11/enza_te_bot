"""Offline geometry safety checks for automatic REFLECTION route discovery."""
from __future__ import annotations

import unittest
from PIL import Image

from reflection_geometry import BoardCandidate, annotate_board_geometry, candidate_box, ordered_outer_candidates


def settings() -> dict:
    return {
        "canny_low": 60, "canny_high": 160,
        "min_tile_fraction": 0.025, "max_tile_fraction": 0.25,
        "max_aspect_ratio": 2.2, "candidate_count_min": 3, "candidate_count_max": 20,
        "min_separation_fraction": 0.08, "outer_band_fraction": 0.18,
        "outer_count_min": 3, "outer_count_max": 12,
        "boundary_distance_fraction": 0.035, "angular_sector_degrees": 40.0,
        "min_angular_separation_degrees": 8.0, "max_angular_gap_degrees": 115.0,
        "max_neighbor_gap_fraction": 0.55, "min_anchor_margin_fraction": 0.02,
        "neighbor_distance_factor": 1.9, "min_boundary_exposure_degrees": 135.0,
        "topology_score_margin": 0.08,
        "boundary_tiebreak_distance_fraction": 0.004,
        "start_anchor_max_distance_fraction": 0.3,
    }


class ReflectionGeometryTest(unittest.TestCase):
    def ring(self) -> list[BoardCandidate]:
        # Image coordinates: y grows downwards, so clockwise from east is E,S,W,N.
        return [
            BoardCandidate(90, 50, 5, 50), BoardCandidate(50, 90, 5, 50),
            BoardCandidate(10, 50, 5, 50), BoardCandidate(50, 10, 5, 50),
            BoardCandidate(60, 50, 5, 30),  # inner candidate: excluded by outer radial band
        ]

    def test_clockwise_sorting_and_start_anchor_rotation(self) -> None:
        geometry = ordered_outer_candidates("upper_left", self.ring(), (100, 100), (0.9, 0.5), settings())
        self.assertEqual([(round(node.x), round(node.y)) for node in geometry.clockwise],
                         [(90, 50), (50, 90), (10, 50), (50, 10)])
        self.assertEqual(len(geometry.outer_ring), 4)

    def test_outer_ring_filtering_excludes_inner_candidates(self) -> None:
        geometry = ordered_outer_candidates("upper_left", self.ring(), (100, 100), (0.9, 0.5), settings())
        self.assertNotIn((60, 50), [(round(node.x), round(node.y)) for node in geometry.outer_ring])

    def test_small_coordinate_jitter_keeps_clockwise_route_identity(self) -> None:
        jittered = [BoardCandidate(node.x + 1, node.y - 1, node.radius, node.contour_area) for node in self.ring()]
        geometry = ordered_outer_candidates("upper_left", jittered, (100, 100), (0.91, 0.49), settings())
        self.assertEqual([(round(node.x), round(node.y)) for node in geometry.clockwise],
                         [(91, 49), (51, 89), (11, 49), (51, 9)])

    def test_duplicate_or_overlapping_outer_centers_are_rejected(self) -> None:
        nodes = self.ring()[:4] + [BoardCandidate(92, 50, 5, 50)]
        geometry = ordered_outer_candidates("upper_left", nodes, (100, 100), (0.9, 0.5), settings())
        # The topology selector keeps only one angularly overlapping member.
        self.assertEqual(len([node for node in geometry.outer_ring if node.y == 50 and node.x > 80]), 1)

    def test_ambiguous_outer_geometry_stops_safely(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot form"):
            ordered_outer_candidates("upper_left", self.ring()[-1:], (100, 100), (0.6, 0.5), settings())

    def test_non_circular_uneven_boundary_cycle_is_supported(self) -> None:
        outer = [BoardCandidate(*point, 5, 50) for point in ((88, 50), (74, 84), (36, 82),
                                                               (12, 52), (28, 18), (66, 12))]
        geometry = ordered_outer_candidates("upper_left", outer + [BoardCandidate(60, 50, 5, 40)],
                                            (100, 100), (0.88, 0.5), settings())
        self.assertEqual(len(geometry.outer_ring), 6)
        self.assertEqual((round(geometry.clockwise[0].x), round(geometry.clockwise[0].y)), (88, 50))

    def test_interior_radial_outlier_does_not_replace_boundary_member(self) -> None:
        # The interior candidate is farther from the board center than the
        # shallow top boundary member, but lacks hull/boundary support.
        outer = [BoardCandidate(*point, 5, 50) for point in ((50, 30), (90, 50), (50, 90), (10, 50))]
        interior = BoardCandidate(50, 75, 5, 50)
        geometry = ordered_outer_candidates("upper_left", outer + [interior], (100, 100), (0.88, 0.5), settings())
        self.assertNotIn(interior, geometry.outer_ring)

    def test_ambiguous_branch_topology_fails_closed(self) -> None:
        # An anchor equally close to several route members cannot pick a branch.
        with self.assertRaisesRegex(ValueError, "start anchor does not uniquely"):
            ordered_outer_candidates("upper_left", self.ring()[:4], (100, 100), (0.5, 0.5), settings())

    def test_discovered_click_box_is_contained_in_board_roi(self) -> None:
        roi = (0.2, 0.3, 0.7, 0.8)
        box = candidate_box(BoardCandidate(50, 50, 8, 50), roi, (100, 100), half_size_fraction=0.03)
        self.assertGreaterEqual(box[0], roi[0])
        self.assertGreaterEqual(box[1], roi[1])
        self.assertLessEqual(box[2], roi[2])
        self.assertLessEqual(box[3], roi[3])

    def test_annotated_geometry_image_is_rendered_without_action(self) -> None:
        geometry = ordered_outer_candidates("upper_left", self.ring(), (100, 100), (0.9, 0.5), settings())
        annotated = annotate_board_geometry(Image.new("RGB", (100, 100)), diagnostics=geometry.diagnostics,
                                            start_anchor=(0.9, 0.5), geometry=geometry)
        self.assertEqual(annotated.size, (100, 100))


if __name__ == "__main__":
    unittest.main()
