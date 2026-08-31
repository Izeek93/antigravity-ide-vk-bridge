import os
import sys
import ctypes
from ctypes import windll
from PIL import ImageGrab

def attach_to_desktop():
    """Attach current thread to interactive desktop station."""
    try:
        user32 = windll.user32
        hwinsta = user32.OpenWindowStationW('winsta0', False, 0x10000000 | 0xF037F)
        if hwinsta:
            user32.SetProcessWindowStation(hwinsta)
        hdesk = user32.OpenDesktopW('default', 0, False, 0x10000000 | 0xF01FF)
        if hdesk:
            user32.SetThreadDesktop(hdesk)
    except Exception as e:
        print(f"[Warning] Could not attach to winsta0: {e}", file=sys.stderr)

def capture_desktop(output_path: str = "desktop.png") -> str:
    abs_output = os.path.abspath(output_path)
    attach_to_desktop()
    
    try:
        img = ImageGrab.grab(all_screens=True)
        img.save(abs_output, format="PNG")
        return abs_output
    except Exception as e:
        print(f"PIL capture failed: {e}. Trying fallback...", file=sys.stderr)
        raise e

if __name__ == "__main__":
    path = "desktop.png"
    if len(sys.argv) > 1:
        path = sys.argv[1]
    saved = capture_desktop(path)
    print(f"Screenshot saved to: {saved}")
