from modules.sidecar import SidecarBridge

# --- Generic Helpers ---

def verify_login(service, creds):
    payload = {
        "action": "verify",
        "service": service,
        "creds": creds
    }
    resp = SidecarBridge.get().request_sync(payload, timeout=15)
    if resp.get("status") == "success":
        return True, resp.get("msg", "OK")
    return False, resp.get("msg", "Failed")

def check_updates():
    # Placeholder: Future implementation to check github for updates
    return None

# --- Service Specific Wrappers (Delegating to Go) ---

def vipr_login(user, password, client=None):
    # Just returns the credentials dict for the config to use.
    # Actual authentication happens in the Go sidecar per request/session.
    return {"vipr_user": user, "vipr_pass": password}

def get_vipr_metadata(creds):
    """
    Asks Go sidecar to scrape/list galleries.
    """
    payload = {
        "action": "list_galleries",
        "service": "vipr.im",
        "creds": creds
    }
    resp = SidecarBridge.get().request_sync(payload, timeout=30)
    
    if resp.get("status") == "success":
        # Expecting Go to return: { "data": [ {"id": "1", "name": "Folder"}, ... ] }
        return {"galleries": resp.get("data", [])}
    
    return {"galleries": []}

def create_imx_gallery(user, pwd, name, client=None):
    """
    Asks Go sidecar to create a gallery on IMX and return the ID.
    """
    payload = {
        "action": "create_gallery",
        "service": "imx.to",
        "creds": {"imx_user": user, "imx_pass": pwd},
        "config": {"gallery_name": name}
    }
    
    # Increase timeout as gallery creation might involve redirects/parsing
    resp = SidecarBridge.get().request_sync(payload, timeout=30)
    
    if resp.get("status") == "success":
        # The 'msg' or 'data' field from Go should contain the new ID
        return resp.get("data")
    
    return None

def create_pixhost_gallery(name, client=None):
    # Pixhost doesn't support user galleries in the same way via this API yet,
    # but if implemented in Go, it would follow the pattern above.
    pass