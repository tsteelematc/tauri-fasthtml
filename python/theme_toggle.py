"""Cross-platform OS appearance (dark/light mode) helpers.

Windows: uses winreg + ctypes.windll to read/write the registry value and
         broadcast a WM_SETTINGCHANGE so apps pick up the change immediately.

macOS:   uses osascript to talk to System Events, which is the most reliable
         way to toggle appearance and have it take effect immediately.
"""

import subprocess
import sys


def get_theme() -> str:
    """Return the current OS appearance as a human-readable string."""
    if sys.platform == "win32":
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        )
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        winreg.CloseKey(key)
        return "dark mode" if value == 0 else "light mode"

    if sys.platform == "darwin":
        result = subprocess.run(
            [
                "osascript",
                "-e",
                'tell application "System Events" to return dark mode of appearance preferences',
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"osascript failed: {result.stderr.strip()}")
        is_dark = result.stdout.strip().lower() == "true"
        return "dark mode" if is_dark else "light mode"

    raise RuntimeError(
        f"get_theme is not supported on platform: {sys.platform}"
    )


def set_dark_theme() -> str:
    """Switch the OS to dark mode and return a confirmation string."""
    if sys.platform == "win32":
        import ctypes
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            0,
            winreg.KEY_SET_VALUE,
        )
        winreg.SetValueEx(key, "AppsUseLightTheme", 0, winreg.REG_DWORD, 0)
        winreg.SetValueEx(key, "SystemUsesLightTheme", 0, winreg.REG_DWORD, 0)
        winreg.CloseKey(key)
        # Broadcast so Explorer and other apps update immediately
        ctypes.windll.user32.SendMessageTimeoutW(
            0xFFFF, 0x001A, 0, "ImmersiveColorSet", 0, 1000, None
        )
        return "Windows theme set to dark mode"

    if sys.platform == "darwin":
        result = subprocess.run(
            [
                "osascript",
                "-e",
                "tell application \"System Events\" to tell appearance preferences to set dark mode to true",
            ],
            capture_output=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"osascript failed: {result.stderr.decode().strip()}")
        return "macOS appearance set to dark mode"

    raise RuntimeError(
        f"set_appearance is not supported on platform: {sys.platform}"
    )


def set_light_theme() -> str:
    """Switch the OS to light mode and return a confirmation string."""
    if sys.platform == "win32":
        import ctypes
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            0,
            winreg.KEY_SET_VALUE,
        )
        winreg.SetValueEx(key, "AppsUseLightTheme", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "SystemUsesLightTheme", 0, winreg.REG_DWORD, 1)
        winreg.CloseKey(key)
        ctypes.windll.user32.SendMessageTimeoutW(
            0xFFFF, 0x001A, 0, "ImmersiveColorSet", 0, 1000, None
        )
        return "Windows theme set to light mode"

    if sys.platform == "darwin":
        result = subprocess.run(
            [
                "osascript",
                "-e",
                "tell application \"System Events\" to tell appearance preferences to set dark mode to false",
            ],
            capture_output=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"osascript failed: {result.stderr.decode().strip()}")
        return "macOS appearance set to light mode"

    raise RuntimeError(
        f"set_appearance is not supported on platform: {sys.platform}"
    )


def toggle_theme() -> str:
    """Toggle between dark and light mode and return a confirmation string."""
    current = get_theme()
    if "dark" in current:
        return set_light_theme()
    return set_dark_theme()
