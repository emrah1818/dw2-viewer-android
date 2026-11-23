"""Language of the native desktop parts (menus, file dialogs, message boxes).

The default follows the system language: German systems get German, every other system
English. The web interface makes the same choice (navigator.language) and reports a manual
change through the bridge method set_language."""
_EN = {
    'PC-Werkzeuge': 'PC tools',
    'Mod Studio · 3D-Import / Rigging / Vollfarben': 'Mod Studio · 3D import / rigging / full colour',
    'Vollbild': 'Full screen',
    'Vorgang läuft': 'Operation running',
    'Bitte den laufenden Vorgang abschließen lassen.': 'Please let the running operation finish.',
    'Ungespeicherte Änderungen': 'Unsaved changes',
    'Schließen und vorgemerkte Änderungen verwerfen? Zum Sichern abbrechen und ein Mod-Projekt speichern.':
        'Close and discard queued changes? To keep them, cancel and save a mod project.',
    'HD-PNG wählen (z. B. 512×1024)': 'Choose HD PNG (e.g. 512×1024)',
    'PC-Port-Ordner wählen': 'Choose PC-port folder',
    'Keine Änderungen vorgemerkt.': 'No changes queued.',
    'Passende dw2.pak wählen': 'Choose the matching dw2.pak',
    'PC-Port-Ordner mit dw2.exe wählen': 'Choose the PC-port folder with dw2.exe',
    'Unbekannte Mod-Aktion.': 'Unknown mod action.',
    'Unbekannter Dateidialog.': 'Unknown file dialog.',
    'Image wechseln': 'Change image',
    'Vorgemerkte Änderungen verwerfen und ein anderes Image öffnen?': 'Discard queued changes and open another image?',
    'Datei öffnen': 'Open file',
    'Datei speichern': 'Save file',
    'Alle Dateien': 'All files',
    'Modelle / Texturen': 'Models / textures',
    'DW2 Mod-Projekt': 'DW2 mod project',
    'Spielstand / Memory Card': 'Save file / memory card',
    'Bitte einen anderen Zielpfad wählen.': 'Please choose a different target path.',
    'Für das Original-Image bitte „Original überschreiben“ verwenden.': 'For the original image please use “Overwrite original”.',
    'Zieldatei wurde inzwischen verändert.': 'The target file has changed in the meantime.',
}


def system_language():
    try:
        from PyQt6.QtCore import QLocale
        langs = QLocale.system().uiLanguages()
        first = (langs[0] if langs else QLocale.system().name()).lower()
    except Exception:
        import locale
        first = (locale.getlocale()[0] or '').lower()
    return 'de' if first.startswith('de') else 'en'


LANG = None


def lang():
    global LANG
    if LANG is None:
        LANG = system_language()
    return LANG


def set_language(value):
    global LANG
    if value in ('de', 'en'):
        LANG = value
    return lang()


def tr(text):
    return _EN.get(text, text) if lang() == 'en' else text
