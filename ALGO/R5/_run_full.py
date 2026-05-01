"""Run the notebook end-to-end with FULL output capture (DataFrames + prints).

Writes:
  _full_run_log.txt — stdout/stderr per cell
  combination_search_drinks_outputs/*.csv — already produced by the notebook
"""
import json, sys, traceback, re, io, os, contextlib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.show = lambda *a, **k: None
import pandas as pd

# Plotly: disable browser
import plotly.io as pio
pio.renderers.default = "json"

# Real `display` that prints DataFrames as pandas does
class _Markdown(str):
    def __init__(self, s=""): self.s = s
    def __repr__(self): return self.s
    def _repr_markdown_(self): return self.s
    def __str__(self): return self.s

def display(*objs, **kw):
    for o in objs:
        if isinstance(o, _Markdown):
            print(str(o))
        elif isinstance(o, pd.DataFrame):
            with pd.option_context("display.max_columns", 80, "display.width", 200,
                                   "display.max_rows", 60):
                print(o.to_string())
        elif isinstance(o, pd.Series):
            print(o.to_string())
        else:
            print(repr(o))

class _IPyDisplayShim:
    display = staticmethod(display)
    Markdown = _Markdown
    HTML = _Markdown
sys.modules.setdefault("IPython", type("M", (), {"display": _IPyDisplayShim})())
sys.modules["IPython.display"] = _IPyDisplayShim

with open("combination_search_drinks.ipynb") as fh:
    nb = json.load(fh)

ns = {"display": display, "Markdown": _Markdown}
magic_re = re.compile(r"^\s*[%!].*$", re.MULTILINE)

with open("_full_run_log.txt", "w") as logf:
    for i, c in enumerate(nb["cells"]):
        if c["cell_type"] != "code":
            continue
        if i == 0:
            continue
        src = "".join(c["source"]) if isinstance(c["source"], list) else c["source"]
        src = magic_re.sub("", src)
        src = re.sub(r"\bfig\d*\.show\(\)", "pass", src)
        head = src.split("\n", 1)[0][:90]
        marker = f"\n{'='*80}\n>>> CELL {i:3d}: {head}\n{'='*80}\n"
        print(marker, flush=True)
        logf.write(marker)
        buf_out = io.StringIO()
        buf_err = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
                exec(compile(src, f"<cell-{i}>", "exec"), ns)
            logf.write(buf_out.getvalue())
            if buf_err.getvalue().strip():
                logf.write(f"\n[stderr]\n{buf_err.getvalue()}\n")
            print(buf_out.getvalue()[-2000:], flush=True)  # last 2k chars per cell
        except Exception as e:
            tb = traceback.format_exc(limit=6)
            logf.write(f"\n[FAIL] {type(e).__name__}: {e}\n{tb}\n")
            print(f"[FAIL] {type(e).__name__}: {e}", flush=True)
            print(tb, flush=True)
print("\n\nFULL LOG: _full_run_log.txt")
