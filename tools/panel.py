"""Make a panel of a board with KiKit: `<python with KiKit> tools/panel.py <board> <panel> <preset.json>`.

`workcenter export` runs this under KIKIT_PYTHON when the project holds `panel.json`. It calls KiKit's
own `doPanelization`, the function its command line and its KiCad plugin both call, so KiKit's
command-line start, which imports wxPython for a GUI it does not open, is not needed. The last line
printed is JSON: the layout's type, rows and cols as KiKit resolved them from the preset.
"""

import json
import sys

from kikit import panelize_ui_impl as ki
from kikit.panelize_ui import doPanelization

board, panel, preset_file = sys.argv[1:4]
preset = ki.obtainPreset([preset_file])
doPanelization(board, panel, preset)
layout = preset["layout"]
print(json.dumps({"type": layout["type"], "rows": int(layout["rows"]), "cols": int(layout["cols"])}))
