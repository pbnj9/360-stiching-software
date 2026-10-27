import unittest

import numpy as np

from src.stitcher import build_equirect_maps, reframe_equirect


class ReframeEquirectTests(unittest.TestCase):
    def test_center_pixel_looks_at_requested_yaw(self):
        frame = np.zeros((180, 360, 3), dtype=np.uint8)
        frame[:, 180] = (10, 20, 30)

        view = reframe_equirect(frame, yaw_deg=0, fov_deg=90, out_w=101, out_h=57)

        np.testing.assert_array_equal(view[28, 50], (10, 20, 30))

    def test_rejects_invalid_field_of_view(self):
        frame = np.zeros((180, 360, 3), dtype=np.uint8)

        with self.assertRaises(ValueError):
            reframe_equirect(frame, fov_deg=180)

    def test_north_pole_maps_to_top_of_fisheye(self):
        calibration = {
            "front": {
                "cx_frac": 0.5,
                "cy_frac": 0.5,
                "radius_frac": 0.5,
                "fov_deg": 195.0,
            },
            "back": {
                "cx_frac": 0.5,
                "cy_frac": 0.5,
                "radius_frac": 0.5,
                "fov_deg": 195.0,
                "rotation_deg": 0.0,
            },
            "feather_frac": 0.85,
        }

        maps = build_equirect_maps(200, 100, 200, 100, calibration)

        self.assertLess(maps["map_y_front"][0, 100], 50)
