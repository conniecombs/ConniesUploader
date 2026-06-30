# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""Main application class assembled from focused Main_Window mixins."""

from .common import (  # noqa: F401
    DND_FILES,
    DragDropMixin,
    Image,
    ImageTk,
    TkinterDnD,
    ctk,
    config,
    logger,
    os,
    queue,
    sys,
    tk,
    threading,
    time,
    ThreadPoolExecutor,
    UploadManager,
    SettingsManager,
    TemplateManager,
    CredentialsManager,
    AutoPoster,
    viper_api,
)
from .cover_helpers import CoverHelpersMixin
from .diagnostics import DiagnosticsMixin
from .file_queue import FileQueueMixin
from .gallery_actions import GalleryActionsMixin
from .layout import LayoutMixin
from .menu_actions import MenuActionsMixin
from .posting import PostingMixin
from .runtime import RuntimeMixin
from .settings import SettingsMixin
from .upload_checks import UploadChecksMixin


class UploaderApp(
    MenuActionsMixin,
    GalleryActionsMixin,
    LayoutMixin,
    SettingsMixin,
    FileQueueMixin,
    UploadChecksMixin,
    CoverHelpersMixin,
    PostingMixin,
    RuntimeMixin,
    DiagnosticsMixin,
    ctk.CTk,
    TkinterDnD.DnDWrapper,
    DragDropMixin,
):
    def __init__(self) -> None:
        """Initialize the uploader application."""
        super().__init__()
        self.TkdndVersion = TkinterDnD._require(self)
        self._init_window()
        self._init_variables()
        self._init_state()
        self._init_managers()
        self._init_ui()
        self._load_startup_file()

    def _init_window(self):
        """Initialize window properties (title, size, icon)."""
        self.title(f"Connie's Uploader {config.APP_VERSION}")
        self.geometry("1250x850")
        self.minsize(1050, 720)

        # Set up graceful shutdown on window close
        # System Tray: Close button hides the window instead of quitting
        self.protocol("WM_DELETE_WINDOW", self.withdraw)

        try:
            ico_path = config.resource_path("logo.ico")
            png_path = config.resource_path("logo.png")
            if os.path.exists(ico_path):
                try:
                    self.iconbitmap(ico_path)
                except Exception:
                    pass
            elif os.path.exists(png_path):
                self.iconphoto(True, ImageTk.PhotoImage(Image.open(png_path)))
        except Exception as e:
            logger.warning(f"Icon load warning: {e}")

    def _init_variables(self):
        """Initialize UI variables and executors."""
        self.menu_thread_var = tk.IntVar(value=5)
        self._last_global_thread_limit_value = config.DEFAULT_THREAD_COUNT
        self.var_show_previews = tk.BooleanVar(value=True)
        self.var_separate_batches = tk.BooleanVar(value=False)
        self.var_appearance_mode = tk.StringVar(value="System")
        self.thumb_executor = ThreadPoolExecutor(max_workers=config.THUMBNAIL_WORKERS)

        # Queues for thread communication
        self.progress_queue = queue.Queue(maxsize=1000)
        self.ui_queue = queue.Queue(maxsize=500)
        self.result_queue = queue.Queue(maxsize=1000)
        self.cancel_event = threading.Event()
        self.lock = threading.Lock()

        # UI state
        self.file_widgets = {}
        self.groups = []
        self.results = []
        self.log_cache = []
        self.activity_events = []
        self.activity_log_file = config.ACTIVITY_LOG_FILE
        self.preflight_issues = []
        self.preflight_action_files = []
        self.preflight_action_file_issue_texts = []
        self.preflight_action_folders = []
        self.preflight_action_viper_targets = False
        self.preflight_detail_lines = []
        self.import_check_issues = []
        self.image_refs = set()  # Using set for O(1) add/remove operations
        self.log_window_ref = None
        self.clipboard_buffer = []
        self.upload_total = 0
        self.upload_count = 0
        self.is_uploading = False
        self.current_output_files = []
        self.current_completion_summary = None
        self.pix_galleries_to_finalize = []
        self.output_dir = "Output"
        self._template_recovery_notice_shown = False

    def _init_state(self):
        """Initialize application state tracking."""
        # Batch/Group tracking
        self.group_counter = 0

        # Drag & Drop state
        self.drag_data = {"item": None, "type": None, "y_start": 0, "widget_start": None}
        self.selected_files = set()
        self.selection_anchor = None
        self.highlighted_row = None
        self.context_menu = tk.Menu(self, tearoff=0)

        # Service-specific state
        self.vipr_galleries_map = {}
        self.selected_gallery_by_service = {}

    def _init_managers(self):
        """Initialize manager objects and background workers."""
        self.settings_mgr = SettingsManager()
        self.settings = self.settings_mgr.load()

        # Configure sidecar worker count before it's started
        from modules.sidecar import SidecarBridge

        worker_count = self.settings.get("global_worker_count", 8)
        SidecarBridge.set_worker_count(worker_count)

        self.template_mgr = TemplateManager()
        self.upload_manager = UploadManager(
            self.progress_queue, self.result_queue, self.cancel_event
        )

        self._load_credentials()
        # RenameWorker disabled - not currently used (no enqueue calls in codebase)
        # Kept in controller.py for future implementation if needed
        self.rename_worker = None

        # Central history directory
        self.central_history_path = os.path.join(
            os.path.expanduser("~"), ".conniesuploader", "history"
        )
        if not os.path.exists(self.central_history_path):
            os.makedirs(self.central_history_path)

        self.saved_threads_data = viper_api.load_saved_threads()

        # Initialize AutoPoster
        self.auto_poster = AutoPoster(self.creds, self.saved_threads_data)

        # System Tray Integration
        from modules.ui.system_tray import SystemTrayManager

        self.system_tray = SystemTrayManager(self)
        self.system_tray.start()

        # Start Python-owned ViperGirls scheduled posting.
        self.scheduler_queue = queue.Queue()
        self.viper_scheduler = viper_api.ViperGirlsPostScheduler(
            self.creds,
            self.scheduler_queue,
        )
        self.viper_scheduler.start()
        self._process_scheduler_events()

    def _process_scheduler_events(self):
        try:
            while True:
                event = self.scheduler_queue.get_nowait()
                if event.get("type") == "scheduled_post_completed":
                    status = event.get("status")
                    msg = event.get("msg")
                    post_data = event.get("data", {})
                    thread_name = post_data.get("thread_name", "Unknown Thread")
                    if status == "posted":
                        self.add_activity(
                            f"Scheduled post to '{thread_name}' succeeded.", "success"
                        )
                    else:
                        self.add_activity(
                            f"Scheduled post to '{thread_name}' failed: {msg}", "error"
                        )
        except queue.Empty:
            pass
        self.after(1000, self._process_scheduler_events)

    def _init_ui(self):
        """Initialize user interface (menu, layout, drag-and-drop)."""
        self._create_menu()
        self._create_layout()
        self._apply_settings()
        self.bind_all("<Delete>", self._delete_selected_from_key)
        self.bind_all("<BackSpace>", self._delete_selected_from_key)
        self.bind_all("<c>", self._toggle_selected_cover_from_key)
        self.bind_all("<C>", self._toggle_selected_cover_from_key)
        self.after(250, self._show_template_recovery_notice)

        # Register drag-and-drop on main window
        self.drop_target_register(DND_FILES)
        self.dnd_bind("<<Drop>>", self.drop_files)
        self.bind("<Button-1>", self._clear_highlights, add="+")

        # CRITICAL FIX: Register drag-and-drop on scrollable containers with delay
        # CustomTkinter's scrollable frames use internal canvases that capture drop events
        # We need to register drop targets on these canvases after they're fully initialized
        # Using after() ensures the widget tree is complete before registration
        self.after(config.UI_DROP_TARGET_DELAY_MS, self._register_drop_targets)

    def _register_drop_targets(self):
        """
        Register drag-and-drop targets on scrollable frames.

        CustomTkinter scrollable frames use internal canvases that capture mouse events,
        including drag-and-drop. We need to explicitly register these canvases as drop
        targets and bind the drop handler to them.

        This method should be called with a delay (via after()) to ensure widgets are
        fully initialized before registration.
        """
        logger.info("Registering drop targets on scrollable containers...")

        # Force widget tree to update before registration
        self.update_idletasks()

        # Register drop target on the main file list container
        if hasattr(self.list_container, "_parent_canvas"):
            try:
                canvas = self.list_container._parent_canvas
                if canvas:
                    canvas.drop_target_register(DND_FILES)
                    canvas.dnd_bind("<<Drop>>", self.drop_files)
                    logger.info(f"✓ Registered drop target on list_container canvas: {canvas}")
                else:
                    logger.warning("list_container._parent_canvas is None")
            except Exception as e:
                logger.error(
                    f"✗ Could not register drop target on list_container: {e}", exc_info=True
                )
        else:
            logger.warning("list_container does not have _parent_canvas attribute")

        # Register drop target on the settings scrollable frame
        if hasattr(self.settings_frame_container, "_parent_canvas"):
            try:
                canvas = self.settings_frame_container._parent_canvas
                if canvas:
                    canvas.drop_target_register(DND_FILES)
                    canvas.dnd_bind("<<Drop>>", self.drop_files)
                    logger.info(
                        f"✓ Registered drop target on settings_frame_container canvas: {canvas}"
                    )
                else:
                    logger.warning("settings_frame_container._parent_canvas is None")
            except Exception as e:
                logger.error(
                    f"✗ Could not register drop target on settings_frame_container: {e}",
                    exc_info=True,
                )
        else:
            logger.warning("settings_frame_container does not have _parent_canvas attribute")

        logger.info("Drop target registration complete")

    def _load_startup_file(self):
        """Load file from command line argument if provided."""
        if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
            self.after(500, lambda: self._process_files([sys.argv[1]]))

        # Start UI update loop
        self.after(config.UI_UPDATE_INTERVAL_MS, self.update_ui_loop)

        # Start periodic image cleanup to prevent memory leaks
        self.after(config.UI_CLEANUP_INTERVAL_MS, self._cleanup_orphaned_images)

    def _load_credentials(self):
        """Load credentials from system keyring using CredentialsManager."""
        self.creds = CredentialsManager.load_all_credentials()
        if hasattr(self, "lbl_host_readiness"):
            self._refresh_host_readiness()


if __name__ == "__main__":
    app = UploaderApp()
    app.mainloop()
