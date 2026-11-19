"""Make a panel of a board with KiKit: `<python with KiKit> tools/panel.py <board> <panel> <preset.json>`.

`workcenter export` runs this under KIKIT_PYTHON when the project holds `panel.json`. It calls KiKit's
own `doPanelization`, the function its command line and its KiCad plugin both call, so KiKit's
command-line start, which imports wxPython for a GUI it does not open, is not needed. The last line
printed is JSON: the layout's type, rows and cols as KiKit resolved them from the preset.

A preset can name Python for KiKit to run: a section's `code` plugin and a text's `plugin`, loaded while
KiKit reads the preset, and `post.script`, run on the built panel. panel.json is the board repository's
own file, so a preset that names any of them is refused on 1 line before KiKit reads it.
"""

import json
import sys

from kikit import panelize_ui_impl as ki
from kikit.panelize_ui import doPanelization

board, panel, preset_file = sys.argv[1:4]
# The preset as JSON, merged on KiKit's default, before any of it is validated (which loads plugins).
raw = ki.loadPresetChain([":default", preset_file])
for section, values in raw.items():
    named = {k: v for k, v in values.items() if k in ("code", "plugin")} if isinstance(values, dict) else {}
    if section == "post":
        named["script"] = values.get("script", "")
    for key, value in named.items():
        if value not in ("none", ""):
            sys.exit(
                f"{preset_file}: {section}.{key} names Python for KiKit to run ({value}): the gates run no "
                "code a board's panel.json names; use a built-in KiKit type"
            )
preset = ki.obtainPreset([preset_file])
doPanelization(board, panel, preset)
layout = preset["layout"]
print(json.dumps({"type": layout["type"], "rows": int(layout["rows"]), "cols": int(layout["cols"])}))
