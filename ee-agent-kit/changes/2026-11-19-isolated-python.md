### Security
- `workcenter gates` and `workcenter export` no longer import a `kikit/`, `pcbnew.py` or `sitecustomize.py` from a board's folder or the working directory: the KiKit probe and KiKit's run start Python isolated (`-I`), as `workcenter ci` and `workcenter placement` now do. A `panel.json` that names Python for KiKit to run (`code`, `plugin`, `post.script`) is refused, red.
