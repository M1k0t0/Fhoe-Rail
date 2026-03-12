"""
轻量级 Chrome DevTools Protocol (CDP) 客户端。
通过 WebSocket 连接到 Chrome 的 --remote-debugging-port，
发送 Input.dispatchMouseEvent / Input.dispatchKeyEvent 等命令，
使云游戏窗口在后台时也能正常接收鼠标和键盘输入。
"""

import json
import threading
import time
import urllib.request

import websocket

from utils.log import log
from utils.singleton import SingletonMeta


class CdpClient(metaclass=SingletonMeta):
    """
    CDP 客户端单例。

    使用方法::

        client = CdpClient(port=9222)
        client.send("Input.dispatchMouseEvent", {
            "type": "mousePressed", "x": 100, "y": 200,
            "button": "left", "buttons": 1, "clickCount": 1,
            "pointerType": "mouse"
        })
    """

    # ────────── 按键映射表 ──────────
    SPECIAL_KEY_MAP = {
        "esc": {"key": "Escape", "code": "Escape", "vk": 27},
        "escape": {"key": "Escape", "code": "Escape", "vk": 27},
        "enter": {"key": "Enter", "code": "Enter", "vk": 13},
        "space": {"key": " ", "code": "Space", "vk": 32},
        "tab": {"key": "Tab", "code": "Tab", "vk": 9},
        "backspace": {"key": "Backspace", "code": "Backspace", "vk": 8},
        "delete": {"key": "Delete", "code": "Delete", "vk": 46},
        "arrowup": {"key": "ArrowUp", "code": "ArrowUp", "vk": 38},
        "arrowdown": {"key": "ArrowDown", "code": "ArrowDown", "vk": 40},
        "arrowleft": {"key": "ArrowLeft", "code": "ArrowLeft", "vk": 37},
        "arrowright": {"key": "ArrowRight", "code": "ArrowRight", "vk": 39},
        "shift": {"key": "Shift", "code": "ShiftLeft", "vk": 16},
        "ctrl": {"key": "Control", "code": "ControlLeft", "vk": 17},
        "alt": {"key": "Alt", "code": "AltLeft", "vk": 18},
        "caps": {"key": "CapsLock", "code": "CapsLock", "vk": 20},
    }

    # F1-F12
    for _i in range(1, 13):
        SPECIAL_KEY_MAP[f"f{_i}"] = {
            "key": f"F{_i}",
            "code": f"F{_i}",
            "vk": 111 + _i,
        }

    CHAR_KEY_MAP = {
        # a-z
        **{
            chr(i): {
                "key": chr(i),
                "code": f"Key{chr(i).upper()}",
                "vk": ord(chr(i).upper()),
            }
            for i in range(97, 123)
        },
        # 0-9
        **{
            str(i): {
                "key": str(i),
                "code": f"Digit{i}",
                "vk": 48 + i,
            }
            for i in range(10)
        },
    }

    def __init__(self, port: int = 9222):
        self.port = port
        self._ws = None
        self._msg_id = 0
        self._lock = threading.Lock()
        self._connected = False
        self.last_x = 0
        self.last_y = 0
        self._connect()

    # ──────────────── 连接管理 ────────────────

    def _get_ws_url(self) -> str:
        """通过 HTTP 查询 Chrome 的 /json 端点，获取第一个页面的 WebSocket 调试地址。"""
        url = f"http://127.0.0.1:{self.port}/json"
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                pages = json.loads(resp.read().decode())
        except Exception as e:
            raise ConnectionError(f"无法连接到 Chrome DevTools (port={self.port}): {e}")

        if not pages:
            raise ConnectionError("Chrome DevTools 没有可用的页面")

        # 优先选择 type==page 的条目
        for page in pages:
            if page.get("type") == "page" and "webSocketDebuggerUrl" in page:
                return page["webSocketDebuggerUrl"]

        # 退而求其次
        for page in pages:
            if "webSocketDebuggerUrl" in page:
                return page["webSocketDebuggerUrl"]

        raise ConnectionError("Chrome DevTools 未返回 webSocketDebuggerUrl")

    def _connect(self):
        """建立 WebSocket 连接。"""
        try:
            ws_url = self._get_ws_url()
            log.info(f"CDP 正在连接: {ws_url}")
            self._ws = websocket.create_connection(
                ws_url, timeout=10,
                origin=f"http://127.0.0.1:{self.port}"
            )
            self._connected = True
            log.info("CDP 连接成功")
        except Exception as e:
            log.error(f"CDP 连接失败: {e}")
            self._connected = False

    def _ensure_connected(self):
        """确保 WebSocket 连接可用，断线则自动重连。"""
        if not self._connected or self._ws is None:
            self._connect()
        if not self._connected:
            raise ConnectionError("CDP 未连接")

    def close(self):
        """关闭 WebSocket 连接。"""
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
            self._ws = None
            self._connected = False

    # ──────────────── 底层发送 ────────────────

    def send(self, method: str, params: dict = None) -> dict:
        """
        发送 CDP 命令并等待返回。

        :param method: CDP 方法名，例如 ``"Input.dispatchMouseEvent"``
        :param params: 参数字典
        :return: CDP 响应
        """
        with self._lock:
            self._ensure_connected()
            self._msg_id += 1
            msg = {"id": self._msg_id, "method": method, "params": params or {}}
            try:
                self._ws.send(json.dumps(msg))
                # 读取响应（简单实现：仅等待对应 id 的回复）
                while True:
                    raw = self._ws.recv()
                    resp = json.loads(raw)
                    if resp.get("id") == self._msg_id:
                        if "error" in resp:
                            log.error(f"CDP 错误: {resp['error']}")
                        return resp
            except Exception as e:
                log.error(f"CDP 发送失败: {e}")
                self._connected = False
                raise

    # ──────────────── 鼠标操作 ────────────────

    def mouse_move(self, x: int, y: int):
        """
        移动鼠标到 (x, y)。
        Moonlight Web Point-and-Drag 模式下需要 buttons=1。
        """
        self.last_x, self.last_y = x, y
        try:
            self.send("Input.dispatchMouseEvent", {
                "type": "mouseMoved",
                "x": x, "y": y,
                "buttons": 1,
                "pointerType": "mouse",
            })
            log.debug(f"CDP 鼠标移动 ({x}, {y})")
        except Exception as e:
            log.error(f"CDP 鼠标移动出错: {e}")

    def mouse_down(self, x: int, y: int):
        """在 (x, y) 按下鼠标左键。"""
        self.last_x, self.last_y = x, y
        try:
            self.send("Input.dispatchMouseEvent", {
                "type": "mousePressed",
                "button": "left",
                "buttons": 1,
                "x": x, "y": y,
                "clickCount": 1,
                "pointerType": "mouse",
            })
            log.debug(f"CDP 鼠标按下 ({x}, {y})")
        except Exception as e:
            log.error(f"CDP 鼠标按下出错: {e}")

    def mouse_up(self, x: int = None, y: int = None):
        """释放鼠标左键。"""
        if x is not None:
            self.last_x = x
        if y is not None:
            self.last_y = y
        try:
            self.send("Input.dispatchMouseEvent", {
                "type": "mouseReleased",
                "button": "left",
                "buttons": 0,
                "x": self.last_x, "y": self.last_y,
                "clickCount": 1,
                "pointerType": "mouse",
            })
            log.debug(f"CDP 鼠标释放 ({self.last_x}, {self.last_y})")
        except Exception as e:
            log.error(f"CDP 鼠标释放出错: {e}")

    def mouse_click(self, x: int, y: int, delay: float = 0.05):
        """在 (x, y) 点击一次。"""
        self.mouse_down(x, y)
        time.sleep(delay)
        self.mouse_up(x, y)
        log.debug(f"CDP 鼠标点击 ({x}, {y})")

    def mouse_scroll(self, delta_y: float, x: int = None, y: int = None):
        """滚动鼠标滚轮。"""
        if x is None:
            x = self.last_x
        if y is None:
            y = self.last_y
        try:
            self.send("Input.dispatchMouseEvent", {
                "type": "mouseWheel",
                "x": x, "y": y,
                "deltaX": 0,
                "deltaY": delta_y,
                "pointerType": "mouse",
            })
            log.debug(f"CDP 鼠标滚轮 deltaY={delta_y}")
        except Exception as e:
            log.error(f"CDP 鼠标滚轮出错: {e}")

    # ──────────────── 键盘操作 ────────────────

    def _resolve_key(self, key_name: str) -> dict:
        """将按键名解析为 CDP 所需的 key/code/vk 字典。"""
        k = key_name.lower()
        if k in self.SPECIAL_KEY_MAP:
            return self.SPECIAL_KEY_MAP[k]
        if k in self.CHAR_KEY_MAP:
            return self.CHAR_KEY_MAP[k]
        log.error(f"CDP 未知按键: {key_name}")
        return None

    def key_down(self, key_name: str):
        """按下按键（不释放）。"""
        info = self._resolve_key(key_name)
        if not info:
            return
        self._focus()
        try:
            self.send("Input.dispatchKeyEvent", {
                "type": "keyDown",
                "key": info["key"],
                "code": info["code"],
                "windowsVirtualKeyCode": info["vk"],
                "nativeVirtualKeyCode": info["vk"],
                "modifiers": 0,
                "text": "",
            })
            log.debug(f"CDP 按键按下: {key_name}")
        except Exception as e:
            log.error(f"CDP 按键按下出错: {e}")

    def key_up(self, key_name: str):
        """释放按键。"""
        info = self._resolve_key(key_name)
        if not info:
            return
        try:
            self.send("Input.dispatchKeyEvent", {
                "type": "keyUp",
                "key": info["key"],
                "code": info["code"],
                "windowsVirtualKeyCode": info["vk"],
                "nativeVirtualKeyCode": info["vk"],
                "modifiers": 0,
                "text": "",
            })
            log.debug(f"CDP 按键释放: {key_name}")
        except Exception as e:
            log.error(f"CDP 按键释放出错: {e}")

    def press_key(self, key_name: str, hold_time: float = 0.05):
        """按下按键并在 hold_time 秒后释放。"""
        self.key_down(key_name)
        time.sleep(hold_time)
        self.key_up(key_name)

    def _focus(self):
        """通过模拟一次 mouseMoved 确保浏览器内的焦点，防止键盘事件失效。"""
        try:
            self.send("Input.dispatchMouseEvent", {
                "type": "mouseMoved",
                "x": self.last_x, "y": self.last_y,
                "buttons": 1,
                "pointerType": "mouse",
            })
        except Exception:
            pass

    # ──────────────── 截图 ────────────────

    def capture_screenshot(self) -> bytes:
        """
        通过 CDP Page.captureScreenshot 获取浏览器视口截图。
        返回 PNG 图片的原始字节数据。
        坐标系为视口相对坐标 (0,0) = 左上角，完全不依赖窗口位置。
        """
        import base64
        resp = self.send("Page.captureScreenshot", {"format": "png"})
        if "result" in resp and "data" in resp["result"]:
            return base64.b64decode(resp["result"]["data"])
        raise RuntimeError(f"CDP 截图失败: {resp}")
