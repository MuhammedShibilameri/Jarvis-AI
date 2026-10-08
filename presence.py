"""Always-on presence for Jarvis.

  - Single-instance guard (kills the duplicate-window respawn bug).
  - System-tray icon: Show Jarvis / Listen now / Start with Windows / Exit.
  - Global push-to-talk hotkey Ctrl+Alt+J (ctypes RegisterHotKey, zero deps).
  - The window's close (X) button hides it to the tray instead of quitting.

The heavy GUI backends (pystray, winforms) are imported lazily so that
the app still starts if a dependency is missing.
"""

import ctypes
import os
import sys
import threading
import time
import winreg
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
LOCK_FILE = os.path.join(HERE, "jarvis.running")
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "JarvisUI"
WANTED_HOTKEY = "Ctrl+Alt+J"

_HOTKEY_ID = 1
_MOD_ALT = 0x0001
_MOD_CONTROL = 0x0002
_VK_J = 0x4A
_WM_HOTKEY = 0x0312
_STILL_ACTIVE = 259

exit_requested = False  # set True to allow the window to really close
_tray = None
_stop_hotkey = threading.Event()


# ---------------------------------------------------------------- helpers
def log(message):
    try:
        print(message)
    except Exception:
        pass


def _pid_alive(pid):
    """True if a Windows process with this PID is still running."""
    kernel32 = ctypes.windll.kernel32
    try:
        handle = kernel32.OpenProcess(0x1000, 0, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    except Exception:
        return False
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return code.value == _STILL_ACTIVE
        return False
    finally:
        kernel32.CloseHandle(handle)


# ------------------------------------------------------- single instance
_lock_handle = None


def acquire_single_instance():
    """Return True if this copy may run. Exits cleanly if another one does.

    A lock file left behind by a crashed (killed) process is treated as
    stale and removed, so a fresh start is always possible.
    """
    global _lock_handle
    for attempt in range(2):
        try:
            if os.path.exists(LOCK_FILE):
                try:
                    with open(LOCK_FILE, "r", encoding="utf-8") as f:
                        old = int((f.read() or "").strip() or 0)
                except Exception:
                    old = 0
                if old and _pid_alive(old):
                    log(f"(already running as PID {old} - this copy exits)")
                    return False
                # The lock is stale (dead PID). Remove it and retry.
                try:
                    os.remove(LOCK_FILE)
                except OSError:
                    pass
            handle = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(handle, str(os.getpid()).encode("utf-8"))
            _lock_handle = handle
            return True
        except FileExistsError:
            # Another copy created it between our check and our create.
            if attempt == 0:
                time.sleep(0.15)
                continue
            log("(already running - lock race, this copy exits)")
            return False
    return False


def release_single_instance():
    global _lock_handle
    try:
        if _lock_handle is not None:
            os.close(_lock_handle)
            _lock_handle = None
    except Exception:
        pass
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
    except Exception:
        pass


# ------------------------------------------------------------ autostart
def autostart_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, RUN_NAME)
        return True
    except FileNotFoundError:
        return False
    except Exception:
        return False


def _launcher_path():
    exe = sys.executable
    candidate = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.exists(candidate):
        return candidate
    return exe


def set_autostart(on):
    """Add/remove the HKCU Run entry. Returns the new state."""
    exe = _launcher_path()
    args = f'"{exe}" "{os.path.join(HERE, "jarvis_ui.py")}" --tray'
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if on:
            winreg.SetValueEx(key, RUN_NAME, 0, winreg.REG_SZ, args)
        else:
            try:
                winreg.DeleteValue(key, RUN_NAME)
            except FileNotFoundError:
                pass
    return on


# ----------------------------------------------------------------- tray
def _make_image():
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((8, 8, 56, 56), fill=(217, 173, 76, 255), outline=(110, 84, 32, 255), width=3)
    draw.ellipse((24, 20, 40, 36), fill=(20, 40, 70, 255))
    draw.arc((22, 24, 42, 44), 200, 340, fill=(20, 40, 70, 255), width=2)
    return img


def start_tray(show_fn, listen_fn, exit_fn):
    """Run the notification-area icon. Never raises (best effort)."""
    global _tray
    try:
        import pystray
    except Exception as error:
        log(f"(tray unavailable: {error})")
        return

    def on_show(icon, item):
        show_fn()

    def on_listen(icon, item):
        listen_fn()

    def on_toggle_startup(icon, item):
        item.checked = set_autostart(not autostart_enabled())
        log(f"(start with windows {'on' if item.checked else 'off'})")

    def on_exit(icon, item):
        exit_fn()

    menu = pystray.Menu(
        pystray.MenuItem("Show Jarvis", on_show, default=True),
        pystray.MenuItem(f"Listen now ({WANTED_HOTKEY})", on_listen),
        pystray.MenuItem(
            "Start with Windows",
            on_toggle_startup,
            checked=lambda item: autostart_enabled(),
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Exit", on_exit),
    )
    try:
        _tray = pystray.Icon("Jarvis", _make_image(), "Jarvis - always listening", menu)
        _tray.run_detached()
        log("(tray icon: on)")
    except Exception as error:
        log(f"(tray failed: {error})")
        _tray = None


def stop_tray():
    global _tray
    try:
        if _tray is not None:
            _tray.stop()
    except Exception:
        pass
    _tray = None


# -------------------------------------------------------- push-to-talk
def _hotkey_thread(on_hotkey):
    user32 = ctypes.windll.user32
    if not user32.RegisterHotKey(None, _HOTKEY_ID, _MOD_CONTROL | _MOD_ALT, _VK_J):
        log("(push-to-talk hotkey unavailable - probably already in use)")
        return
    log(f"(push-to-talk: {WANTED_HOTKEY})")
    msg = wintypes.MSG()
    while not _stop_hotkey.is_set():
        result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
        if result <= 0:
            break
        if msg.message == _WM_HOTKEY and msg.wParam == _HOTKEY_ID:
            on_hotkey()
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))
    user32.UnregisterHotKey(None, _HOTKEY_ID)


def start_hotkey(on_hotkey):
    _stop_hotkey.clear()
    threading.Thread(target=_hotkey_thread, args=(on_hotkey,), daemon=True).start()


def stop_hotkey():
    _stop_hotkey.set()


# ------------------------------------------------------ close -> tray
def install_close_hook(exit_allowed, on_hidden):
    """Patch the WinForms FormClosing so the X button hides to the tray.

    The window is webview's winforms BrowserForm (defined as a nested
    class), so we patch that exact class. Mirrors the Camera-permission
    patch already used for WebView2.
    """
    try:
        import webview.platforms.winforms as winforms

        original = winforms.BrowserView.BrowserForm.on_closing

        def patched(self, sender, args):
            if not exit_allowed():
                args.Cancel = True
                try:
                    self.Hide()
                except Exception as error:
                    log(f"(hide failed: {error})")
                on_hidden()
                return
            original(self, sender, args)

        winforms.BrowserView.BrowserForm.on_closing = patched
        log("(close to tray: on)")
    except Exception as error:
        log(f"(close to tray unavailable: {error})")


if __name__ == "__main__":
    # Quick self-test of the non-GUI pieces.
    log("acquire_single_instance -> %s" % acquire_single_instance())
    log("autostart_enabled -> %s" % autostart_enabled())
    release_single_instance()