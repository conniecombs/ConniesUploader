"""Connie's Uploader Ultimate - Main Entry Point

Refactored lightweight entry point that delegates to modular UI components.
Previously a monolithic 1,078-line file, now properly organized.
"""

import customtkinter as ctk
import signal
import sys
import os
from loguru import logger
from modules.ui import UploaderApp


def main():
    """Main entry point for the application."""
    # Fix tkinterdnd2 library path for PyInstaller frozen builds
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        # Point to the bundled tkdnd folder inside _MEIPASS
        tkdnd_path = os.path.join(sys._MEIPASS, 'tkinterdnd2', 'tkdnd')
        if os.path.exists(tkdnd_path):
            os.environ['TKDND_LIBRARY'] = tkdnd_path

    # Set appearance and theme before creating app
    ctk.set_appearance_mode("System")
    ctk.set_default_color_theme("blue")

    # Create and run the application
    app = UploaderApp()

    # Set up signal handlers for graceful shutdown
    def signal_handler(sig, frame):
        """Handle SIGINT (Ctrl+C) and SIGTERM signals."""
        logger.info("Received shutdown signal, cleaning up...")
        app.graceful_shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    app.mainloop()


if __name__ == "__main__":
    main()
