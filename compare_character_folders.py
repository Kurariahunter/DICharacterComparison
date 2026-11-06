"""Batch static comparisons. Reads assets; writes reports only. Never installs mods."""
import argparse
from collections import Counter, OrderedDict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent
from research_pk_reader import Archive
from character_comparison import candidates, typed, differences
from compare_config import Chunk, decode_tables
from octane_scene import Scene


def digest(data):
    return hashlib.sha256(data).hexdigest()


def belongs(logical, char):
    # Do not mistake the root directory 'characters' for a character ID.
    if logical.startswith('characters/' + char + '/'):
        return True
    logical = logical.removeprefix('characters/')
    return re.search(r'(?<![a-z0-9])' + re.escape(char) + r'(?![a-z0-9])', logical) is not None


class PC:
    """Exact paths, plus basename ONLY in the character's own package. Bounded handles."""
    def __init__(self, game, mods, cache):
        self.layers = [game] + mods
        self.opened = OrderedDict()
        self.failed = {}
        self.cache = cache
        cache.mkdir(parents=True, exist_ok=True)

    def loose(self, name):
        return next((p for layer in reversed(self.layers) if (p := layer / name).is_file()), None)

    def archive(self, path):
        if path in self.failed:
            raise ValueError(self.failed[path])
        if path not in self.opened:
            obj = Archive.__new__(Archive)
            try:
                Archive.__init__(obj, path, self.cache / (digest(str(path).encode()) + '.json'))
            except Exception as exc:
                if getattr(obj, 'file', None):
                    obj.file.close()
                self.failed[path] = str(exc)
                raise
            self.opened[path] = obj
            if len(self.opened) > 24:
                self.opened.popitem(last=False)[1].close()
        self.opened.move_to_end(path)
        return self.opened[path]

    def read(self, logical, char):
        path = self.loose('assets/' + logical)
        if path:
            return path.read_bytes(), {'source': str(path), 'identity': 'exact loose path'}, []
        errors = []
        own = f'assets/characters/{char}/{char}.zip'
        archives = candidates(logical, char)
        bits = logical.split('/')
        if len(bits)>2 and bits[0]=='choreographies':
            archives = [f'assets/choreographies/{bits[1]}/{bits[1]}.zip',
                        f'assets/choreographies/{bits[1]}.zip', 'assets/choreographies/choreographies.zip'] + archives
        for arc in archives:
            path = self.loose(arc)
            if not path:
                continue
            try:
                archive = self.archive(path)
                key = next((k for k in (logical, 'assets/' + logical) if k in archive.index), None)
                identity = 'exact archive member'
                package_prefix = arc.removeprefix('assets/').rsplit('/',1)[0] + '/'
                local = logical.removeprefix(package_prefix)
                canonical_member = '/' not in local or (local.startswith('motions/') and local.count('/') == 1)
                if key is None and logical.startswith(package_prefix) and canonical_member:
                    base = logical.rsplit('/', 1)[-1]
                    if base in archive.index:
                        key, identity = base, 'basename in explicitly scoped package'
                if key is not None:
                    return archive.extract(key), {'source': str(path), 'member': key, 'identity': identity}, errors
            except Exception as exc:
                errors.append({'archive': str(path), 'error': str(exc)})
        return None, None, errors

    def close(self):
        for archive in self.opened.values():
            archive.close()


def structured(data, suffix):
    if suffix in ('.lua', '.dnax'):
        return typed(decode_tables(Chunk(data).read(), True))
    if suffix == '.bent':
        def node(n):
            return {'tag': n.tag, 'value': n.value, 'extra': n.extra, 'children': [node(c) for c in n.children]}
        return {str(n.value): node(n) for n in Scene.from_bytes(data).top.find('Files').children}
    raise ValueError('No structured decoder selected')


def inventory(resources, layout):
    """Use explicit CMM resource destinations where available; retain overlapping inputs."""
    result = {}
    if layout:
        report = json.loads(layout.read_text(encoding='utf-8'))
        for row in report['writes']:
            logical = row['target'].replace('\\', '/').lower().removeprefix('[game]/assets/')
            source = resources / row['source'].removeprefix('resources/')
            result.setdefault(logical, []).append({'path': source, 'action': row['action_index'], 'kind': row['kind']})
    else:
        for path in sorted(resources.rglob('*')):
            if path.is_file():
                result[path.relative_to(resources).as_posix().lower()] = [{'path': path}]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resources', type=Path, required=True)
    parser.add_argument('--game', type=Path, required=True)
    parser.add_argument('--mod', type=Path, action='append', default=[], help='Optional PC mod overlay; default compares base installation only')
    parser.add_argument('--layout', type=Path, default=None)
    parser.add_argument('--direct-paths', action='store_true', help='Ignore installer map; compare resource-relative paths')
    parser.add_argument('--characters', nargs='+', help='Limit internal IDs; default all character model folders')
    parser.add_argument('--output', type=Path, default=ROOT / 'FolderComparisons')
    parser.add_argument('--resume', type=Path, help='Continue an existing report directory using the same source snapshot')
    args = parser.parse_args()
    if not args.resources.is_dir() or not args.game.is_dir():
        parser.error('Both resources and game directories must exist')
    layout = None if args.direct_paths else args.layout
    if layout and not layout.is_file():
        parser.error('Installer layout missing. Generate it with ContinuumLayout/audit_layout.py, or use --direct-paths')
    out = args.resume or args.output / datetime.now().strftime('%Y%m%d_%H%M%S')
    out.mkdir(parents=True, exist_ok=True)
    scope = {'resources': str(args.resources.resolve()), 'game': str(args.game.resolve()), 'mods': [str(p.resolve()) for p in args.mod],
             'layout': str(layout) if layout else None, 'layout_sha256': digest(layout.read_bytes()) if layout else None,
             'note': 'Static comparison, not runtime validation. Base installation may already contain patches. No assets changed.'}
    scopefile = out / 'scope.json'
    if scopefile.exists() and json.loads(scopefile.read_text()) != scope:
        parser.error('Resume scope differs; start a new report directory')
    scopefile.write_text(json.dumps(scope, indent=2), encoding='utf-8')
    print('Indexing source paths...', flush=True)
    files = inventory(args.resources, layout)
    chars = sorted(p.name for p in (args.resources / 'characters').iterdir() if p.is_dir())
    if args.characters:
        chars = sorted(args.characters)
    pc = PC(args.game, args.mod, out / 'ArchiveIndexCache')
    summary = []
    try:
        for index, char in enumerate(chars, 1):
            if not re.fullmatch('[a-z0-9_]+', char):
                raise ValueError('Invalid character ID: ' + char)
            dest = out / (char + '.json')
            if args.resume and dest.exists():
                saved = json.loads(dest.read_text(encoding='utf-8'))
                summary.append(saved['summary'])
                print(f'[{index}/{len(chars)}] {char}: reused saved report', flush=True)
                continue
            selected = {k: v for k, v in files.items() if belongs(k, char)}
            rows = []
            print(f'[{index}/{len(chars)}] {char}: comparing {len(selected)} mapped paths...', flush=True)
            for number, (logical, sources) in enumerate(sorted(selected.items()), 1):
                row = {'logical': logical, 'inputs': [], 'installer_overlap': len(sources) > 1}
                current, origin, errors = pc.read(logical, char)
                row['pc'] = None if current is None else {**origin, 'bytes': len(current), 'sha256': digest(current)}
                row['read_errors'] = errors
                for entry in sources:
                    source = entry['path']
                    item = {**entry, 'path': str(source)}
                    try:
                        data = source.read_bytes()
                        item.update(bytes=len(data), sha256=digest(data), status='pc_unresolved' if current is None else 'identical' if current == data else 'different')
                        if current is not None and current != data and source.suffix.lower() in ('.lua', '.dnax', '.bent'):
                            try:
                                a, b = structured(current, source.suffix.lower()), structured(data, source.suffix.lower())
                                changes, truncated = differences(a, b, limit=100)
                                item['structured'] = {'equal': a == b, 'changes': changes, 'truncated': truncated,
                                                      'labels': 'pc=installation, wiiu=source folder (historical comparator labels only; not provenance)'}
                            except Exception as exc:
                                item['decode_error'] = str(exc)
                    except Exception as exc:
                        item.update(status='source_error', error=str(exc))
                    row['inputs'].append(item)
                rows.append(row)
                if number % 100 == 0:
                    print(f'  {number}/{len(selected)} files', flush=True)
            counts = Counter(i['status'] for row in rows for i in row['inputs'])
            stats = dict(character=char, paths=len(rows), **counts, overlaps=sum(r['installer_overlap'] for r in rows),
                         decode_errors=sum('decode_error' in i for r in rows for i in r['inputs']))
            result = {'scope': scope, 'summary': stats, 'files': rows,
                      'limitations': ['PC-only extra files are not enumerated.', 'Shared files not named for a character are listed separately, not assigned speculatively.',
                                      'Byte differences do not prove bugs or console provenance.', 'Motion curves and mesh geometry are hashed, not fully evaluated.',
                                      'Installer overlap winners and QuickBMS integration effects are not simulated.']}
            temporary = dest.with_suffix('.json.tmp')
            temporary.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
            temporary.replace(dest)
            md = [f'# {char}: source versus PC', '', str(stats), '', '| Resource | Result | Structured changes |', '|---|---|---|']
            for row in rows:
                status = ', '.join(i['status'] for i in row['inputs'])
                details = ', '.join('same decoded tables' if i.get('structured', {}).get('equal') else str(len(i['structured']['changes'])) + ' changes' for i in row['inputs'] if 'structured' in i)
                md.append(f"| `{row['logical']}` | {status} | {details} |")
            (out / (char + '.md')).write_text('\n'.join(md) + '\n', encoding='utf-8')
            summary.append(stats)
            (out / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
            print('  Saved: ' + str(stats), flush=True)
    finally:
        pc.close()
    shared = {k: [{**i, 'path': str(i['path'])} for i in v] for k, v in files.items()
              if not any(belongs(k, c) for c in chars)}
    (out / 'shared-source-map.json').write_text(json.dumps(shared, indent=2), encoding='utf-8')
    lines = ['# Character comparison batch', '', scope['note'], '',
             '| Character | Paths | Identical | Different | Unresolved PC | Decode errors |', '|---|---:|---:|---:|---:|---:|']
    for s in summary:
        lines.append(f"| [{s['character']}]({s['character']}.md) | {s['paths']} | {s.get('identical',0)} | {s.get('different',0)} | {s.get('pc_unresolved',0)} | {s['decode_errors']} |")
    (out / 'SUMMARY.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('Reports saved to: ' + str(out), flush=True)
    try:
        import winsound
        winsound.MessageBeep()
    except (ImportError, RuntimeError):
        pass


if __name__ == '__main__':
    main()
