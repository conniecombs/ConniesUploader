# modules/utils.py
import sys
import os
import platform
import winreg
from tkinter import messagebox

class ContextUtils:
    @staticmethod
    def install_menu():
        if platform.system() != 'Windows': return
        try:
            key = winreg.CreateKey(winreg.HKEY_CLASSES_ROOT, r"Directory\shell\ConniesUploader")
            winreg.SetValue(key, "", winreg.REG_SZ, "Upload with Connie's Uploader")
            cmd_key = winreg.CreateKey(key, "command")
            py_exe = sys.executable.replace("python.exe", "pythonw.exe")
            if not os.path.exists(py_exe): py_exe = sys.executable
            # We assume this is called from main.py, so we use sys.argv[0] or __file__ from the caller
            # But for safety in a module, we can rely on sys.executable for frozen apps
            # or pass the script path. For now, we assume standard usage.
            script_path = os.path.abspath(sys.argv[0])
            
            cmd = f'"{py_exe}" "{script_path}" "%V"'
            if getattr(sys, 'frozen', False): 
                cmd = f'"{sys.executable}" "%V"'
                
            winreg.SetValue(cmd_key, "", winreg.REG_SZ, cmd)
            messagebox.showinfo("Success", "Context menu installed.")
        except Exception as e: 
            messagebox.showerror("Error", str(e))

    @staticmethod
    def remove_menu():
        if platform.system() != 'Windows': return
        try:
            winreg.DeleteKey(winreg.HKEY_CLASSES_ROOT, r"Directory\shell\ConniesUploader\command")
            winreg.DeleteKey(winreg.HKEY_CLASSES_ROOT, r"Directory\shell\ConniesUploader")
            messagebox.showinfo("Success", "Context menu removed.")
        except: pass