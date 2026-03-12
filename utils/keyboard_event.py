"""
统一的键盘事件封装，根据云游戏/本地客户端自动选择输入方式。

云游戏模式：通过 CDP (Chrome DevTools Protocol) 发送按键事件，支持后台运行。
本地客户端模式：使用 pynput / pyautogui / win32api 发送按键事件。
"""

import time

from pynput.keyboard import Controller as KeyboardController
from pynput.keyboard import Key as KeyboardKey

from utils.log import log
from utils.window import Window


def _get_cdp_client():
    """延迟获取 CdpClient 单例。"""
    from utils.cdp_client import CdpClient
    from utils.config.config import ConfigurationManager
    cfg = ConfigurationManager()
    port = int(cfg.config_file.get("cdp_debug_port", 9222))
    return CdpClient(port=port)


def _is_cloud_game() -> bool:
    """检测当前是否为云游戏模式。"""
    try:
        window = Window()
        return window.client == "云游戏"
    except Exception:
        return False


# 缓存云游戏检测结果
_cloud_mode_cache = None


def _check_cloud_mode() -> bool:
    global _cloud_mode_cache
    if _cloud_mode_cache is None:
        _cloud_mode_cache = _is_cloud_game()
    return _cloud_mode_cache


class KeyboardEvent:
    """
    键盘事件类，自动根据云游戏/本地模式选择输入方式。
    """

    def __init__(self):
        self.keyboard = KeyboardController()

    @staticmethod
    def translate_key(key_name: str):
        """转换key"""
        if key_name == "space":
            key_name = KeyboardKey.space
        if key_name == "caps":
            key_name = KeyboardKey.caps_lock
        return key_name

    @staticmethod
    def keyboard_press(key_name: str, delay: float = 0):
        """
        按下键盘后延迟抬起。
        云游戏模式下通过 CDP 发送按键，本地模式下通过 pynput。
        """
        if _check_cloud_mode():
            cdp = _get_cdp_client()
            cdp.press_key(key_name, hold_time=max(delay, 0.05))
        else:
            key_name = KeyboardEvent.translate_key(key_name)
            KeyboardController().press(key_name)
            time.sleep(delay)
            KeyboardController().release(key_name)


def press_key_cdp_or_pyautogui(key_name: str, hold_time: float = 0.05):
    """
    替代 pyautogui.press() 的统一按键函数。
    云游戏模式下使用 CDP，否则使用 pyautogui。
    """
    if _check_cloud_mode():
        cdp = _get_cdp_client()
        cdp.press_key(key_name, hold_time=hold_time)
    else:
        import pyautogui
        pyautogui.press(key_name)


def keybd_event_cdp_or_win32(key_name: str, hold_time: float = 0.05):
    """
    替代 win32api.keybd_event() 的统一按键函数。
    云游戏模式下使用 CDP，否则使用 win32api。
    """
    if _check_cloud_mode():
        cdp = _get_cdp_client()
        cdp.press_key(key_name, hold_time=hold_time)
    else:
        import win32api
        import win32con
        vk = _get_vk_code(key_name)
        scan = win32api.MapVirtualKey(vk, 0)
        win32api.keybd_event(vk, scan, 0, 0)
        time.sleep(hold_time)
        win32api.keybd_event(vk, scan, win32con.KEYEVENTF_KEYUP, 0)


def key_down_cdp_or_pynput(key_name):
    """
    按下按键不释放，云游戏模式下使用 CDP。
    key_name 可以是字符串或 pynput Key 对象。
    """
    if _check_cloud_mode():
        cdp = _get_cdp_client()
        name = _pynput_key_to_str(key_name)
        cdp.key_down(name)
    else:
        key = _translate_pynput_key(key_name) if isinstance(key_name, str) else key_name
        KeyboardController().press(key)


def key_up_cdp_or_pynput(key_name):
    """
    释放按键，云游戏模式下使用 CDP。
    key_name 可以是字符串或 pynput Key 对象。
    """
    if _check_cloud_mode():
        cdp = _get_cdp_client()
        name = _pynput_key_to_str(key_name)
        cdp.key_up(name)
    else:
        key = _translate_pynput_key(key_name) if isinstance(key_name, str) else key_name
        KeyboardController().release(key)


def _pynput_key_to_str(key) -> str:
    """将 pynput Key 对象转换为字符串按键名。"""
    if isinstance(key, str):
        return key
    pynput_to_str = {
        KeyboardKey.shift: "shift",
        KeyboardKey.shift_l: "shift",
        KeyboardKey.shift_r: "shift",
        KeyboardKey.ctrl: "ctrl",
        KeyboardKey.ctrl_l: "ctrl",
        KeyboardKey.ctrl_r: "ctrl",
        KeyboardKey.alt: "alt",
        KeyboardKey.alt_l: "alt",
        KeyboardKey.alt_r: "alt",
        KeyboardKey.esc: "esc",
        KeyboardKey.enter: "enter",
        KeyboardKey.space: "space",
        KeyboardKey.tab: "tab",
        KeyboardKey.caps_lock: "caps",
        KeyboardKey.backspace: "backspace",
        KeyboardKey.delete: "delete",
    }
    if key in pynput_to_str:
        return pynput_to_str[key]
    # 处理字符按键 (KeyCode 对象)
    if hasattr(key, 'char') and key.char:
        return key.char
    return str(key)


def _translate_pynput_key(key_name):
    """将字符串按键名转换为 pynput Key 对象。"""
    special_map = {
        "shift": KeyboardKey.shift,
        "ctrl": KeyboardKey.ctrl,
        "alt": KeyboardKey.alt,
        "esc": KeyboardKey.esc,
        "escape": KeyboardKey.esc,
        "enter": KeyboardKey.enter,
        "space": KeyboardKey.space,
        "tab": KeyboardKey.tab,
        "caps": KeyboardKey.caps_lock,
        "caps_lock": KeyboardKey.caps_lock,
        "backspace": KeyboardKey.backspace,
        "delete": KeyboardKey.delete,
    }
    if isinstance(key_name, str):
        k = key_name.lower()
        if k in special_map:
            return special_map[k]
        if len(k) == 1:
            return k
    return key_name


def _get_vk_code(key_name: str) -> int:
    """将按键名转换为 Windows 虚拟键码。"""
    import win32con
    special_keys = {
        'esc': win32con.VK_ESCAPE,
        'escape': win32con.VK_ESCAPE,
        'enter': win32con.VK_RETURN,
        'space': win32con.VK_SPACE,
        'tab': win32con.VK_TAB,
        'shift': win32con.VK_SHIFT,
        'ctrl': win32con.VK_CONTROL,
        'alt': win32con.VK_MENU,
    }
    key_lower = key_name.lower()
    if key_lower in special_keys:
        return special_keys[key_lower]
    if len(key_lower) == 1 and key_lower.isalpha():
        return ord(key_lower.upper())
    if len(key_lower) == 1 and key_lower.isdigit():
        return ord(key_lower)
    raise ValueError(f"不支持的按键: {key_name}")
