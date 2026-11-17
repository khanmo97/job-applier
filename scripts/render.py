#!/usr/bin/env python3
"""Compile a resume .tex to PDF and check it is exactly one page.

Usage: render.py path/to/Name_Resume.tex [--png]
Writes Name_Resume.pdf next to the .tex (and Name_Resume.png with --png, for a visual check).
Uses pdflatex if installed, otherwise tectonic. Exit 0 = one page, 2 = wrong page count, 1 = error.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def compile_tex(tex: Path, out_dir: Path) -> Path:
    with tempfile.TemporaryDirectory() as tmp:
        if shutil.which("pdflatex"):
            cmd = ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", f"-output-directory={tmp}", str(tex)]
        elif shutil.which("tectonic"):
            cmd = ["tectonic", "--chatter", "minimal", "--outdir", tmp, str(tex)]
        else:
            print("error: neither pdflatex nor tectonic is installed (see README > Requirements)", file=sys.stderr)
            sys.exit(1)
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=tex.parent)
        pdf = Path(tmp) / (tex.stem + ".pdf")
        if r.returncode != 0 or not pdf.exists():
            log = (r.stdout + r.stderr)[-3000:]
            print(f"error: LaTeX failed\n{log}", file=sys.stderr)
            sys.exit(1)
        dest = out_dir / pdf.name
        shutil.copyfile(pdf, dest)
        return dest


def page_count(pdf: Path) -> int:
    out = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True).stdout
    m = re.search(r"^Pages:\s+(\d+)", out, re.M)
    return int(m.group(1)) if m else -1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tex")
    ap.add_argument("--png", action="store_true", help="also write a PNG of page 1 for a visual check")
    ap.add_argument("--max-pages", type=int, default=1)
    a = ap.parse_args()
    tex = Path(a.tex).expanduser().resolve()
    pdf = compile_tex(tex, tex.parent)
    pages = page_count(pdf)
    print(f"PDF: {pdf}\nPages: {pages}")
    if a.png and shutil.which("pdftoppm"):
        subprocess.run(["pdftoppm", "-png", "-r", "80", "-singlefile", "-f", "1", str(pdf), str(pdf.with_suffix(""))])
        print(f"PNG: {pdf.with_suffix('.png')}")
    if pages != a.max_pages:
        print(f"FAIL: resume is {pages} page(s); it must be exactly {a.max_pages}. Cut or tighten bullets.")
        sys.exit(2)
    print("OK: one page")


if __name__ == "__main__":
    main()
