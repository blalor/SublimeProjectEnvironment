# Project Environment Host py33

**Auto-managed — do not edit or install manually.**

This package is materialized onto disk by the **Project Environment** package
and runs in Sublime Text's legacy (Python 3.3) plugin host. Project Environment
itself runs in the modern (3.8+) host, whose process environment is separate
from the legacy host's; this companion fills that gap.

It is tool-agnostic: it applies the resolved project environment to the legacy
host's process `os.environ`, exactly as Project Environment does in the modern
host, and modifies nothing else. Any legacy-host package that spawns subprocesses
then inherits that environment.

It is created and updated automatically when Project Environment loads. Removing
Project Environment leaves this directory in place; delete it manually if you no
longer want it.
