import os
import sys


if hasattr(sys, "_MEIPASS"):
    os.environ.setdefault("TCL_LIBRARY", os.path.join(sys._MEIPASS, "_tcl_data"))
    os.environ.setdefault("TK_LIBRARY", os.path.join(sys._MEIPASS, "_tk_data"))
