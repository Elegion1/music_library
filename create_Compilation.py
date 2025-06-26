import os
import re
import shutil
import sqlite3
import difflib
import unicodedata
import json

try:
    from mutagen import File as MutagenFile
except ImportError:
    MutagenFile = None

# CONFIG
MUSIC_FOLDER = "/Volumes/NAS/Media/Music"  # o prendi il valore dalla GUI
DB_FILENAME = "music_library.db"
DB_PATH_MUSIC = os.path.join(MUSIC_FOLDER, DB_FILENAME)
DB_PATH_LOCAL = os.path.join(os.path.dirname(__file__), DB_FILENAME)

if os.path.exists(DB_PATH_MUSIC):
    DB_PATH = DB_PATH_MUSIC
else:
    DB_PATH = DB_PATH_LOCAL

SECOND_FOLDER = "/Volumes/Incoming"
COMPILATIONS_FILE = "compilations.json"

def load_compilations():
    if os.path.exists(COMPILATIONS_FILE):
        with open(COMPILATIONS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_compilations(compilations):
    with open(COMPILATIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(compilations, f, ensure_ascii=False, indent=2)

def normalize(s):
    s = s.lower().replace("’", "'").replace("`", "'").replace("‘", "'").replace("-", " ").replace("_", " ").strip()
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r'[^a-z0-9 ]', '', s)  # rimuove tutto tranne lettere, numeri e spazi
    return s

def find_all_matches_db(conn, artist, title):
    cur = conn.cursor()
    cur.execute("SELECT path, filename, duration, size, bitrate, album FROM tracks")
    rows = cur.fetchall()
    candidates = []
    for row in rows:
        path, filename, duration, size, bitrate, album = row
        fname = normalize(filename)
        if normalize(artist) in fname and normalize(title) in fname:
            score = difflib.SequenceMatcher(None, normalize(title), fname).ratio()
            candidates.append((score, path, filename, duration, size, bitrate, album))
    if not candidates:
        return []
    candidates.sort(key=lambda x: (x[0], x[4]), reverse=True)
    return candidates

def find_all_matches_folder(folder, artist, title):
    matches = []
    for root, dirs, files in os.walk(folder):
        for file in files:
            fname = normalize(file)
            if normalize(artist) in fname and normalize(title) in fname:
                path = os.path.join(root, file)
                size = os.path.getsize(path)
                duration = 0
                album = ""
                bitrate = 0
                if MutagenFile:
                    try:
                        audio = MutagenFile(path)
                        duration = int(audio.info.length) if audio and audio.info else 0
                        album_tag = audio.tags.get('TALB') if audio and audio.tags else None
                        if album_tag:
                            album = album_tag.text[0] if hasattr(album_tag, 'text') else str(album_tag)
                        bitrate = getattr(audio.info, 'bitrate', 0) if audio and audio.info else 0
                    except Exception:
                        pass
                matches.append((1.0, path, file, duration, size, bitrate, album))
    return matches

def run_compilation_process(dest_base, compilation_name, tracklist, progress_callback=None, choice_callback=None):
    """
    Crea una compilation copiando i brani trovati in una nuova cartella.
    Args:
        dest_base (str): Cartella di destinazione base.
        compilation_name (str): Nome della compilation.
        tracklist (list): Lista di tuple (artista, titolo).
        progress_callback (callable): funzione (current, total, status) per aggiornare la GUI.
        choice_callback (callable): funzione (artist, title, matches) per scelta utente in caso di più versioni.
    Returns:
        tuple: (not_found_tracks, not_copied_tracks)
    """
    DEST_FOLDER = os.path.join(dest_base, compilation_name)
    os.makedirs(DEST_FOLDER, exist_ok=True)

    all_found_matches = []  # (index, artist, title, matches)
    not_found_tracks = []
    selected_tracks_to_copy = []

    conn = sqlite3.connect(DB_PATH)

    # Fase 1: Ricerca brani
    if progress_callback:
        progress_callback(0, len(tracklist), "Ricerca brani...")

    for i, (artist, title) in enumerate(tracklist, 1):
        if progress_callback:
            progress_callback(i, len(tracklist), f"Ricerca: {artist} - {title}")

        matches = find_all_matches_db(conn, artist, title)
        if not matches:
            matches = find_all_matches_folder(SECOND_FOLDER, artist, title)

        if matches:
            all_found_matches.append((i, artist, title, matches))
        else:
            not_found_tracks.append(f"{artist} - {title}")
    conn.close()

    # Fase 2: Scelta versione (se necessario)
    selected_paths = []

    for i, artist, title, matches in all_found_matches:
        selected_path = None
        if len(matches) == 1:
            selected_path = matches[0][1]
        elif choice_callback:
            selected_path = choice_callback(artist, title, matches)
        else:
            selected_path = matches[0][1]

        selected_paths.append(selected_path)

        if selected_path:
            sel = next((m for m in matches if m[1] == selected_path), None)
            if sel:
                ext = os.path.splitext(sel[2])[1]
                new_name = f"{i}. {artist} - {title}{ext}"
                dest_path = os.path.join(DEST_FOLDER, new_name)
                selected_tracks_to_copy.append((selected_path, dest_path))

    # Fase 3: Copia file
    not_copied_tracks = []
    if progress_callback:
        progress_callback(0, len(selected_tracks_to_copy), "Copia files...")

    for i, (src, dst) in enumerate(selected_tracks_to_copy, 1):
        if progress_callback:
            progress_callback(i, len(selected_tracks_to_copy), f"Copiando: {os.path.basename(dst)}")
        try:
            shutil.copy2(src, dst)
        except FileNotFoundError:
            not_copied_tracks.append(os.path.basename(dst) + " (File not found)")
        except Exception as e:
            not_copied_tracks.append(os.path.basename(dst) + f" (Error: {e})")

    # Fase 4: Scrivi tracklist
    tracklist_path = os.path.join(DEST_FOLDER, "tracklist.txt")
    with open(tracklist_path, "w", encoding="utf-8") as f:
        for i, (artist, title) in enumerate(tracklist, 1):
            f.write(f"{i}. {artist} - {title}\n")

    return not_found_tracks, not_copied_tracks, selected_paths

# Il modulo non deve eseguire nulla se importato
if __name__ == "__main__":
    print("Questo modulo fornisce solo funzioni di logica. Usalo tramite gui_compilation_creator.py.")