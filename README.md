# Disney Infinity Character Comparison

Compare an extracted character-resource folder with a PC game installation and generate per-character reports plus a combined summary. Useful for reviewing console exports, mod resources, and alternate asset sets without manually opening every file.

**Read-only static comparison:** no assets are installed, edited, or repacked. A difference is not automatically a bug or evidence of a file's platform of origin.

## Setup

Python 3.11 on Windows was used for validation. Install the archive-reader dependency:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Run

The source resource folder should contain `characters/<internal_id>/...`. The game root should contain `assets/`.

```powershell
.venv\Scripts\python.exe compare_character_folders.py --resources "D:\ExportedResources" --game "D:\Games\Disney Infinity 3.0" --output "D:\Reports\Comparison"
```

The public copy requires explicit source/game paths and defaults to direct resource-relative paths. It does not assume a Breeze installation or local installer manifest. It enumerates all immediate folders under the source `characters` directory; those folders are not necessarily all playable characters.

- `--characters tbx_baloo ali_alice`: select internal IDs.
- `--mod "D:\Game\mods\Example"`: include a PC overlay; repeat low to high precedence.
- `--layout "D:\Research\resource-layout.json"`: use an existing compatible installer destination map.
- `--direct-paths`: ignore the layout argument.
- `--resume "D:\Reports\Comparison\<timestamp>"`: reuse saved character reports from the same declared scope.

Resume does not revalidate every source file in an already completed character report. If source contents changed, use a new output directory. The tool does not execute or fully simulate an installer.

## Output

Each timestamped run contains `SUMMARY.md`, `summary.json`, `scope.json`, per-character Markdown/JSON reports, and a `shared-source-map.json`. Results are saved after each character. A completion beep is attempted on Windows.

An optional review pass summarizes the reports without reading game assets:

```powershell
.venv\Scripts\python.exe review_folder_reports.py "D:\Reports\Comparison\<timestamp>"
```

Reports retain provenance, SHA-256 hashes, archive-reader diagnostics, overlapping installer inputs, and supported decoded differences. They may contain local paths and game-derived configuration; review before publishing.

## What is compared

- Source paths and bytes against bounded PC loose/archive lookup.
- Supported compiled Lua/DNA literal tables and PC BENT node trees when byte content differs.
- Counts of identical, different, unresolved, source-error, and decoder-error findings.

Motion curves and mesh geometry are hashed, not fully evaluated. PC-only extra files are not enumerated. Shared files not assigned to a character remain in a separate map.

The supported archive reader handles standard-key DI PK-FFFF stored/deflate members. Other keys/compression variants can remain unresolved. Text-decompiled Lua and big-endian BENT variants may not support structured comparison here. This is distinct from the Character Dependency Reporter's optional Wii U comparison mode.

An unresolved PC lookup means unresolved within this search scope, not globally missing from the game. Installer overlap winners, runtime registrations, game caches, physics, and gameplay behavior are not simulated. A base installation can already contain patches.

## Examples and verification

`examples/` contains a synthetic comparison: one equal file, one changed file, and one source-only file. No game assets are included. Public CLI startup, result classification, per-character output, summary, and unchanged-scope resume are validated with these synthetic inputs.

## Contributing and credits

Useful improvements include additional structured formats, stronger scope/freshness checks, and verified shared-resource lookup. Include revision, declared source/mod scope, internal character ID, and diagnostics when reporting an issue; avoid uploading copyrighted assets or keys.

This unofficial project documents Disney Infinity research. Preserve applicable source and dependency attributions/licenses. No repository-wide license is assigned by this README.
