"""Entry point: launches the Gear 360 Stitcher GUI."""
import ctypes
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.gui import main


def enable_high_dpi():
    """Prevent Windows from bitmap-scaling the Tk interface on high-DPI displays."""
    if sys.platform != "win32":
        return

    user32 = ctypes.windll.user32
    try:
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except AttributeError:
        pass

    try:
        if ctypes.windll.shcore.SetProcessDpiAwareness(2) == 0:
            return
    except AttributeError:
        pass

    user32.SetProcessDPIAware()


if __name__ == "__main__":
    enable_high_dpi()
    main()
