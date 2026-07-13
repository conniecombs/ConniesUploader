import threading

from loguru import logger
from PIL import Image, ImageDraw

try:
    import pystray
except ModuleNotFoundError:
    pystray = None


class SystemTrayManager:
    def __init__(self, main_window):
        self.main_window = main_window
        self.icon = None
        self._setup_icon()

    def _create_image(self):
        image = Image.new("RGB", (64, 64), color=(30, 30, 30))
        drawer = ImageDraw.Draw(image)
        drawer.rectangle((16, 16, 48, 48), fill=(60, 180, 75))
        return image

    def _setup_icon(self):
        if pystray is None:
            logger.warning("System tray disabled: pystray is not installed.")
            return

        try:
            image = self._create_image()
            menu = pystray.Menu(
                pystray.MenuItem("Show App", self.show_window, default=True),
                pystray.MenuItem("Scheduled Posts", self.show_scheduled_posts),
                pystray.MenuItem("Quit", self.quit_app),
            )
            self.icon = pystray.Icon(
                "ConniesUploader",
                image,
                "Connie's Uploader",
                menu,
            )
        except Exception as exc:
            logger.error(f"Failed to set up system tray icon: {exc}")

    def show_window(self, icon, item):
        self.main_window.after(0, self._restore_window)

    def _restore_window(self):
        self.main_window.deiconify()
        self.main_window.lift()
        self.main_window.focus_force()

    def show_scheduled_posts(self, icon, item):
        self.main_window.after(0, self._open_scheduled_posts)

    def _open_scheduled_posts(self):
        self._restore_window()
        self.main_window.open_scheduled_posts()

    def quit_app(self, icon, item):
        self.main_window.after(0, self.main_window.graceful_shutdown)

    def start(self):
        if self.icon:
            threading.Thread(target=self.icon.run, daemon=True).start()

    def stop(self):
        if self.icon:
            self.icon.stop()
