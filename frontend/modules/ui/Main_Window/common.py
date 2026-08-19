# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""Shared imports for the Main_Window package."""

import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox, filedialog
from tkinterdnd2 import DND_FILES, TkinterDnD
from PIL import Image, ImageTk
import threading
import queue
import os
import sys
import pyperclip
import subprocess
import platform
import time
from collections import deque
from contextlib import nullcontext
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor
from modules.ui.safe_scrollable_frame import SafeScrollableFrame

from modules import config
from modules import api
from modules.widgets import ScrollableFrame, CollapsibleGroupFrame, ServiceSettingsView
from modules.gallery_manager import GalleryManager
from modules.gallery_service import GalleryRecord, gallery_url_for_service
from modules.settings_manager import SettingsManager
from modules.template_manager import TemplateManager, TemplateEditor
from modules.upload_manager import UploadManager
from modules.utils import ContextUtils
from modules import viper_api
from modules import file_handler
from modules.dnd import DragDropMixin
from modules.credentials_manager import CredentialsManager
from modules.auto_poster import AutoPoster
from modules.plugin_manager import PluginManager
from loguru import logger

__all__ = [
    "Any",
    "AutoPoster",
    "CollapsibleGroupFrame",
    "ContextUtils",
    "CredentialsManager",
    "DND_FILES",
    "Dict",
    "DragDropMixin",
    "GalleryManager",
    "GalleryRecord",
    "Image",
    "ImageTk",
    "List",
    "Optional",
    "PluginManager",
    "SafeScrollableFrame",
    "ScrollableFrame",
    "ServiceSettingsView",
    "SettingsManager",
    "TemplateEditor",
    "TemplateManager",
    "ThreadPoolExecutor",
    "TkinterDnD",
    "Tuple",
    "UploadManager",
    "api",
    "config",
    "ctk",
    "datetime",
    "deque",
    "file_handler",
    "filedialog",
    "gallery_url_for_service",
    "logger",
    "messagebox",
    "nullcontext",
    "os",
    "platform",
    "pyperclip",
    "queue",
    "subprocess",
    "sys",
    "threading",
    "time",
    "tk",
    "viper_api",
]
