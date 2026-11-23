"""DW3 motions -> DW2 battle actions: multi-part clips with loop ranges.

How DW2 plays its battle animations (dw2-pc-port, src/main/anim.c, src/stag3000/fighter.c, measured on
all 202 Digimon of the US game, see ANIMATIONSSYSTEM_0.96.md):
  one clip = rows of key indices (one row = one frame = 2 VBlanks, 30 per second), ended by 0xFF
  (hold the last frame) or 0xFE + a 16-bit row offset (jump back there: a loop). Either end sets
  animDone once; the game never waits for anything else, so a loop cannot block a battle.
  A0 standby          every turn               whole clip loops (202 of 202)
  B0 hit while guarding target chose Defend    once, then standby (202 hold)
  C0 / C1 hit, hops   during hop 1 / 2         loop (whole or a tail of ~6 frames)
  C2 landing          after the hops           once
  J0 getting up       after C2                 once, then standby
  K0 knocked out      after C2 when HP is 0    tail loop (mostly the last frame)
  F0 / G0 / H0 technique (Skill_GetCastAnim)   plays, then a tail loops until the next action
  I0 victory          battle won               plays, then a tail loops
How DW3 plays them (dw3_decomp src/battle/battle_mode: battle_script.c, model_mesh.c, face.c, menu.c,
hit_effect.c, move.c): an action is a script that starts motions one after the other, waiting for a
motion's end, a number of ticks or a jump; each motion ends by holding, by looping back to a keyframe,
or by blending into the idle motion. Script 0 idle (motion 1), 1 a hit that lands (flinch), 2 a hit
that knocks down (two jumps, landing, getting up), 3 a knockout, 4 a dodge, 5-8 the techniques,
9 the basic attack; motion 13 is the victory pose (menu.c, battle won).

An ACTION (one DW2 clip) is a dict:
  {'segments': [{'motion': id, 'start': frame, 'end': frame, 'repeat': n, 'blend': frames}],
   'end': 'hold' | 'loop', 'loop_segment': i, 'loop_frame': f (frame within that segment's range),
   'status': 'data' | 'auto' | 'manual' | 'open', 'reason': text}
Frames are the 30-per-second samples of native_source.json (frame i = DW3 keyframe 1 + 2 i).
"""
import math
from copy import deepcopy
import numpy as np

STATUS = {'data': 'Durch Daten bestätigt', 'auto': 'Automatisch erkannt', 'manual': 'Manuell zugeordnet',
          'open': 'Noch ungeklärt'}
# what the game does with each place (shown in the editor)
ROLES = {('A', 0): 'Standby', ('B', 0): 'Verteidigung (Treffer bei Abwehr)', ('C', 0): 'Fallen: erster Sprung',
         ('C', 1): 'Fallen: zweiter Sprung', ('C', 2): 'Liegen / Landung', ('F', 0): 'Attacke 1', ('G', 0): 'Attacke 2',
         ('H', 0): 'Attacke 3', ('I', 0): 'Sieg', ('J', 0): 'Aufstehen', ('K', 0): 'K.o.'}
JUMP_SPEED = {1: 136, 2: 102, 3: 81, 4: 64, 5: 64, 6: 42}   # FIGHTSTG_jumps (move.c)
VICTORY_MOTION = 13


def field_role(clip):
    # STAG4000 enemy.c: E0 (0x28) when standing, E1 (0x29) when moving.
    return {0: 'Domain / Feld: Standby', 1: 'Domain / Feld: Gehen'}.get(clip, f'Feld-Animation {clip}')


def field_defaults(source, places):
    """Field files are shared by logical A/D/E slots. Edit each physical clip once.
    DW3 locomotion is not guessed from a battle attack or motion number.
    """
    table = motion_table(source)
    idle = 1 if 1 in table else min(table)
    return {place: single(table, idle, 'data' if place[1] == 0 else 'open',
                          'Standby aus DW3' if place[1] == 0 else
                          'Feldbewegung noch nicht zugeordnet: Motion manuell wählen; vorläufig Standby')
            for place in places}


def jump_ticks(kind):
    """Ticks a DW3 jump takes (FIGHTSTG_updateJump: t from 2 * speed in steps of 2 * speed to 4096)."""
    s = 2 * JUMP_SPEED.get(kind, 64)
    return 2 * max(1, math.ceil((4096 - s) / s))


def motion_table(source):
    """{id: {'frames', 'end', 'loop_frame'}} from native_source.json (converter v8)."""
    out = {}
    for m in source['motions']:
        n = len(m['frames'])
        end = m.get('end', 'hold')
        lf = 0
        if end == 'loop':
            lf = min(n - 1, max(0, round((m.get('loop_key', 1) - 1) / 2)))
        # DW3 opens most motions with a blend from whatever pose shows (lead_blend keyframes, no source
        # frame of their own); frame i shows keyframe 1 + 2 i, so the first LEAD frames are that blend
        lead_keys = int(m.get('lead_blend', 0) or 0)
        lead = min(n - 1, lead_keys // 2) if lead_keys >= 2 else 0
        out[m['id']] = {'frames': n, 'end': end, 'loop_frame': lf, 'lead': lead, 'lead_keys': lead_keys}
    return out


def _segments_for(table, motion, ticks, idle=1):
    """The frames MOTION shows over TICKS ticks from its start, as segments (DW3 rules: hold, loop,
    or blend into idle and go on with the idle motion)."""
    info = table.get(motion)
    if info is None or ticks <= 0:
        return []
    n_frames = max(1, math.ceil(ticks / 2))
    N, out = info['frames'], []
    if n_frames <= N:
        return [{'motion': motion, 'start': 0, 'end': n_frames - 1, 'repeat': 1}]
    out.append({'motion': motion, 'start': 0, 'end': N - 1, 'repeat': 1})
    rest = n_frames - N
    if info['end'] == 'loop':
        lf = info['loop_frame']
        L = N - lf
        if rest // L:
            out.append({'motion': motion, 'start': lf, 'end': N - 1, 'repeat': rest // L})
        if rest % L:
            out.append({'motion': motion, 'start': lf, 'end': lf + rest % L - 1, 'repeat': 1})
    elif info['end'] == 'idle' and motion != idle and idle in table:
        out += _segments_for(table, idle, 2 * rest, idle)
    else:
        out.append({'motion': motion, 'start': N - 1, 'end': N - 1, 'repeat': rest})
    return out


def timeline(steps, table):
    """Simulate a DW3 script for its own model. Returns (parts, hits): parts = [(motion, ticks,
    jump_index or None)], the motions in the order they show with how long each shows; the last part
    has ticks None (it goes on after the script). hits = ticks at which hits land."""
    t, cur, start, jump_end, jumps, jump_of = 0, None, 0, 0, 0, None
    parts, hits = [], []
    for st in steps:
        op = st[0]
        if op == 'm':
            if cur is not None and t > start:
                parts.append((cur, t - start, jump_of))
            cur, start, jump_of = st[1], t, (jumps if jump_end > t else None)
        elif op == 'w':
            t += max(0, int(st[1]))
        elif op == 'wm':
            info = table.get(cur)
            if info and info['end'] != 'loop':
                t = max(t, start + 2 * info['frames'])
        elif op == 'j':
            jumps += 1
            jump_end = t + jump_ticks(st[1])
            if cur is not None and start == t:
                jump_of = jumps
        elif op == 'wj':
            t = max(t, jump_end)
        elif op == 'hit':
            hits.append(t)
    if cur is not None:
        parts.append((cur, None, jump_of))
    return parts, hits


def _tail(table, motion, idle=1):
    """Segments + loop for the motion that goes on after a script ends."""
    info = table[motion]
    segs = [{'motion': motion, 'start': 0, 'end': info['frames'] - 1, 'repeat': 1}]
    if info['end'] == 'loop':
        return segs, 'loop', 0, info['loop_frame']
    if info['end'] == 'idle' and motion != idle and idle in table:
        segs.append({'motion': idle, 'start': 0, 'end': table[idle]['frames'] - 1, 'repeat': 1})
        return segs, 'loop', 1, table[idle]['loop_frame']
    return segs, 'hold', 0, 0


def from_script(steps, table, status, reason, idle=1):
    """A whole DW3 script as one DW2 action: every motion in order with its timing, then the motion
    the script leaves playing (looping where DW3 loops, or the idle motion after a blend)."""
    parts, _ = timeline(steps, table)
    parts = [p for p in parts if p[0] in table]
    if not parts:
        return None
    segs = []
    for motion, ticks, _ in parts[:-1]:
        segs += _segments_for(table, motion, ticks, idle)
    tail, end, li, lf = _tail(table, parts[-1][0], idle)
    loop_segment = len(segs) + li
    segs += tail
    return {'segments': segs, 'end': end, 'loop_segment': loop_segment, 'loop_frame': lf,
            'status': status, 'reason': reason}


def single(table, motion, status, reason, end=None, idle=1):
    """One whole motion; END None = as DW3 ends it."""
    if motion not in table:
        return None
    if end is None:
        segs, e, li, lf = _tail(table, motion, idle)
        return {'segments': segs, 'end': e, 'loop_segment': li, 'loop_frame': lf, 'status': status, 'reason': reason}
    n = table[motion]['frames']
    return {'segments': [{'motion': motion, 'start': 0, 'end': n - 1, 'repeat': 1}], 'end': end,
            'loop_segment': 0, 'loop_frame': 0 if end == 'loop' else n - 1, 'status': status, 'reason': reason}


def last_frame(table, motion, status, reason):
    if motion not in table:
        return None
    n = table[motion]['frames']
    return {'segments': [{'motion': motion, 'start': n - 1, 'end': n - 1, 'repeat': 1}], 'end': 'hold',
            'loop_segment': 0, 'loop_frame': 0, 'status': status, 'reason': reason}


def _steps(scripts, i):
    return scripts[i].get('steps') or [] if i < len(scripts) else []


def defaults(source, scripts, places):
    """{(slot, clip): action} for PLACES (the target's (slot, clip) list)."""
    table = motion_table(source)
    idle = 1 if 1 in table else min(table)
    out = {}
    standby = single(table, idle, 'data', 'Standby: DW3-Skript 0, Motion %d (DW3 wiederholt sie ganz)' % idle)
    out[('A', 0)] = standby
    if scripts:
        # B: DW3 has no guard; a hit that lands without knocking down (script 1) is the closest
        s1 = [st[1] for st in _steps(scripts, 1) if st[0] == 'm']
        if s1:
            out[('B', 0)] = single(table, s1[0], 'auto', f'DW3 kennt keine Verteidigung. Nächste Entsprechung: Treffer '
                                   f'ohne Umfallen (DW3-Skript 1, Motion {s1[0]})', end='hold')
        # C / J: script 2 (knocked down, gets up); jumps 1 and 2 are DW2's hops
        parts, _ = timeline(_steps(scripts, 2), table)
        parts = [p for p in parts if p[0] in table]
        if parts:
            getup = parts[-1][0]
            fall = parts[:-1]
            out[('J', 0)] = single(table, getup, 'data', f'Aufstehen: letzte Motion von DW3-Skript 2 (Motion {getup})',
                                   end='hold')
            by_jump = {}
            for motion, ticks, j in fall:
                if j is not None:
                    by_jump.setdefault(j, motion)
            landing = [m for m, t, j in fall if j is None and m not in by_jump.values()]
            if len(by_jump) >= 2:
                j1, j2 = sorted(by_jump)[:2]
                out[('C', 0)] = single(table, by_jump[j1], 'data', f'Erster Sprung beim Fallen: DW3-Skript 2, Motion {by_jump[j1]}')
                out[('C', 1)] = single(table, by_jump[j2], 'data', f'Zweiter Sprung: DW3-Skript 2, Motion {by_jump[j2]}')
            elif fall:
                first = fall[0][0]
                out[('C', 0)] = single(table, first, 'auto', f'Fallen: DW3-Skript 2, Motion {first} (DW3 springt '
                                       f'{"einmal" if by_jump else "nicht"}, DW2 zweimal)', end='hold')
                second = fall[1][0] if len(fall) > 1 else first
                out[('C', 1)] = (single(table, second, 'auto', f'Zweiter Sprung: DW3-Skript 2, Motion {second}', end='hold')
                                 if second != first else
                                 last_frame(table, first, 'auto', f'Zweiter Sprung: letztes Bild von Motion {first} '
                                            '(DW3 hat dafür keine eigene Motion)'))
            if landing and len(by_jump) >= 2:
                out[('C', 2)] = single(table, landing[-1], 'data', f'Landung: DW3-Skript 2, Motion {landing[-1]}', end='hold')
            elif fall:
                lm = fall[-1][0]
                out[('C', 2)] = last_frame(table, lm, 'auto', f'Liegen: letztes Bild von Motion {lm} (DW3-Skript 2)')
        # K: script 3 ends on the ground
        p3, _ = timeline(_steps(scripts, 3), table)
        p3 = [p for p in p3 if p[0] in table]
        if p3:
            out[('K', 0)] = single(table, p3[-1][0], 'data', f'K.o.: letzte Motion von DW3-Skript 3 (Motion {p3[-1][0]})')
        # F / G / H: the techniques, each one whole script, never mixed
        techs = [i for i in range(5, 9) if any(st[0] == 'm' for st in _steps(scripts, i))]
        for place, i in zip('FGH', techs):
            out[(place, 0)] = from_script(_steps(scripts, i), table, 'data',
                                          f'Technik: DW3-Skript {i} (alle Motions mit ihren Zeiten, danach wie in DW3)')
        missing = [p for p in 'FGH' if (p, 0) not in out]
        if missing and any(st[0] == 'm' for st in _steps(scripts, 9)):
            # only one place gets the basic attack: two places with the same motions would merge attacks
            out[(missing[0], 0)] = from_script(_steps(scripts, 9), table, 'auto',
                                               'Keine weitere DW3-Technik: Standardangriff (DW3-Skript 9)')
    # I: the victory motion (DW3 menu.c sets motion 13 when the battle is won)
    if VICTORY_MOTION in table and table[VICTORY_MOTION]['frames'] > 1:
        out[('I', 0)] = single(table, VICTORY_MOTION, 'data', 'Sieg: DW3 spielt Motion 13 nach einem gewonnenen Kampf '
                               '(danach wie in DW3 wiederholt)')
    for act in out.values():
        if act:
            _smooth_cuts(source, table, act)
    # DW2 plays C0 → C1 → C2 → J0 / K0 one after the other: their opening blend starts from the
    # pose the clip before ends on (the others start from standby)
    def last_pose(place):
        a = out.get(place)
        if a:
            s = a['segments'][-1]
            return [s['motion'], s['end']]
    for place, before in ((('C', 1), ('C', 0)), (('C', 2), ('C', 1)), (('J', 0), ('C', 2)), (('K', 0), ('C', 2))):
        if out.get(place) and last_pose(before):
            out[place]['enter'] = last_pose(before)
    result = {}
    for place in places:
        act = out.get(place)
        if act is None:
            act = dict(standby, status='open',
                       reason=f'Noch ungeklärt: {ROLES.get(place, "Feld-Animation, nicht im Kampf")}. Vorläufig Standby')
        result[place] = act
    return result


CUT_DEGREES, CUT_BLEND = 45., 4


def _smooth_cuts(source, table, act):
    """Where a script switches motions without DW3's own opening blend and the pose jumps by
    CUT_DEGREES or more (a camera cut in DW3, a visible jump in DW2's fixed view), ease over
    CUT_BLEND frames. Marked in the reason; the editor can take it out."""
    index = {m['id']: i for i, m in enumerate(source['motions'])}
    segs, added = act['segments'], []
    for i in range(1, len(segs)):
        a, b = segs[i - 1], segs[i]
        if b.get('blend') or b['start'] < table[b['motion']].get('lead', 0) or a['motion'] == b['motion']:
            continue
        d = joints(source, (index[a['motion']], a['end']), (index[b['motion']], b['start']))
        if d >= CUT_DEGREES:
            b['blend'] = CUT_BLEND
            added.append(f'{i}→{i + 1} ({round(d)}°)')
    if added:
        act['reason'] += f'. Übergang {CUT_BLEND} Bilder ergänzt, wo DW3 hart schneidet: ' + ', '.join(added)


def legacy(table, motion, loop):
    """0.95 assignment (one motion, whole-clip loop or hold) as an action."""
    n = table[motion]['frames']
    return {'segments': [{'motion': motion, 'start': 0, 'end': n - 1, 'repeat': 1}], 'end': 'loop' if loop else 'hold',
            'loop_segment': 0, 'loop_frame': 0, 'status': 'manual', 'reason': 'aus 0.95'}


def resolve_assignment(row, table):
    """Resolve simple motion/loop controls before a saved action can mask them.

    The explicit selector also covers choosing the *same* motion as the first
    part of an automatic multi-part action. Old clients have no selector; their
    changed motion/loop fields still take precedence over stale action data.
    Legacy rows without actions keep the byte-identical 0.95 encoding path.
    """
    row = deepcopy(row)
    action = row.get('action')
    explicit = row.pop('selection', None) == 'motion'
    changed_motion = (isinstance(action, dict) and action.get('segments') and
                      'motion' in row and row['motion'] != action['segments'][0].get('motion'))
    if explicit or changed_motion:
        mid = row.get('motion')
        if type(mid) is not int or mid not in table:
            raise ValueError('Unbekannte DW3-Motion.')
        loop = row.get('loop')
        if type(loop) is not bool:
            raise ValueError('Schleife muss ein-/ausgeschaltet sein.')
        reason = f'Manuell gewählt: DW3-Motion {mid}'
        chosen = single(table, mid, 'manual', reason)
        if not loop:
            chosen = single(table, mid, 'manual', reason, end='hold')
            # Keep the selected motion's real loop point for a later re-enable.
            # A hold action's default last-frame marker is not a DW3 loop point.
            chosen['loop_frame'] = table[mid]['loop_frame'] if table[mid]['end'] == 'loop' else 0
        elif chosen['end'] != 'loop':
            chosen = single(table, mid, 'manual', reason, end='loop')
        if isinstance(action, dict) and action.get('enter') is not None:
            chosen['enter'] = action['enter']
        action = chosen
    elif isinstance(action, dict) and 'loop' in row:
        if type(row['loop']) is not bool:
            raise ValueError('Schleife muss ein-/ausgeschaltet sein.')
        if row['loop'] != (action.get('end') == 'loop'):
            action['end'] = 'loop' if row['loop'] else 'hold'
            # Keep a previously configured loop range when toggling it back on.
            action.setdefault('loop_segment', 0)
            action.setdefault('loop_frame', action['segments'][action['loop_segment']]['start'])
            action['status'] = 'manual'
            action['reason'] = 'Schleife manuell geändert'
    if isinstance(action, dict):
        validate(action, table)
        row.update(action=action, motion=action['segments'][0]['motion'], loop=action['end'] == 'loop')
    return row


def validate(action, table):
    """Raises ValueError with a German message for an action the encoder cannot build."""
    segs = action.get('segments')
    if not isinstance(segs, list) or not segs or len(segs) > 64:
        raise ValueError('Aktion braucht 1–64 Abschnitte.')
    for i, s in enumerate(segs):
        m = s.get('motion')
        if m not in table:
            raise ValueError(f'Abschnitt {i + 1}: unbekannte Motion {m}.')
        n = table[m]['frames']
        a, b = s.get('start'), s.get('end')
        if type(a) is not int or type(b) is not int or not 0 <= a <= b < n:
            raise ValueError(f'Abschnitt {i + 1}: Bilder {a}–{b} außerhalb von Motion {m} (0–{n - 1}).')
        r = s.get('repeat', 1)
        if type(r) is not int or not 1 <= r <= 99:
            raise ValueError(f'Abschnitt {i + 1}: Wiederholungen 1–99.')
        bl = s.get('blend', 0)
        if type(bl) is not int or not 0 <= bl <= 30:
            raise ValueError(f'Abschnitt {i + 1}: Übergang 0–30 Bilder.')
    en = action.get('enter')
    if en is not None and not (isinstance(en, (list, tuple)) and len(en) == 2 and en[0] in table
                               and type(en[1]) is int and 0 <= en[1] < table[en[0]]['frames']):
        raise ValueError('Einstiegspose ungültig.')
    if action.get('end') not in ('hold', 'loop'):
        raise ValueError('Ende: halten oder wiederholen.')
    if action['end'] == 'loop':
        li, lf = action.get('loop_segment'), action.get('loop_frame')
        if type(li) is not int or not 0 <= li < len(segs):
            raise ValueError('Loop-Abschnitt fehlt.')
        s = segs[li]
        if type(lf) is not int or not s['start'] <= lf <= s['end']:
            raise ValueError(f'Loop-Beginn {lf} liegt nicht im Abschnitt {li + 1} ({s["start"]}–{s["end"]}).')


def frames_of(action, table=None):
    """[(motion, frame, blend_from or None, weight)] in play order, and the row the loop goes back to
    (None = hold). A segment's BLEND frames ease from the previous segment's last pose into its first.
    With TABLE, the opening blend DW3 gives a motion (motion_table 'lead') starts from the pose that
    actually shows when the segment starts: blend_from is then ('row', index of that row) or
    ('idle', None) at the start of the action (DW2 enters every action from standby)."""
    rows, loop_row = [], None
    for i, s in enumerate(action['segments']):
        bl = s.get('blend', 0)
        info = (table or {}).get(s['motion']) or {}
        lead, keys = info.get('lead', 0), info.get('lead_keys', 0)
        if bl and rows:
            # The preceding row may itself be blended. Use its displayed matrix,
            # not the unblended source pose recorded in its first two fields.
            prev = ('row', len(rows) - 1)
            for k in range(bl):
                rows.append((s['motion'], s['start'], prev, (k + 1) / (bl + 1)))
        for rep in range(s.get('repeat', 1)):
            enter = action.get('enter')
            anchor = (('row', len(rows) - 1) if rows else
                      (int(enter[0]), int(enter[1])) if enter else ('idle', None))
            for f in range(s['start'], s['end'] + 1):
                if action['end'] == 'loop' and i == action['loop_segment'] and rep == 0 and f == action['loop_frame']:
                    loop_row = len(rows)
                if f < lead and not bl:
                    rows.append((s['motion'], lead, anchor, (2 * f + 2) / (keys + 1)))
                else:
                    rows.append((s['motion'], f, None, 1.0))
    if action['end'] == 'loop' and loop_row is None:
        loop_row = 0
    return rows, loop_row


def joints(source, a, b):
    """Largest bone rotation change (degrees) between pose A and pose B ((motion index, frame))."""
    from .core.dw3_native import source_matrices
    ma, mb = source_matrices(source, a[0])[a[1]], source_matrices(source, b[0])[b[1]]
    worst = 0.
    for x, y in zip(ma[1:], mb[1:]):
        r = x[:3, :3].T @ y[:3, :3]
        nx = np.linalg.norm(x[:3, :3], axis=0); ny = np.linalg.norm(y[:3, :3], axis=0)
        if nx.min() < 1e-6 or ny.min() < 1e-6:
            continue
        r = (x[:3, :3] / nx).T @ (y[:3, :3] / ny)
        c = max(-1., min(1., (np.trace(r) - 1) / 2))
        worst = max(worst, math.degrees(math.acos(c)))
    return worst


def transitions(source, action, threshold=25.):
    """Pose jumps of an action: between its segments and at the loop. [{'at', 'degrees', 'where'}]."""
    index = {m['id']: i for i, m in enumerate(source['motions'])}
    table = motion_table(source)
    segs, out = action['segments'], []
    for i in range(1, len(segs)):
        if segs[i].get('blend'):
            continue
        a, b = segs[i - 1], segs[i]
        if b['start'] < table.get(b['motion'], {}).get('lead', 0):
            continue                      # DW3 blends into it from the pose that shows
        d = joints(source, (index[a['motion']], a['end']), (index[b['motion']], b['start']))
        if d >= threshold:
            out.append({'at': i, 'degrees': round(d), 'where': f'Abschnitt {i} → {i + 1}'})
        for k in range(1, b.get('repeat', 1) if b['start'] != b['end'] else 1):
            d2 = joints(source, (index[b['motion']], b['end']), (index[b['motion']], b['start']))
            if d2 >= threshold:
                out.append({'at': i, 'degrees': round(d2), 'where': f'Wiederholung in Abschnitt {i + 1}'})
            break
    if action['end'] == 'loop':
        last, s = segs[-1], segs[action['loop_segment']]
        d = joints(source, (index[last['motion']], last['end']), (index[s['motion']], action['loop_frame']))
        if d >= threshold and action['loop_frame'] >= table.get(s['motion'], {}).get('lead', 0):
            out.append({'at': len(segs), 'degrees': round(d), 'where': 'Loop-Rücksprung'})
    return out
