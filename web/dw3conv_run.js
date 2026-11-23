// DW3-Konverter (third_party/dw3_converter, als WebAssembly gebaut) im Web Worker ausführen.
// Python (Pyodide) ruft dw3convRun synchron auf; Ein- und Ausgabedateien werden zwischen dem
// Pyodide-Dateisystem (SRC) und dem eigenen Dateisystem des Konverters kopiert.
// Jeder Aufruf bekommt eine frische Konverter-Instanz (kein Zustand zwischen zwei Läufen).
(function (root) {
  function dirname(p) { const i = p.lastIndexOf('/'); return i > 0 ? p.slice(0, i) : '/'; }
  function isFile(fs, p) { try { const a = fs.analyzePath(p); return a.exists && fs.isFile(a.object.mode); } catch { return false; } }
  function exists(fs, p) { try { return fs.analyzePath(p).exists; } catch { return false; } }
  function copyTree(from, to, p) {
    const mode = from.stat(p).mode;
    if (from.isDir(mode)) {
      to.mkdirTree(p);
      for (const n of from.readdir(p)) if (n !== '.' && n !== '..') copyTree(from, to, p + '/' + n);
    } else {
      to.mkdirTree(dirname(p));
      to.writeFile(p, from.readFile(p));
    }
  }
  function dw3convRun(create, src, args) {
    let stdout = '', stderr = '';
    const m = create({ print: s => { stdout += s + '\n'; }, printErr: s => { stderr += s + '\n'; } });
    const fresh = [];
    for (const a of args) {
      if (typeof a !== 'string' || !a.startsWith('/')) continue;
      if (isFile(src, a)) { m.FS.mkdirTree(dirname(a)); m.FS.writeFile(a, src.readFile(a)); }
      else if (!exists(src, a)) { m.FS.mkdirTree(dirname(a)); fresh.push(a); }
    }
    let code;
    try { code = m.callMain(args.map(String)); }
    catch (e) { if (e && e.name === 'ExitStatus') code = e.status; else { stderr += String(e && e.message || e); code = 5; } }
    for (const p of fresh) if (exists(m.FS, p)) copyTree(m.FS, src, p);
    return { returncode: code | 0, stdout, stderr };
  }
  root.dw3convRun = dw3convRun;
  if (typeof module !== 'undefined') module.exports = { dw3convRun };
})(typeof self !== 'undefined' ? self : globalThis);
