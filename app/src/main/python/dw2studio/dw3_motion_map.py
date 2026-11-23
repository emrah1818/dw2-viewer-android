"""Default DW3 motion for each DW2 animation place, from what both games' code does with them.

DW2 (dw2-pc-port, src/stag0000/digimodel.c, the battle model; Anim_SetModelAnim(actor, 10 * place + clip)):
  A0 (0)    Stg00_DigiModelTask: on entering and after a technique, battle standby
  C0 (0x14) Stg00_HitReactUpdate step 0: hit, first hop (Stg00_HitReactHop1Motion)
  C1 (0x15) step 1: hit, second hop
  C2 (0x16) step 2: landing, played once
  K0 (0x64) step 3: knocked down, then 90 frames on the ground
  J0 (0x5A) step 4: getting up, then back to standby
  F0/G0/H0 (0x32/0x3C/0x46) state 10: the technique's cast motion (Skill_GetCastAnim 0/1/2)
  B0 (0x0A), I0 (0x50) and the field places: not tied to a battle action here -> standby.
DW3 (dw3_decomp; the scripts read with third_party/dw3_converter --scripts):
  script 0 plays the idle motion; the hit effect runs script result + 1 (effect.h: result 1 a hit,
  2 a knockout): script 2 = hit, ending standing; script 3 = knockout, ending on the ground;
  scripts 5..8 are the techniques (techs.c, TechData.script); "strike" is the motion playing when
  the script's first hit line runs.
Every default carries its reason; the user can change each one in the dialog.
"""

STANDBY = 'Standby (DW3-Skript 0)'


def _motions(scripts, index):
    return scripts[index]['motions'] if index < len(scripts) else []


def defaults(scripts):
    """{(place, clip): (motion, reason)} for the places this mapping knows."""
    if not scripts:
        return {}
    idle = (_motions(scripts, 0) or [1])[0]
    out = {('A', 0): (idle, STANDBY), ('B', 0): (idle, STANDBY + ', Bedeutung in DW2 nicht belegt'),
           ('I', 0): (idle, STANDBY + ', Bedeutung in DW2 nicht belegt')}
    hit, knockout = _motions(scripts, 2), _motions(scripts, 3)
    if len(hit) >= 2:
        sequence = hit[:-1]
        out[('C', 0)] = (sequence[0], 'Treffer, erste Motion (DW3-Skript 2)')
        out[('C', 1)] = (sequence[min(1, len(sequence) - 1)], 'Treffer, zweite Motion (DW3-Skript 2)')
        out[('C', 2)] = (sequence[-1], 'Treffer, letzte Motion vor dem Aufstehen (DW3-Skript 2)')
        out[('J', 0)] = (hit[-1], 'Aufstehen nach Treffer (DW3-Skript 2, Ende)')
    if knockout:
        out[('K', 0)] = (knockout[-1], 'K.o., liegend (DW3-Skript 3, Ende)')
    strikes = [s.get('strike', 0) for s in scripts[5:9] if s.get('strike', 0) > 0]
    for k, place in enumerate('FGH'):
        if strikes:
            pick = strikes[min(k, len(strikes) - 1)]
            number = 5 + [s.get('strike', 0) for s in scripts[5:9]].index(pick)
            out[(place, 0)] = (pick, f'Angriff, Motion beim ersten Treffer (DW3-Skript {number}, Technik)')
    return out


def apply_defaults(assignments, scripts, valid):
    """Fill each assignment's motion and reason; VALID: the motion numbers the model has."""
    table = defaults(scripts)
    for row in assignments:
        motion, reason = table.get((row['slot'], row['clip']), (None, None))
        if motion is None or motion not in valid:
            motion, reason = (1 if 1 in valid else min(valid)), ('Standby (Vorgabe)' if scripts else
                                                                 'Keine DW3-Kampfskripte: Vorgabe Motion 1')
        row['motion'], row['reason'] = motion, reason
    return assignments
