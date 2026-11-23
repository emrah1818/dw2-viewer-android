/** DW3 catalog search; keep the rules in sync with dw2studio/dw3_names.py. */
const norm = x => String(x ?? '').normalize('NFKC').toLowerCase().replace(/[^\p{L}\p{N}]/gu, '');

export function dw3Matches(m, query) {
  const q = String(query ?? '').trim();
  if (!q) return true;
  // Numeric queries select exact IDs, rather than substrings of a file name.
  const num = q.replace(/^#/, '');
  if (/^\d+$/.test(num)) return [m.id, m.file_number, ...(m.fighter_ids || [])].includes(Number(num));
  const nq = norm(q);
  return !!nq && [m.digimon, m.raw_name, m.code, m.file, m.name, ...(m.aliases || [])]
    .some(h => norm(h).includes(nq));
}

export function dw3Rank(m, query) {
  const nq = norm(query), names = [m.digimon || m.name, ...(m.aliases || [])].map(norm);
  return !nq || names.includes(nq) ? 0 : names.some(n => n.startsWith(nq)) ? 1 : 2;
}
