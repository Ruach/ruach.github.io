#!/usr/bin/env python3
"""
build_cv.py — Fetch live citation count and GitHub stars/forks, patch
JAEHYUK_CV.tex, then compile it to PDF with pdflatex.

Usage:
    python3 build_cv.py [--no-fetch] [--no-compile]

Flags:
    --no-fetch    Skip web fetching; just compile the current .tex file.
    --no-compile  Only fetch and patch; skip the pdflatex compilation step.
"""

import re
import sys
import time
import subprocess
import shutil
import argparse
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

TEX_FILE = Path(__file__).parent.parent / "files" / "JAEHYUK_CV.tex"

SCHOLAR_URL = (
    "https://scholar.google.com/citations"
    "?user=nfpCTgUAAAAJ&hl=en&sortby=pubdate"
)

GITHUB_REPOS = [
    # (name_in_tex_regex, owner, repo)
    ("autofz",  "sslab-gatech", "autofz"),
    ("opensgx", "sslab-gatech", "opensgx"),
    ("sgx-bomb","sslab-gatech", "sgx-bomb"),
]

# Pattern used in .tex for each artifact row, e.g.:
#   {\makebox[1.0cm][l]{\faCodeFork 13} \makebox[1.0cm][l]{\faStar 85}}
# We match the numbers and replace them.
ARTIFACT_PATTERN = re.compile(
    r'(\\makebox\[1\.0cm\]\[l\]\{\\faCodeFork\s+)(\d+)(\}\s*'
    r'\\makebox\[1\.0cm\]\[l\]\{\\faStar\s+)(\d+)(\})'
)

# Pattern for the citations line, e.g.:
#   \section{PUBLICATION \& PATENT \small\href{...}{(826 citations)}}
CITATION_PATTERN = re.compile(
    r'(\{)\((\d+)\s+citations\)(\})'
)

# Per-paper citation patterns in the impact summary table.
# Each entry: (tex_label, scholar_title_keyword)
# The table row looks like:  Dark-ROP  & USENIX Sec.'17 & 274 & ...
PAPER_ROW_PATTERN = re.compile(
    r'(^.*?&\s*[\w\s\'\.\-\/]+&\s*)(\d+)(\s*&\s*\\textcolor)',
    re.MULTILINE,
)

# Map from the short label used in the table to a keyword from Scholar titles
PAPER_CITE_MAP = [
    ("Dark-ROP",    "Hacking in darkness"),
    ("SGX-Bomb",    "SGX-Bomb"),
    ("OpenSGX",     "OpenSGX"),
    ("PrivateZone", "Privatezone"),
    ("PORTAL",      "PORTAL"),
    ("autofz",      "autofz"),
    ("DeFi Survey", "DeFi"),
    ("P\\+RETOUCH", "Prime\\+ retouch"),
    ("SENSE",       "SENSE"),
]

# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------

def fetch_citations() -> tuple[int | None, dict[str, int]]:
    """
    Scrape Google Scholar profile page.
    Returns (total_citations, {title_keyword_lower: cite_count}).
    """
    try:
        import requests
        from bs4 import BeautifulSoup

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        }
        resp = requests.get(SCHOLAR_URL, headers=headers, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Total citations
        total: int | None = None
        td = soup.select_one("#gsc_rsb_st td.gsc_rsb_std")
        if td:
            total = int(td.text.strip().replace(",", ""))

        # Per-paper citations: each row is a <tr class="gsc_a_tr">
        per_paper: dict[str, int] = {}
        for row in soup.select("tr.gsc_a_tr"):
            title_el = row.select_one(".gsc_a_at")
            cite_el  = row.select_one(".gsc_a_c a")
            if title_el and cite_el:
                title = title_el.get_text(strip=True).lower()
                try:
                    count = int(cite_el.get_text(strip=True).replace(",", "") or "0")
                except ValueError:
                    count = 0
                per_paper[title] = count

        if not total and not per_paper:
            print("[warn] Could not parse Scholar page.")
        return total, per_paper

    except Exception as exc:
        print(f"[warn] Scholar fetch failed: {exc}")
        return None, {}


def fetch_github_stats(owner: str, repo: str) -> tuple[int, int] | None:
    """Return (forks, stars) for a GitHub repo using the public API."""
    try:
        import requests

        url = f"https://api.github.com/repos/{owner}/{repo}"
        headers = {"Accept": "application/vnd.github+json"}
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return data["forks_count"], data["stargazers_count"]
    except Exception as exc:
        print(f"[warn] GitHub fetch failed for {owner}/{repo}: {exc}")
        return None


# ---------------------------------------------------------------------------
# Patching
# ---------------------------------------------------------------------------

def patch_tex(citations: int | None, per_paper: dict[str, int],
              github_stats: dict[str, tuple[int, int]]) -> bool:
    """
    Rewrite TEX_FILE in-place with updated numbers.
    Returns True if any change was made.
    """
    original = TEX_FILE.read_text(encoding="utf-8")
    patched = original

    # 1. Total citation count in section header
    if citations is not None:
        def replace_citations(m: re.Match) -> str:
            return f"{m.group(1)}({citations} citations){m.group(3)}"
        patched = CITATION_PATTERN.sub(replace_citations, patched)

    # 2. Per-paper citation counts in the impact summary table
    # Table row format:  Short-Label  & Venue'YY  & NNN & \textcolor...
    if per_paper:
        for tex_label, scholar_keyword in PAPER_CITE_MAP:
            # Find matching scholar title
            kw = scholar_keyword.lower().replace("\\", "")
            matched_count = None
            for title, count in per_paper.items():
                if kw in title:
                    matched_count = count
                    break
            if matched_count is None:
                continue
            # Replace the count in the matching table row
            # Row pattern: tex_label (with possible regex escapes) ... & NNN & \textcolor
            row_re = re.compile(
                r'(' + tex_label + r'\s+&[^&]+&\s*)(\d+)(\s*&\s*\\textcolor)',
                re.MULTILINE,
            )
            patched = row_re.sub(
                lambda m, c=matched_count: f"{m.group(1)}{c}{m.group(3)}",
                patched,
            )

    # 3. GitHub stars / forks
    lines = patched.splitlines(keepends=True)
    new_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # Detect which repo this block belongs to by looking back for the
        # softwareArtifactHeading that contains the repo name.
        # The stars/forks line immediately follows the heading line.
        matched = False
        for name, owner, repo in GITHUB_REPOS:
            stats = github_stats.get(repo)
            if stats is None:
                continue
            forks, stars = stats
            # The forks/stars line is the second argument to softwareArtifactHeading.
            # Check if *this* line has the pattern AND the preceding heading mentions the repo.
            if ARTIFACT_PATTERN.search(line):
                # Look back for the repo name in recent lines (within 4 lines).
                context = "".join(lines[max(0, i - 4): i])
                if name.lower() in context.lower() or repo.lower() in context.lower():
                    line = ARTIFACT_PATTERN.sub(
                        lambda m, f=forks, s=stars: (
                            f"{m.group(1)}{f}{m.group(3)}{s}{m.group(5)}"
                        ),
                        line,
                    )
                    matched = True
                    break
        new_lines.append(line)
        i += 1

    patched = "".join(new_lines)

    if patched == original:
        print("[info] No changes needed — numbers are already up-to-date.")
        return False

    TEX_FILE.write_text(patched, encoding="utf-8")
    print(f"[info] Patched {TEX_FILE.name}")
    return True


# ---------------------------------------------------------------------------
# Compilation
# ---------------------------------------------------------------------------

def compile_tex() -> bool:
    """Run pdflatex twice (for cross-references) in the tex file's directory."""
    pdflatex = shutil.which("pdflatex")
    if not pdflatex:
        print("[error] pdflatex not found in PATH. Install a TeX distribution.")
        return False

    cwd = TEX_FILE.parent
    cmd = [pdflatex, "-interaction=nonstopmode", "-halt-on-error", TEX_FILE.name]

    for run in range(1, 3):  # two passes
        print(f"[info] pdflatex pass {run}/2 …")
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
        if result.returncode != 0:
            # Print last 30 lines of log so errors are visible
            log_lines = result.stdout.splitlines()
            print("\n".join(log_lines[-30:]))
            print(f"[error] pdflatex failed on pass {run} (exit {result.returncode})")
            return False

    pdf = cwd / TEX_FILE.with_suffix(".pdf").name
    print(f"[ok] PDF written to {pdf}")
    return True


# ---------------------------------------------------------------------------
# Open PDF
# ---------------------------------------------------------------------------

def open_pdf() -> None:
    """
    Open (or reload) the compiled PDF.

    - If Skim is installed, use it — it auto-reloads on file change.
    - Otherwise fall back to Preview, closing any stale window first so
      macOS does not serve the cached version.
    """
    pdf = TEX_FILE.with_suffix(".pdf")

    if shutil.which("open") is None:
        print("[warn] 'open' command not found; cannot open PDF automatically.")
        return

    skim = Path("/Applications/Skim.app")
    if skim.exists():
        subprocess.run(["open", "-a", "Skim", str(pdf)])
        print("[info] Opened in Skim (auto-reloads on future builds).")
        return

    # Preview caches the old document; close it before reopening.
    pdf_name = pdf.name
    close_script = f"""
tell application "Preview"
    repeat with d in documents
        if name of d is "{pdf_name}" then
            close d
            exit repeat
        end if
    end repeat
end tell
"""
    subprocess.run(["osascript", "-e", close_script], capture_output=True)
    subprocess.run(["open", "-a", "Preview", str(pdf)])
    print("[info] Opened fresh in Preview.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-fetch",   action="store_true", help="Skip web fetching")
    parser.add_argument("--no-compile", action="store_true", help="Skip pdflatex compilation")
    parser.add_argument("--open",       action="store_true", help="Open the PDF after compilation")
    args = parser.parse_args()

    citations: int | None = None
    per_paper: dict[str, int] = {}
    github_stats: dict[str, tuple[int, int]] = {}

    if not args.no_fetch:
        print("[step] Fetching Google Scholar citations …")
        citations, per_paper = fetch_citations()
        if citations is not None:
            print(f"       Total citations: {citations}")
        if per_paper:
            print(f"       Per-paper data: {len(per_paper)} entries fetched")

        for name, owner, repo in GITHUB_REPOS:
            print(f"[step] Fetching GitHub stats for {owner}/{repo} …")
            stats = fetch_github_stats(owner, repo)
            if stats is not None:
                forks, stars = stats
                print(f"       {name}: ★ {stars}  ⑂ {forks}")
                github_stats[repo] = stats
            time.sleep(0.3)  # be polite to GitHub API

        patch_tex(citations, per_paper, github_stats)
    else:
        print("[info] Skipping web fetch (--no-fetch).")

    if not args.no_compile:
        print("[step] Compiling …")
        ok = compile_tex()
        if not ok:
            sys.exit(1)
        if args.open:
            open_pdf()
    else:
        print("[info] Skipping compilation (--no-compile).")


if __name__ == "__main__":
    main()
