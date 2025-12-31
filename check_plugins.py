#!/usr/bin/env python3
"""
Plugin Discovery Diagnostic Script
Checks which plugins are being discovered and reports any errors.
"""

import sys
import os

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("=" * 70)
print("Plugin Discovery Diagnostic".center(70))
print("=" * 70)

# Step 1: Check if plugin files exist
print("\n[1] Checking plugin files...")
plugin_dir = "modules/plugins"
plugin_files = [f for f in os.listdir(plugin_dir) if f.endswith('.py') and not f.startswith('_')]
plugin_files = [f for f in plugin_files if 'legacy' not in f and 'v2' not in f]

print(f"Found {len(plugin_files)} plugin files:")
for f in sorted(plugin_files):
    file_path = os.path.join(plugin_dir, f)
    size = os.path.getsize(file_path)
    print(f"  ✓ {f:20} ({size:,} bytes)")

# Step 2: Try importing each plugin module
print("\n[2] Testing plugin module imports...")
import importlib
failed_imports = []

for plugin_file in sorted(plugin_files):
    if plugin_file in ['base.py', 'helpers.py', 'schema_renderer.py', '__init__.py']:
        continue

    module_name = plugin_file[:-3]  # Remove .py
    full_module = f"modules.plugins.{module_name}"

    try:
        mod = importlib.import_module(full_module)
        print(f"  ✓ {module_name:20} imported successfully")
    except Exception as e:
        print(f"  ✗ {module_name:20} FAILED: {e}")
        failed_imports.append((module_name, str(e)))

# Step 3: Load plugins via PluginManager
print("\n[3] Loading plugins via PluginManager...")
try:
    from modules.plugin_manager import PluginManager

    manager = PluginManager()
    plugins = manager.get_all_plugins()
    service_names = manager.get_service_names()
    errors = manager.get_load_errors()

    print(f"\nSuccessfully loaded {len(plugins)} plugins:")
    for plugin in plugins:
        impl = plugin.metadata.get('implementation', 'unknown')
        version = plugin.metadata.get('version', '?')
        print(f"  ✓ {plugin.name:20} id={plugin.id:25} v{version} ({impl})")

    if errors:
        print(f"\n⚠ Plugin load errors ({len(errors)}):")
        for filename, classname, error in errors:
            print(f"  ✗ {filename}.{classname or '?'}")
            print(f"     {error}")

    # Check specifically for Imgur
    print("\n[4] Checking for Imgur specifically...")
    imgur_found = any(p.id == "imgur.com" for p in plugins)

    if imgur_found:
        print("  ✓ Imgur plugin IS loaded and ready!")
        imgur = next(p for p in plugins if p.id == "imgur.com")
        print(f"     Name: {imgur.name}")
        print(f"     ID: {imgur.id}")
        print(f"     Version: {imgur.metadata.get('version')}")
    else:
        print("  ✗ Imgur plugin NOT found in loaded plugins")
        print("\n  Checking if imgur.py can be imported...")
        try:
            from modules.plugins import imgur
            print("  ✓ imgur module can be imported")
            print(f"     Has ImgurPlugin: {hasattr(imgur, 'ImgurPlugin')}")
            if hasattr(imgur, 'ImgurPlugin'):
                try:
                    instance = imgur.ImgurPlugin()
                    print(f"     Plugin ID: {instance.id}")
                    print(f"     Plugin Name: {instance.name}")
                except Exception as e:
                    print(f"  ✗ Cannot instantiate ImgurPlugin: {e}")
        except Exception as e:
            print(f"  ✗ Cannot import imgur module: {e}")
            import traceback
            traceback.print_exc()

except Exception as e:
    print(f"✗ Error loading PluginManager: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 70)
print("Diagnostic Complete".center(70))
print("=" * 70)
