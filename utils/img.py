import ctypes
import time

import cv2
import numpy as np
from PIL import Image, ImageGrab
import win32con
import win32gui
import win32ui

from utils.log import log
from utils.window import Window

# DPI awareness context for accurate screen coordinates on scaled displays
_DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)
try:
    ctypes.windll.user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
    ctypes.windll.user32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    _HAS_THREAD_DPI_API = True
except (OSError, AttributeError):
    _HAS_THREAD_DPI_API = False


class Img:
    def __init__(self, image_paths: dict = None):
        self.window = Window()
        self.temp_screenshot = (0, 0, 0, 0, 0)  # 初始化临时截图
        self.search_img_allow_retry = False  # 初始化查找图片允许重试为不允许

        if image_paths is None:
            self.image_paths = {
                "main_ui": "./picture/finish_fighting.png",
                "doubt_ui": "./picture/doubt.png",
                "warn_ui": "./picture/warn.png",
                "finish2_ui": "./picture/finish_fighting2.png",
                "finish2_1_ui": "./picture/finish_fighting2_1.png",
                "finish2_2_ui": "./picture/finish_fighting2_2.png",
                "finish3_ui": "./picture/finish_fighting3.png",
                "finish4_ui": "./picture/finish_fighting4.png",
                "finish5_ui": "./picture/finish_fighting5.png",
                "battle_esc_check": "./picture/battle_esc_check.png",
                "switch_run": "./picture/switch_run.png",
            }
        else:
            self.image_paths = image_paths

        # 加载所有图片
        self.load_images()

    @staticmethod
    def get_img(img_path):
        """
        获取图片
        :param img_path: 图片路径
        :return: 图片数据（numpy 数组），如果加载失败返回 None
        """
        try:
            img = cv2.imread(img_path)
            if img is None:
                raise FileNotFoundError(f"图片加载失败，路径不存在或文件损坏: {img_path}")
            return img
        except Exception as e:
            log.error(f"加载图片时发生错误: {e}")
            return None

    def load_images(self):
        """加载所有图片"""
        for name, path in self.image_paths.items():
            img = self.get_img(path)
            if img is not None:
                setattr(self, name, img)
            else:
                log.warning(f"警告: 图片 {name} 加载失败，路径为 {path}")

    def cal_screenshot(self):
        """
        计算窗口截图范围
        """
        left, top, right, bottom = self.window.get_rect()
        # 计算初始边框
        width = right - left
        height = bottom - top
        other_border = (width - 1920) // 2
        up_border = height - 1080 - other_border
        # 计算窗口截图范围
        screenshot_left = left + other_border
        screenshot_top = top + up_border
        screenshot_right = right - other_border
        screenshot_bottom = bottom - other_border

        return screenshot_left, screenshot_top, screenshot_right, screenshot_bottom

    @staticmethod
    def match_screenshot(screenshot, prepared, left, top):
        """
        说明：
            比对screenshot与prepared，返回匹配值与位置
        参数：
            :param screenshot:屏幕截图图片
            :param prepared:比对图片
            :param left:截图左侧坐标，用于计算真实位置
            :param top:截图上方坐标，用于计算真实位置
        """
        result = cv2.matchTemplate(screenshot, prepared, cv2.TM_CCORR_NORMED)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
        return {
            "screenshot": screenshot,
            "min_val": min_val,
            "max_val": max_val,
            "min_loc": (min_loc[0] + left, min_loc[1] + top),
            "max_loc": (max_loc[0] + left, max_loc[1] + top),
        }

    def have_screenshot(self, prepared, offset=(0, 0, 0, 0), threshold=0.90):
        """
        验证屏幕截图中是否存在预设的图片之一。

        参数:
            prepared (list): 需要匹配的图片列表。
            offset (tuple): 在搜索时屏幕截图的偏移量，默认为 (0, 0, 0, 0)。
            threshold (float): 确定匹配成功的最小阈值，默认为 0.90。

        返回:
            bool: 如果找到至少一张符合阈值的图片，则返回 True，否则返回 False。
        """
        for image in prepared:
            result_dict = self.scan_screenshot(image, offset)
            max_val = result_dict['max_val']
            if max_val > threshold:
                log.info(f'找到图片，匹配值：{max_val:.3f}')
                return True
            else:
                log.debug(f'图片匹配值未达到阈值，当前值：{max_val:.3f}')
        return False

    def take_screenshot(self, offset=(0, 0, 0, 0), max_retries=50, retry_interval=2):
        """
        说明：
            获取游戏窗口的屏幕截图
        参数：
            :param offset: 左、上、右、下，正值为向右或向下偏移
            :param max_retries: 最大重试次数
            :param retry_interval: 重试间隔（秒）
        """
        # 设置线程级 DPI 感知，确保坐标使用物理像素
        old_dpi_context = None
        if _HAS_THREAD_DPI_API:
            try:
                old_dpi_context = ctypes.windll.user32.SetThreadDpiAwarenessContext(
                    _DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
            except (OSError, AttributeError):
                pass

        try:
            return self._take_screenshot_impl(offset, max_retries, retry_interval)
        finally:
            if old_dpi_context is not None:
                try:
                    ctypes.windll.user32.SetThreadDpiAwarenessContext(
                        ctypes.c_void_p(old_dpi_context))
                except (OSError, AttributeError):
                    pass

    def _capture_printwindow(self):
        """
        使用 PrintWindow API 截取窗口客户区内容。
        可以捕获硬件加速渲染的内容（如云游戏、DirectX 窗口）。
        返回：(PIL.Image, client_screen_x, client_screen_y) 或 None
        """
        hwnd = self.window.hwnd
        if not hwnd:
            return None

        try:
            # 获取客户区大小和屏幕位置
            left_c, top_c, right_c, bottom_c = win32gui.GetClientRect(hwnd)
            client_width = right_c - left_c
            client_height = bottom_c - top_c
            if client_width <= 0 or client_height <= 0:
                return None

            pt = win32gui.ClientToScreen(hwnd, (0, 0))
            client_screen_x, client_screen_y = pt

            # 创建设备上下文和位图
            hwndDC = win32gui.GetWindowDC(hwnd)
            mfcDC = win32ui.CreateDCFromHandle(hwndDC)
            saveDC = mfcDC.CreateCompatibleDC()
            saveBitMap = win32ui.CreateBitmap()
            saveBitMap.CreateCompatibleBitmap(mfcDC, client_width, client_height)
            saveDC.SelectObject(saveBitMap)

            # PrintWindow flag 3 = PW_RENDERFULLCONTENT(2) | PW_CLIENTONLY(1)
            # PW_CLIENTONLY: 只捕获客户区（不含标题栏和边框）
            # PW_RENDERFULLCONTENT: 强制完整渲染（支持硬件加速内容）
            result = ctypes.windll.user32.PrintWindow(hwnd, saveDC.GetSafeHdc(), 3)

            if result != 1:
                # 清理资源
                win32gui.DeleteObject(saveBitMap.GetHandle())
                saveDC.DeleteDC()
                mfcDC.DeleteDC()
                win32gui.ReleaseDC(hwnd, hwndDC)
                return None

            # 转换为 PIL Image
            bmpinfo = saveBitMap.GetInfo()
            bmpstr = saveBitMap.GetBitmapBits(True)
            img = Image.frombuffer(
                'RGB',
                (bmpinfo['bmWidth'], bmpinfo['bmHeight']),
                bmpstr, 'raw', 'BGRX', 0, 1
            )

            # 清理资源
            win32gui.DeleteObject(saveBitMap.GetHandle())
            saveDC.DeleteDC()
            mfcDC.DeleteDC()
            win32gui.ReleaseDC(hwnd, hwndDC)

            return img, client_screen_x, client_screen_y

        except Exception as e:
            log.warning(f"PrintWindow 截图失败: {e}")
            return None

    def _take_screenshot_impl(self, offset, max_retries, retry_interval):
        """take_screenshot 的实际实现（在正确的 DPI 上下文中调用）"""
        if not self.window.check_window_visibility():
            raise RuntimeError("窗口不可见")

        retries = 0
        while retries <= max_retries:
            try:
                # 优先使用 PrintWindow（支持硬件加速渲染的窗口）
                pw_result = self._capture_printwindow()
                if pw_result is not None:
                    picture, client_x, client_y = pw_result
                    client_width, client_height = picture.size

                    # 计算游戏内容在客户区内的边框偏移
                    border_x = (client_width - 1920) // 2
                    border_top = client_height - 1080 - border_x

                    # 游戏内容区域（客户区内坐标）
                    game_left = max(0, border_x)
                    game_top = max(0, border_top)
                    game_right = min(client_width, client_width - border_x)
                    game_bottom = min(client_height, client_height - border_x)

                    # 应用用户指定的偏移
                    crop_left = game_left + offset[0]
                    crop_top = game_top + offset[1]
                    crop_right = game_right + offset[2]
                    crop_bottom = game_bottom + offset[3]

                    # 确保裁剪区域有效
                    crop_left = max(0, crop_left)
                    crop_top = max(0, crop_top)
                    crop_right = min(client_width, crop_right)
                    crop_bottom = min(client_height, crop_bottom)

                    if crop_left >= crop_right or crop_top >= crop_bottom:
                        log.info(f'截图区域无效，偏移值错误({offset[0]},{offset[1]},{offset[2]},{offset[3]})，将使用完整客户区')
                        crop_left, crop_top = game_left, game_top
                        crop_right, crop_bottom = game_right, game_bottom

                    cropped = picture.crop((crop_left, crop_top, crop_right, crop_bottom))
                    # 保存截图到本地，测试用
                    cropped.save("test.png")
                    screenshot = np.array(cropped)
                    screenshot = cv2.cvtColor(screenshot, cv2.COLOR_RGB2BGR)

                    # 转换为屏幕坐标（用于鼠标点击定位）
                    screen_left = client_x + crop_left
                    screen_top = client_y + crop_top
                    screen_right = client_x + crop_right
                    screen_bottom = client_y + crop_bottom

                    self.temp_screenshot = (screenshot, screen_left, screen_top, screen_right, screen_bottom)
                    return screenshot, screen_left, screen_top, screen_right, screen_bottom

                # PrintWindow 失败时回退到 ImageGrab
                log.info("PrintWindow 不可用，回退到 ImageGrab")
                return self._take_screenshot_imagegrab(offset)

            except Exception as e:
                log.info(f"截图失败，原因: {str(e)}，等待 {retry_interval} 秒后重试")
                retries += 1
                time.sleep(retry_interval)

        raise RuntimeError(f"截图尝试失败，已达到最大重试次数 {max_retries} 次）")

    def _take_screenshot_imagegrab(self, offset):
        """使用 ImageGrab 截图（回退方案），基于客户区坐标"""
        hwnd = self.window.hwnd
        if not hwnd:
            raise RuntimeError("窗口句柄无效")

        # 直接使用客户区坐标，避免 _get_fullscreen_rect 返回显示器坐标导致的偏差
        left_c, top_c, right_c, bottom_c = win32gui.GetClientRect(hwnd)
        client_width = right_c - left_c
        client_height = bottom_c - top_c
        pt = win32gui.ClientToScreen(hwnd, (0, 0))
        client_screen_x, client_screen_y = pt

        # 截取整个客户区
        grab_left = client_screen_x
        grab_top = client_screen_y
        grab_right = client_screen_x + client_width
        grab_bottom = client_screen_y + client_height

        picture = ImageGrab.grab(
            (grab_left, grab_top, grab_right, grab_bottom), all_screens=True)

        # 缩放到 1920x1080 以匹配模板图片（处理客户区尺寸不完全为1920x1080的情况）
        if picture.size != (1920, 1080):
            log.info(f"客户区大小 {picture.size}，缩放到 1920x1080")
            picture = picture.resize((1920, 1080), Image.LANCZOS)

        # 应用偏移裁剪
        # 基准是 1920x1080 的图像
        crop_left = max(0, offset[0])
        crop_top = max(0, offset[1])
        crop_right = min(1920, 1920 + offset[2])
        crop_bottom = min(1080, 1080 + offset[3])

        if crop_left >= crop_right or crop_top >= crop_bottom:
            log.info(f'截图区域无效，偏移值错误({offset[0]},{offset[1]},{offset[2]},{offset[3]})，将使用完整截图')
            crop_left, crop_top, crop_right, crop_bottom = 0, 0, 1920, 1080

        if (crop_left, crop_top, crop_right, crop_bottom) != (0, 0, 1920, 1080):
            picture = picture.crop((crop_left, crop_top, crop_right, crop_bottom))

        picture.save("test.png")
        screenshot = np.array(picture)
        screenshot = cv2.cvtColor(screenshot, cv2.COLOR_BGR2RGB)

        # 计算屏幕坐标（用于鼠标点击定位）
        # 从 1920x1080 坐标映射回实际屏幕坐标
        scale_x = client_width / 1920
        scale_y = client_height / 1080
        screen_left = int(client_screen_x + crop_left * scale_x)
        screen_top = int(client_screen_y + crop_top * scale_y)
        screen_right = int(client_screen_x + crop_right * scale_x)
        screen_bottom = int(client_screen_y + crop_bottom * scale_y)

        self.temp_screenshot = (screenshot, screen_left, screen_top, screen_right, screen_bottom)
        return screenshot, screen_left, screen_top, screen_right, screen_bottom

    def scan_screenshot(self, prepared, offset=(0, 0, 0, 0)) -> dict:
        """
        说明：
            比对图片
        参数：
            :param prepared: 比对图片地址
            :param offset: 左、上、右、下，正值为向右或向下偏移
        """
        screenshot, left, top, right, bottom = self.take_screenshot(
            offset=offset)

        return Img.match_screenshot(screenshot, prepared, left, top)

    def scan_temp_screenshot(self, prepared):
        """
        说明：
            使用临时截图数据进行扫描匹配
        参数：
            :param prepared: 比对图片地址
        """
        if not self.temp_screenshot:
            self.take_screenshot()

        try:
            screenshot, left, top, right, bottom = self.temp_screenshot
        except (TypeError, ValueError) as e:
            raise ValueError(f"self.temp_screenshot 数据格式错误: {e}") from e
        return Img.match_screenshot(screenshot, prepared, left, top)

    @staticmethod
    def img_center_point(result, shape) -> tuple:
        """
        计算匹配到的图片中心位置
        """
        mat_top, mat_left = result["max_loc"]
        prepared_height, prepared_width, prepared_channels = shape

        x = int((mat_top + mat_top + prepared_width) / 2)
        y = int((mat_left + mat_left + prepared_height) / 2)

        return x, y

    def img_trans_bitwise(self, target_path, offset=(0, 0, 0, 0)):
        """
        颜色反转
        """
        original_target = cv2.imread(target_path)
        inverted_target = cv2.bitwise_not(original_target)
        result = self.scan_screenshot(inverted_target, offset)
        return inverted_target, result

    def img_bitwise_check(self, target_path: str, offset: tuple = (0, 0, 0, 0)):
        """
        比对颜色反转
        """
        retry = 0
        while retry < 5:
            original_target = cv2.imread(target_path)
            target,  result_inverted = self.img_trans_bitwise(
                target_path, offset)
            result_original = self.scan_screenshot(original_target, offset)
            log.info(
                f"颜色反转后的匹配值：{result_inverted['max_val']:.3f}，反转前匹配值：{result_original['max_val']:.3f}")
            if round(result_original['max_val'], 3) == 0.0 or round(result_inverted['max_val'], 3) == 0.0:
                retry += 1
                time.sleep(0.5)
            else:
                break
        else:
            log.info("超过重试次数，强制认为原图正确")
            return True

        if result_original["max_val"] > result_inverted["max_val"]:
            return True
        else:
            return False

    def on_main_interface(self, check_list=None, timeout=60.0, threshold=0.9, offset=(0, 0, 0, 0), allow_log=True):
        """
        说明：
            检测主页面
        参数：
            :param check_list:检测图片列表，默认检测左上角地图的灯泡，遍历检测
            :param timeout:超时时间（秒），超时后返回False
            :param threshold:识别阈值，默认0.9
        返回：
            是否在主界面
        """
        if check_list is None:
            check_list = [self.main_ui]
            offset = (0, 0, -1630, -800)
        interface_desc = '游戏主界面，非战斗/传送/黑屏状态'

        return self.on_interface(check_list=check_list, timeout=timeout, interface_desc=interface_desc, threshold=threshold, offset=offset, allow_log=allow_log)

    def on_interface(self, check_list=None, timeout=60.0, interface_desc='', threshold=0.9, offset=(0, 0, 0, 0), allow_log=True):
        """
        说明：
            检测check_list中的图片是否在某个页面
        参数：
            :param check_list:检测图片列表，默认为检测[self.main_ui]主界面左上角灯泡
            :param timeout:超时时间（秒），超时后返回False
            :param interface_desc:界面名称或说明，用于日志输出
        返回：
            是否在check_list存在的界面
        """
        if check_list is None:
            check_list = [self.main_ui]

        start_time = time.time()
        temp_max_val = []

        while True:
            for index, img in enumerate(check_list):
                result = self.scan_screenshot(img, offset=offset)
                if result["max_val"] > threshold:
                    if allow_log:
                        log.info(
                            f"检测到{interface_desc}，耗时 {(time.time() - start_time):.1f} 秒")
                        log.info(
                            f"检测图片序号为{index}，匹配度{result['max_val']:.3f}，匹配位置为{result['max_loc']}")
                    return True
                else:
                    temp_max_val.append(result['max_val'])
                    time.sleep(0.2)

            if time.time() - start_time >= timeout:
                if allow_log:
                    log.info(
                        f"在 {timeout} 秒 的时间内未检测到{interface_desc}，相似图片最高匹配值{max(temp_max_val):.3f}")
                return False

    def image_rotate(self, src, rotate=0):
        """
        图像旋转（中心旋转）
        参数：
            :param src: 源图像
            :param rotate: 旋转角度
        """
        h, w, _ = src.shape
        m = self.handle_rotate_val(w // 2, h // 2, rotate)
        # M = cv2.getRotationMatrix2D((w // 2, h // 2), rotate, 1.0)
        img = cv2.warpAffine(src, m, (w, h), flags=cv2.INTER_LINEAR)
        return img

    def handle_rotate_val(self, x, y, rotate):
        """
        计算旋转变换矩阵
        """
        cos_val = np.cos(np.deg2rad(rotate))
        sin_val = np.sin(np.deg2rad(rotate))
        return np.float32(
            [
                [cos_val, sin_val, x * (1 - cos_val) - y * sin_val],
                [-sin_val, cos_val, x * sin_val + y * (1 - cos_val)],
            ]
        )
