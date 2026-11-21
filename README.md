# Node Graph Pie for Nuke

Node Graph Pie is a radial launcher for Foundry Nuke’s Node Graph. It includes node creation and recipes, wiring, graph navigation, layout, selection, Viewer controls, and a customizable command menu.

## Install

1. Extract the ZIP to a permanent location. Keep the `node-graph-pie` directory intact.
2. Add this line to your existing Nuke user `init.py`, or create that file if needed. Replace the example with your actual absolute path.

   ```python
   import nuke
   nuke.pluginAddPath(r"C:/NukePlugins/node-graph-pie")
   ```

   On Windows the startup file is usually `%USERPROFILE%/.nuke/init.py`. On macOS and Linux it is usually `~/.nuke/init.py`. Use forward slashes or a raw Python string for paths containing backslashes.
3. Restart Nuke. Focus the Node Graph and press **Q**. You can also open **Studio → Pie Menu** from the application menu.

The package runs inside interactive Nuke with its Qt bindings. It does not require pip or the studio pipeline. If you already load the pie from a studio package, remove that duplicate registration before enabling this copy.

## Learn and customize

See the [illustrated user guide](docs/USER_GUIDE.md) for all eight menus, shortcuts, recipes, and presets. Open **Edit → Customize Pie…** inside the pie or **Studio → Customize Pie** from Nuke’s application menu.

## Uninstall

Remove the corresponding `nuke.pluginAddPath` line from your startup file and restart Nuke. The package stores personal layouts, presets, favorites, recents, and recipes in local Qt settings under **Studio Nuke / Node Graph Pie**. Removing the plugin path does not erase those preferences.

This is an independent add-on for Foundry Nuke. The release was packaged against the Nuke 17.0v2-era implementation. See the guide for verification and compatibility notes.
