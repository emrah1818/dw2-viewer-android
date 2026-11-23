"""DIGIMNDT evolution rules, following Digi_GetEvolutionTarget in gamedata.c.

18-byte record: rank at +4 high nibble, five DP bounds at +8, four u8
targets at +13. There is no per-species level threshold in these bytes.
"""
from .battle_skills import BaseTable, discover_tables


def target_for(bounds, targets, dp):
    if type(dp) is not int or not 0 <= dp <= 255:
        raise ValueError('DP muss zwischen 0 und 255 liegen.')
    if not targets[0]:
        return 0
    for i in range(4):
        if bounds[i + 1] == 0 or bounds[i] <= dp < bounds[i + 1]:
            return targets[i]
    raise ValueError('DP-Tabelle hat keinen sicheren Abschluss.')


class EvolutionRepository:
    def __init__(self, session, entries):
        self.session = session
        self.entry = discover_tables(session, entries, filenames=('DIGIMNDT.BIN',))['DIGIMNDT.BIN']

    def info(self, identifier):
        data = self.session.current(self.entry)
        table = BaseTable(data)
        if identifier not in table.records:
            raise ValueError('Digimon besitzt keinen DIGIMNDT-Eintrag.')
        offset = table.records[identifier][0]
        bounds, targets = list(data[offset+8:offset+13]), list(data[offset+13:offset+17])
        rows = []
        if targets[0]:
            for i, target in enumerate(targets):
                rows.append({'min_dp': bounds[i], 'target': target})
                if bounds[i+1] == 0:
                    break
            else:
                raise ValueError('Digitationstabelle ohne Abschluss; Bearbeitung wird verweigert.')
        return {'rank': data[offset+4] >> 4, 'dna_group': data[offset+3], 'rows': rows,
                'bounds': bounds, 'targets': targets,
                'choices': sorted(i for i in table.records if 1 <= i <= 255)}

    def change(self, identifier, rows, rank=None, dna_group=None):
        before = self.session.current(self.entry)
        table = BaseTable(before)
        self.info(identifier)
        if not isinstance(rows, list) or len(rows) > 4:
            raise ValueError('Höchstens vier Digitationsziele möglich.')
        bounds, targets = [0]*5, [0]*4
        last = -1
        for i, row in enumerate(rows):
            dp, target = row['min_dp'], row['target']
            if type(dp) is not int or not 0 <= dp <= 255 or dp <= last or (i == 0 and dp != 0):
                raise ValueError('DP-Grenzen müssen bei 0 beginnen und streng steigen (0–255).')
            if type(target) is not int or not 1 <= target <= 255 or target not in table.records or target == identifier:
                raise ValueError('Digitationsziel muss eine andere vorhandene 8-Bit-Digimon-ID sein.')
            bounds[i], targets[i], last = dp, target, dp
        offset = table.records[identifier][0]
        out = bytearray(before)
        out[offset+8:offset+13], out[offset+13:offset+17] = bytes(bounds), bytes(targets)
        if rank is not None:
            if type(rank) is not int or not 0 <= rank <= 3:
                raise ValueError('Stufe muss 0 (Rookie) bis 3 (Mega) sein.')
            out[offset+4] = (out[offset+4] & 15) | (rank << 4)
        if dna_group is not None:
            if type(dna_group) is not int or not 0 <= dna_group <= 255:
                raise ValueError('DNA-Gruppe muss 0–255 sein.')
            out[offset+3] = dna_group
        if out == before:
            return False
        for dp in range(256):
            target_for(bounds, targets, dp)
        self.session.stage(self.entry, out, f'Digitation / DP #{identifier:03}')
        return True


def change_line(repo, lines):
    """Several species' evolution rows in one step. LINES: [{'id', 'rows', 'rank'?, 'dna_group'?}].

    Every row set is checked first; nothing is staged unless all are valid. The final
    DIGIMNDT bytes go in as one edit, so one undo step reverts the whole line."""
    if not isinstance(lines, list) or not lines:
        raise ValueError('Mindestens ein Digimon der Linie angeben.')
    ids = [row.get('id') for row in lines]
    if len(set(ids)) != len(ids):
        raise ValueError('Jedes Digimon nur einmal pro Linie.')
    session, entry = repo.session, repo.entry
    original = session.edits.get((entry.path, entry.lba))
    staged = []
    try:
        for row in lines:
            if repo.change(row['id'], row.get('rows', []), row.get('rank'), row.get('dna_group')):
                staged.append(row['id'])
    except Exception:
        key = (entry.path, entry.lba)
        if original is None:
            session.edits.pop(key, None)
        else:
            session.edits[key] = original
        raise
    if staged:
        from dataclasses import replace
        key = (entry.path, entry.lba)
        session.edits[key] = replace(session.edits[key], label='Digitationslinie: ' + ', '.join(f'#{i:03}' for i in staged))
    return staged


def validate(repo):
    """Errors already present in the unchanged game data are reported as warnings ('original')."""
    now = _check(repo.session.current(repo.entry))
    try:
        orig = _check(repo.session.original(repo.entry))
    except Exception:
        orig = {'errors': []}
    known = {(e['id'], e['kind'], e.get('target')) for e in orig['errors']}
    keep = []
    for e in now['errors']:
        if (e['id'], e['kind'], e.get('target')) in known:
            now['warnings'].append(dict(e, original=True, text=e['text'] + ' (schon im Original)'))
        else:
            keep.append(e)
    now['errors'] = keep
    now['ok'] = not keep
    return now


def _check(data):
    """Check all DIGIMNDT evolution rows. Returns {'errors', 'warnings', 'info'} (lists of dicts).

    errors   – the game would misbehave: target without DIGIMNDT record, a species evolving into
               itself, a DP table without a safe end, a cycle (A > … > A).
    warnings – unusual, but valid: a target of the same or lower stage.
    info     – stage 1–3 species that no normal evolution reaches (DNA results, enemies only)."""
    table = BaseTable(data)
    errors, warnings, info = [], [], []
    graph, ranks = {}, {}
    for ident, (offset, _) in table.records.items():
        ranks[ident] = data[offset + 4] >> 4
    for ident, (offset, _) in sorted(table.records.items()):
        if not 1 <= ident <= 255:
            continue
        bounds, targets = list(data[offset + 8:offset + 13]), list(data[offset + 13:offset + 17])
        try:
            for dp in range(256):
                target_for(bounds, targets, dp)
        except ValueError as e:
            errors.append({'id': ident, 'kind': 'dp_table', 'text': str(e)})
            continue
        used = []
        if targets[0]:
            for i, t in enumerate(targets):
                used.append(t)
                if bounds[i + 1] == 0:
                    break
        graph[ident] = used
        for t in used:
            if t == ident:
                errors.append({'id': ident, 'kind': 'self', 'text': f'#{ident:03} digitiert in sich selbst.'})
            elif t not in table.records:
                errors.append({'id': ident, 'kind': 'missing', 'target': t,
                               'text': f'#{ident:03}: Ziel #{t:03} hat keinen DIGIMNDT-Eintrag.'})
            elif ranks[t] <= ranks[ident]:
                warnings.append({'id': ident, 'kind': 'stage', 'target': t,
                                 'text': f'#{ident:03} (Stufe {ranks[ident]}) > #{t:03} (Stufe {ranks[t]}): '
                                         'Ziel ist nicht höherstufig.'})
    # cycles: depth-first search over the evolution graph
    state, stack, seen_cycles = {}, [], set()

    def visit(n):
        state[n] = 1
        stack.append(n)
        for t in graph.get(n, ()):
            if t == n:
                continue
            if state.get(t) == 1:
                cyc = stack[stack.index(t):]
                key = frozenset(cyc)
                if key not in seen_cycles:
                    seen_cycles.add(key)
                    errors.append({'id': t, 'kind': 'cycle', 'cycle': cyc + [t],
                                   'text': 'Kreis: ' + ' > '.join(f'#{c:03}' for c in cyc + [t])})
            elif t in graph and not state.get(t):
                visit(t)
        stack.pop()
        state[n] = 2
    for n in sorted(graph):
        if not state.get(n):
            visit(n)
    reached = {t for ts in graph.values() for t in ts}
    for ident in sorted(graph):
        if ranks.get(ident, 0) > 0 and ident not in reached:
            info.append({'id': ident, 'kind': 'unreached',
                         'text': f'#{ident:03} (Stufe {ranks[ident]}) wird durch keine normale Digitation erreicht.'})
    return {'errors': errors, 'warnings': warnings, 'info': info, 'ok': not errors}
