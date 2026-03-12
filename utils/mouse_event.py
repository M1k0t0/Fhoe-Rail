import ctypes
import time

import cv2
import pyautogui
import win32api
import win32con

from utils.config.config import ConfigurationManager
from utils.img import Img
from utils.log import log
from utils.singleton import SingletonMeta
from utils.window import Window


def _get_cdp_client():
    """延迟初始化 CdpClient 单例，仅在云游戏模式下使用。"""
    from utils.cdp_client import CdpClient
    cfg = ConfigurationManager()
    port = int(cfg.config_file.get("cdp_debug_port", 9222))
    return CdpClient(port=port)


class MouseEvent(metaclass=SingletonMeta):
    def __init__(self):
        self.img = Img()
        self.window = Window()
        self.cfg = ConfigurationManager()

        self.img_search_val_dict = {}  # 图片匹配值
        self.multi_num = 1
        self._is_cloud = self.window.client == "云游戏"
        self._cdp = None  # 延迟初始化

        if self._is_cloud:
            log.info("检测到云游戏模式，将使用 CDP 进行鼠标/键盘输入（支持后台运行）")
        try:
            self.scale = ctypes.windll.user32.GetDpiForWindow(self.window.hwnd) / 96.0
            log.debug(f"scale:{self.scale}")
        except Exception:
            self.scale = 1.0
            log.info(f'DPI获取失败，使用默认比例scale:{self.scale}')

    @property
    def cdp(self):
        """获取 CDP 客户端（惰性初始化）。"""
        if self._cdp is None:
            self._cdp = _get_cdp_client()
        return self._cdp

    def click(self, points, slot=0.0, clicks=1, delay=0.05):
        """
        说明：
            点击指定屏幕坐标
        参数：
            :param points: 坐标
            :param slot: 坐标来源图片匹配值
            :param clicks: 连续点击次数
        """
        x, y = int(points[0]), int(points[1])
        if not slot:
            log.info(f"点击坐标{(x, y)}")
        else:
            log.info(f"点击坐标{(x, y)}，坐标来源图片匹配度{slot:.3f}")
        if clicks > 1:
            log.info(f"将点击 {clicks} 次")
        for _ in range(clicks):
            self.mouse_press(x, y, delay)

    def mouse_press(self, x, y, delay: float = 0.05):
        """
        说明：
            鼠标点击
        参数：
            :param x: 坐标x（CDP模式下为视口坐标，本地模式为屏幕坐标）
            :param y: 坐标y（CDP模式下为视口坐标，本地模式为屏幕坐标）
            :param delay: 鼠标点击与抬起之间的延迟（秒）
        """
        if self._is_cloud:
            # CDP 模式：坐标来自 CDP 截图，已经是视口相对坐标，直接使用
            self.cdp.mouse_click(x, y, delay)
            time.sleep(0.1)
        else:
            win32api.SetCursorPos((x, y))
            time.sleep(0.1)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            time.sleep(delay)
            time.sleep(0.01)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
            time.sleep(0.1)

    def mouse_drag(self, x, y, end_x, end_y, press_time: float = 0):
        """
        说明：
            在窗口内执行鼠标拖拽操作
            
        参数：
            :param x: 起始点x坐标(相对于窗口)
            :param y: 起始点y坐标(相对于窗口)
            :param end_x: 终点x坐标(相对于窗口)
            :param end_y: 终点y坐标(相对于窗口)
            :param press_time: 鼠标拖动到终点后的停留时间(秒)，默认为0
            
        返回：
            None
            
        示例：
            mouse_drag(100, 100, 300, 300)  # 从(100,100)拖拽到(300,300)
            mouse_drag(100, 100, 300, 300, 0.5)  # 拖拽到终点后停留0.5秒
        """
        if self._is_cloud:
            # CDP 模式：坐标直接使用窗口内相对坐标（即 x, y, end_x, end_y 本身）
            # 先点击起点同步光标位置
            self.cdp.mouse_click(x + 2, y + 2, 0.05)
            time.sleep(0.3)

            # 按下开始拖拽
            self.cdp.mouse_down(x, y)
            time.sleep(0.1)

            # 分步拖拽
            steps = 8
            for i in range(1, steps + 1):
                frac = i / steps
                ix = int(x + (end_x - x) * frac)
                iy = int(y + (end_y - y) * frac)
                self.cdp.mouse_move(ix, iy)
                time.sleep(0.05)

            if press_time:
                time.sleep(press_time)
            else:
                time.sleep(0.1)
            self.cdp.mouse_up(end_x, end_y)
            time.sleep(1)
        else:
            left, top, right, bottom = self.window.get_rect()
            start_x = left + x
            start_y = top + y
            target_x = left + end_x
            target_y = top + end_y

            # 先移到起点并点击一次，让云游戏重新定位游戏内光标到该位置
            # Moonlight Web Point-and-Drag 模式下，点击会同步光标位置
            win32api.SetCursorPos((start_x+2, start_y+2)) # 微调坐标，确保触发云游戏的点击事件
            time.sleep(0.1)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            time.sleep(0.1)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
            time.sleep(0.3)

            # 再次确认光标在起点，然后按下开始拖拽
            win32api.SetCursorPos((start_x, start_y))
            time.sleep(0.15)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            time.sleep(0.1)

            # 分步拖拽，避免云游戏网页跟不上
            steps = 8
            for i in range(1, steps + 1):
                frac = i / steps
                ix = int(start_x + (target_x - start_x) * frac)
                iy = int(start_y + (target_y - start_y) * frac)
                win32api.SetCursorPos((ix, iy))
                time.sleep(0.05)

            if press_time:
                time.sleep(press_time)
            else:
                time.sleep(0.1)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
            time.sleep(1)

    def mouse_press_alt(self, x, y, delay: float = 0.4):
        """
        说明：
            按下alt同时鼠标点击指定坐标
        参数：
            :param x:相对坐标x
            :param y:相对坐标y
        """
        if self._is_cloud:
            self.cdp.key_down("alt")
            self.mouse_press(x, y, delay)
            self.cdp.key_up("alt")
        else:
            win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
            self.mouse_press(x, y, delay)
            win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)

    def relative_click(self, points):
        """
        说明：
            点击相对坐标
        参数：
            :param points: 百分比坐标，100为100%
        """
        if self._is_cloud:
            # CDP 模式：直接使用 1920x1080 视口内的百分比坐标
            x = int(1920 / 100 * points[0])
            y = int(1080 / 100 * points[1])
            log.info(f"CDP relative_click viewport ({x}, {y})")
            self.mouse_press_alt(x, y)
        elif self.window.check_window_visibility():
            left, top, right, bottom = self.window.get_rect()
            x, y = int(left + (right - left) / 100 *
                       points[0]), int(top + (bottom - top) / 100 * points[1])
            log.info((x, y))
            self.mouse_press_alt(x, y)

    def click_center(self):
        """
        点击游戏窗口中心位置
        """
        if self._is_cloud:
            # CDP 模式：视口中心 = (960, 540)，但我们点击上一个记录的位置防止视角错误旋转，如果没有记录则点击视口中心
            if self.cdp.last_x and self.cdp.last_y:
                self.mouse_press(self.cdp.last_x, self.cdp.last_y)
            else:
                self.mouse_press(960, 540)
        elif self.window.check_window_visibility():
            left, top, right, bottom = self.window.get_rect()
            x, y = int((left + right) / 2), int((top + bottom) / 2)
            self.mouse_press(x, y)

    def click_target_above_threshold(self, target, threshold, offset, clicks=1, delay=0.05):
        """
        尝试点击匹配度大于阈值的目标图像。
        参数:
            :param target: 目标图像
            :param threshold: 匹配阈值
            :param offset: 左、上、右、下，正值为向右或向下偏移
            :param clicks: 连续点击次数
        返回:
            :return: 是否点击成功
        """
        result = self.img.scan_screenshot(target, offset)
        if result["max_val"] > threshold:
            points = self.img.img_center_point(result, target.shape)
            self.click(points, result['max_val'], clicks, delay)
            return True, result['max_val']
        return False, result['max_val']

    def click_target(self, target_path, threshold, flag=True, timeout=30.0, offset=(0, 0, 0, 0), retry_in_map: bool = True, clicks=1, delay=0.05):
        """
        说明：
            点击指定图片
        参数：
            :param target_path:图片地址
            :param threshold:匹配阈值
            :param flag:True为一定要找到图片
            :param timeout: 最大搜索时间（秒）
            :param offset: 左、上、右、下，正值为向右或向下偏移
            :param retry_in_map: 是否允许地图中重试查找
            :param clicks: 连续点击次数
        返回：
            :return 是否点击成功
        """
        # 定义目标图像与颜色反转后的图像
        original_target = cv2.imread(target_path)
        inverted_target = cv2.bitwise_not(original_target)
        start_time = time.time()
        assigned = False

        while time.time() - start_time < timeout:
            click_it, img_search_val = self.click_target_above_threshold(
                original_target, threshold, offset, clicks, delay)
            if click_it:
                return True
            if time.time() - start_time > 1:  # 如果超过1秒，同时匹配原图像和颜色反转后的图像
                click_it, _ = self.click_target_above_threshold(
                    inverted_target, threshold, offset, clicks, delay)
                if click_it:
                    log.info("阴阳变转")
                    return True

            if not assigned:
                if target_path in self.img_search_val_dict:
                    if self.img_search_val_dict[target_path] > img_search_val and img_search_val < 0.99:
                        self.img_search_val_dict[target_path] = img_search_val
                        assigned = True
                else:
                    if img_search_val < 0.99:
                        self.img_search_val_dict[target_path] = img_search_val
                        assigned = True

            if not flag:  # 是否一定要找到
                return False
            time.sleep(0.5)  # 添加短暂延迟避免性能消耗

        log.info(
            f"查找图片超时 {target_path} ，最相似图片匹配值 {img_search_val}，所需匹配值 {threshold}")
        self.img.search_img_allow_retry = retry_in_map
        return False

    def click_target_with_alt(self, target_path, threshold, flag=True, clicks=1):
        """
        说明：
            按下alt，点击指定图片，释放alt
        参数：
            :param target_path: 图片地址
            :param threshold: 匹配阈值
            :param flag: True为必须找到图片
            :param clicks: 连续点击次数
        改进：
            1. 使用成对的按下/释放标志
            2. 增加异常处理确保ALT释放
            3. 优化延时逻辑
            4. 添加键盘状态恢复机制
        """
        if self._is_cloud:
            try:
                self.cdp.key_down("alt")
                time.sleep(0.15)
                self.click_target(target_path, threshold, flag, clicks=clicks)
            except Exception as e:
                if flag:
                    raise RuntimeError(f"操作执行失败: {str(e)}") from e
            finally:
                self.cdp.key_up("alt")
                time.sleep(0.1)
        else:
            initial_state = win32api.GetKeyState(win32con.VK_MENU)
            log.debug(f"ALT初始状态: {initial_state}")

            try:
                win32api.keybd_event(win32con.VK_MENU, 0,
                                     win32con.KEYEVENTF_EXTENDEDKEY, 0)
                time.sleep(0.15)

                self.click_target(target_path, threshold, flag, clicks=clicks)

            except Exception as e:
                if flag:
                    raise RuntimeError(f"操作执行失败: {str(e)}") from e
            finally:
                current_state = win32api.GetKeyState(win32con.VK_MENU)
                log.debug(f"释放前状态: {current_state}, 正在执行强制释放")
                if win32api.GetKeyState(win32con.VK_MENU) != initial_state:
                    win32api.keybd_event(
                        win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP | win32con.KEYEVENTF_EXTENDEDKEY, 0)
                time.sleep(0.1)

    def mouse_move(self, x, fine=1, align=False):
        """
        说明：
            视角转动x度
        参数：
            :param x: 转动角度
            :param fine: 精细度
            :param align: 是否对齐
        """
        if x > 30 // fine:
            y = 30 // fine
        elif x < -30 // fine:
            y = -30 // fine
        else:
            y = x
        if align:
            dx = int(16.5 * y * 1 * self.scale)
            log.debug(f"dx1:{dx}")
        else:
            self.multi_num = self.get_multi_num()
            dx = int(16.5 * y * self.multi_num * self.scale)
            log.debug(f"dx2:{dx}")
        if self._is_cloud:
            # CDP 模式：通过 mouseMoved 模拟视角移动
            # 使用相对位移：以当前记录位置为基准偏移
            cur_x = self.cdp.last_x
            cur_y = self.cdp.last_y
            self.cdp.mouse_move(cur_x + dx, cur_y)
        else:
            win32api.mouse_event(win32con.MOUSEEVENTF_MOVE, dx, 0)  # 进行视角移动
        time.sleep(0.2 * fine)
        if x != y:
            self.mouse_move(x - y, fine, align)

    def get_multi_num(self) -> float:
        """获取视角旋转偏移参数"""
        self.multi_num = float(self.cfg.config_file.get("angle", 1))
        return self.multi_num
