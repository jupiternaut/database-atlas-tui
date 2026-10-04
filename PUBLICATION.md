# First publication · 2026-10-04

This is the GitHub publication of the existing Database Atlas TUI, not a new
web implementation. There was no Git history in the source application directory;
the first commit is therefore a source snapshot, not a history migration.

## Included

- The application (`app.py`), Textual stylesheet, launcher and pinned dependencies.
- The read-only data adapter and data / interactive UI tests.
- The existing preview generator and four generated SVG/PNG terminal previews.
- The three existing database atlas JSON snapshots. The graph and popularity
  observations are byte-identical; knowledge metadata has the changes below.

## Packaging-only changes

- The default data path is now `data/` beside the application instead of a path
  outside the repository. Explicit external data directories remain supported.
- Additional tests check loading from unrelated working directories and the
  original external `outputs` layout.
- README instructions use clone-relative paths and describe the bundled data.
- Two explanatory metadata strings in `knowledge.json` replace a workstation
  name and private-network address with generic wording. Its ranking reference
  now points to the included `popularity-observations.json` instead of an
  unbundled file. Product nodes, relationships, conditions and ranking values
  are unchanged.
- This publication record is new. Application behavior and source claims are
  otherwise unchanged; the original running directory is preserved.
- Generated SVG previews have trailing whitespace removed for repository
  hygiene; their drawing content and PNG companions are unchanged.

## Excluded

- `.venv/`: local Python environment and dependency binaries; recreate from the
  requirements files.
- `__pycache__/`, `.pytest_cache/` and bytecode: generated local caches.
- Unrelated workspace projects, logs, credentials and browser/session state.
- Font binaries: terminal fonts remain a user choice. Preview generation needs
  the separately installed fonts documented in README.

## Provenance and interpretation

The family graph is the earlier `database-graphs-v2` dataset. The nine-perspective
dataset is `database-perspectives-v3`. Its nodes, edges and matrix rows preserve
their source URLs and conditions. The adapter does not merge local architecture
roles into global product identities.

Popularity observations are the existing **2026-10** DB-Engines snapshot, sourced
from [DB-Engines ranking](https://db-engines.com/en/ranking). These are popularity
indicators, not installation counts, performance measurements, recruitment data
or market shares. This publication does not claim to have re-fetched or freshly
audited every upstream fact. Missing values are not zero.

The architecture views summarize documented designs and are not topology maps of
the author's computer or servers. Runtime reads local files only; an external
website opens only when the user explicitly selects the source-opening button.

## Rights

No pre-existing project license was found, and no new license is imposed in this
upload. Public repository visibility is not itself an open-source license grant.
Third-party documentation, ranking sources, dependency packages and fonts retain
their respective rights and terms. Source URLs are preserved for attribution and
checking, not used to imply endorsement or to relicense third-party material.
