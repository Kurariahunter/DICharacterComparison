"""Summarize a completed batch without reading or modifying game assets."""
import json
from collections import Counter
from pathlib import Path
import sys

p = Path(sys.argv[1])
summary = json.loads((p / 'summary.json').read_text())
unique = {}
suspect = []
for item in summary:
    report = json.loads((p / (item['character'] + '.json')).read_text(encoding='utf-8'))
    for row in report['files']:
        unique[row['logical']] = row
        origin = row.get('pc') or {}
        if origin.get('identity') == 'basename in character package':
            local = row['logical'].removeprefix('characters/' + item['character'] + '/')
            if '/' in local and not (local.startswith('motions/') and local.count('/') == 1):
                suspect.append({'report': item['character'], 'logical': row['logical'], 'pc': origin})
totals = Counter(i['status'] for row in unique.values() for i in row['inputs'])
errors = Counter(i['decode_error'] for row in unique.values() for i in row['inputs'] if 'decode_error' in i)
audit = {'completed_reports': len(summary), 'unique_paths': len(unique), 'input_status_counts': dict(totals),
         'suspect_basename_matches': suspect, 'decode_errors': dict(errors),
         'note': 'Raw totals retain original results, including flagged basename matches; not counts of game bugs or required missing assets.'}
(p / 'REVIEW.json').write_text(json.dumps(audit, indent=2), encoding='utf-8')
lines = ['# Review of the character comparison batch', '',
         f'Completed {len(summary)} report pairs. Compared Breeze resource destinations with the installed PC base files; no DisneyInfinityComplete overlay was selected. The base may already include earlier patches.', '',
         '## Most useful findings', '',
         '- Alice’s primary OCT mesh, BENT animation table and animation overrides match the PC installation byte for byte. Her primary MTB differs. This batch does not support a claim that Breeze supplies a different primary Alice mesh that fixes her dress.',
         '- Alice also contains a nested `new folder/ali_alice` model set with differences. These are separate intended paths, not evidence those copies override the primary mesh. Establish references before treating them as active.',
         '- Baloo has 53 different source inputs in the raw report, covering body/model resources, animation metadata and numerous motions. This supports comparing a coherent asset set rather than changing only one motion. It does not prove the reason his special fails.',
         '- Sixteen shared animation-tree include files differ, including powerup, facial lids, basic mobility, reaction and force powers. These deserve graph-level comparison because they can affect several characters.',
         '- Vision and Ant-Man also have substantial raw differences (28 and 22 source inputs respectively). They are useful later candidates after shared behavior is understood.', '',
         '## Report quality corrections', '',
         f'- Flagged {len(suspect)} noncanonical nested-path basename matches. The original resolver could match a backup/nested file to a primary PC archive member. `REVIEW.json` lists them; the script is corrected for future runs. Original reports are preserved.',
         '- Ten unique inputs report `Not standard Lua 5.1`. At least Alice’s progression source is decompiled Lua text, so this represents an unsupported input form in our decoder, not a broken game file. The tool does not execute the text.',
         '- Four unique BENT inputs report node-count/header disagreements. Keep these as parser findings until investigated; do not classify them as damaged assets.',
         '- Many unresolved paths are extra motion copies or alternate resource paths. An unresolved exact path is not proof that the motion is absent elsewhere or required by the active BENT.',
         '- Character totals overlap through shared or named references. Do not sum them as unique assets. Byte differences are not functional differences; two unique changed Lua files already decode to the same tables.', '',
         '## Recommended order', '',
         '1. Compare the sixteen shared graph changes structurally, ignoring editor layout metadata.',
         '2. Follow Alice’s active BENT/DNA/cloth references before testing any nested alternative model.',
         '3. Compare Baloo’s complete body and motion dependency set against our current mod overlay, preserving the working fruit/tool and material repairs.',
         '4. Add safe static parsing for decompiled Lua text and strengthen logical-path resolution before using unresolved totals to plan imports.', '',
         'No game assets were changed during this review.']
(p / 'REVIEW.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
print(json.dumps(audit, indent=2)[:1000])
