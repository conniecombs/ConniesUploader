# modules/plugins/base.py
import abc
from typing import Dict, Any, Tuple, Optional
import customtkinter as ctk

class ImageHostPlugin(abc.ABC):
    @property
    @abc.abstractmethod
    def id(self) -> str:
        """Unique identifier (e.g., 'imx.to')"""
        pass

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Display name (e.g., 'IMX.to')"""
        pass

    # --- UI Methods (Main Thread) ---

    @abc.abstractmethod
    def render_settings(self, parent: ctk.CTkFrame, current_settings: Dict[str, Any]) -> Any:
        """
        Draws the settings widgets into 'parent'. 
        Returns a 'ui_handle' (object/dict) containing the Tkinter variables 
        needed to retrieve values later.
        """
        pass

    @abc.abstractmethod
    def get_configuration(self, ui_handle: Any) -> Dict[str, Any]:
        """
        Called when Start Upload is clicked. 
        Extracts values from the 'ui_handle' into a plain dictionary.
        """
        pass

    # --- Worker Methods (Background Thread) ---

    @abc.abstractmethod
    def initialize_session(self, config: Dict[str, Any], creds: Dict[str, Any]) -> Dict[str, Any]:
        """
        Runs once per batch start. Performs login, fetches global tokens.
        Returns a 'context' dict passed to subsequent methods.
        """
        pass

    def prepare_group(self, group_info: Any, config: Dict[str, Any], context: Dict[str, Any], creds: Dict[str, Any]) -> None:
        """
        Optional: Runs before processing a specific group of files.
        Used for creating galleries per folder (e.g., IMX, Pixhost).
        Modifies 'context' or 'group_info' in place.
        """
        pass

    @abc.abstractmethod
    def upload_file(self, file_path: str, group_info: Any, config: Dict[str, Any], context: Dict[str, Any], progress_callback) -> Tuple[str, str]:
        """
        Uploads a single file.
        Returns: (viewer_url, thumb_url)
        """
        pass
    
    def finalize_batch(self, context: Dict[str, Any]) -> None:
        """Optional: Runs after all uploads are finished."""
        pass