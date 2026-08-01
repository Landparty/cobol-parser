# Publishing executables without publishing source

This repo is private, under an EULA (`LICENSE`) that keeps the source
proprietary. That said, private-repo permissions don't have a "download
releases but can't read source" tier: on GitHub, repo-read access is
repo-read access, full stop, whether you're cloning `main` or downloading a
Release asset. Two separate mechanisms exist here for two separate goals;
neither one, by itself, lets you hand a binary to someone who has zero
access to this repo.

## What the release workflow builds

On every `release-please`-cut release (`.github/workflows/release-please.yml`),
three kinds of artifacts get attached to the GitHub Release:

1. **`sdist` + a pure-Python fallback wheel** (`build-sdist`) — plain `.py`
   source, as usual for a source distribution.
2. **Platform wheels with the Cython extension built in** (`build-binary-wheels`,
   via `cibuildwheel`) — `_lexer_fast` / `_preprocess_fast` / `_data_fast`
   are compiled to `.so`/`.pyd`, but every other module (parsers, AST models,
   analysis, CLI — the large majority of the codebase) still ships as
   readable `.py` inside the wheel. **This is not source-hidden**; it's an
   accelerated install, not a protected one.
3. **Single-file Nuitka executables** (`build-nuitka-executables`, new) — one
   binary per OS (`cobol-parser-linux-x86_64`, `cobol-parser-macos-arm64`,
   `cobol-parser-windows-amd64.exe`). Nuitka compiles the *entire*
   `cobolparser` package straight to C and then machine code, so unlike the
   wheels above, no `.py` source ships in these at all — only compiled code
   plus module/exception qualified names (e.g. `cobolparser.analysis`),
   which Nuitka keeps for traceback formatting. Spot-checked with `strings`
   against the compiled binary: no docstrings, comments, or function bodies
   show up as plaintext.

   Trade-off versus the wheel: this is the CLI only (`cobol-parser parse ...`,
   `tokenize`, `analyze`, etc.), not an importable library — Nuitka *can*
   compile a package into an importable extension module instead of a
   standalone executable, but that's a separate build mode this workflow
   doesn't use. If something needs `import cobolparser` as a hidden-source
   dependency (as `mockymock` currently does via a `git+https` pin — see
   that repo's own `PUBLISHING.md`), the Nuitka CLI binary here doesn't
   cover that case by itself.

## The part this workflow does *not* solve

Attaching a binary to a Release on a **private** repo only makes it
downloadable by people who already have read access to the repo — i.e.,
people who could just as easily `git clone` the source. There is no GitHub
permission level that grants "Releases only." So this workflow gets you
source-free *artifacts*; it does not by itself get you a way to hand those
artifacts to someone with zero repo access.

If the actual goal is distributing to people who should never see this
repo at all (customers, non-technical users, anyone outside the
collaborator list), you need one more piece, which is a decision for
whoever owns distribution, not something this workflow can decide on its
own:

- Mirror the built executables to somewhere access is *not* tied to this
  repo — a separate public "releases only" repo (that never contains
  source, only CI-pushed binaries), a company website, or object storage
  with a shareable link.
- Or accept that anyone who can download the binary can also read the
  source, and stop optimizing for source-hiding via repo permissions.

## Local build

```bash
COBOLPARSER_SKIP_EXT=1 pip install .
pip install nuitka
# Linux only:
sudo apt-get install -y patchelf

scripts/build_executable.sh cobol-parser-dev
./build/cobol-parser-dev --version
```
