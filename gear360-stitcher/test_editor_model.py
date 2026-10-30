import unittest

from src.editor_model import EditorProject, ReframeKeyframe


class EditorProjectTests(unittest.TestCase):
    def test_interpolates_reframe_keyframes(self):
        project = EditorProject(keyframes=[
            ReframeKeyframe(0, 0, 0, 80),
            ReframeKeyframe(10, 100, 20, 100),
        ])
        view = project.view_at(5)
        self.assertEqual((view.yaw_deg, view.pitch_deg, view.fov_deg), (50, 10, 90))
