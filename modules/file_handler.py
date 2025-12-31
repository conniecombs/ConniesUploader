import os
import io
import base64
from PIL import Image, ImageTk
from modules.sidecar import SidecarBridge

VALID_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp')

def scan_inputs(inputs):
    """
    Scans a list of inputs (files or folders) and returns valid image paths.
    """
    media_files = []
    
    if isinstance(inputs, str):
        inputs = [inputs]
    if not inputs:
        return []

    for item in inputs:
        if os.path.isfile(item):
            if item.lower().endswith(VALID_EXTENSIONS):
                media_files.append(item)
        elif os.path.isdir(item):
            media_files.extend(get_files_from_directory(item))
            
    return sorted(list(set(media_files)))

def get_files_from_directory(directory):
    files = []
    try:
        for root, _, filenames in os.walk(directory):
            for filename in filenames:
                if filename.lower().endswith(VALID_EXTENSIONS):
                    files.append(os.path.join(root, filename))
    except Exception as e:
        print(f"Error scanning directory: {e}")
    return files

def generate_thumbnail(file_path):
    """
    Offloads image resizing to the Go sidecar.
    Returns a PIL Image object (not ImageTk) for use in CustomTkinter.
    """
    payload = {
        "action": "generate_thumb",
        "files": [file_path],
        "config": {"width": "100"}
    }
    
    bridge = SidecarBridge.get()
    resp = bridge.request_sync(payload, timeout=2)
    
    if resp.get("status") == "success" and resp.get("data"):
        try:
            image_data = base64.b64decode(resp["data"])
            return Image.open(io.BytesIO(image_data))
        except Exception as e:
            print(f"Thumbnail decode error for {file_path}: {e}")
            return None
    return None