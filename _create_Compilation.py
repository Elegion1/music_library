import os
import shutil
import sqlite3
import difflib
from tqdm import tqdm
from difflib import SequenceMatcher
import unicodedata
import json
try:
    from mutagen import File as MutagenFile
except ImportError:
    MutagenFile = None

# CONFIG
DB_PATH = "music_library.db"
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

compilations = load_compilations()

# --- SCELTA COMPILATION SALVATA O NUOVA ---
use_saved = False
if compilations:
    print("Compilazioni salvate:")
    for idx, comp in enumerate(compilations, 1):
        print(f"{idx}) {comp['name']} ({comp['dest_base']}/{comp['name']}) [{len(comp['tracklist'])} brani]")
    scelta = input("Vuoi usare una compilation salvata? (numero, invio per nuova): ").strip()
    if scelta.isdigit() and 1 <= int(scelta) <= len(compilations):
        comp = compilations[int(scelta)-1]
        dest_base = comp['dest_base']
        compilation_name = comp['name']
        TRACKLIST = comp['tracklist']
        use_saved = True

if not use_saved:
    print("=== CREAZIONE COMPILATION ===")
    dest_base = input("Percorso di destinazione (es: /Users/gionnymiele/Desktop): ").strip()
    compilation_name = input("Nome cartella compilation: ").strip()

    scelta_input = input("Vuoi inserire i brani da terminale (T) o caricare da file txt (F)? [T/F]: ").strip().lower()
    TRACKLIST = []

    if scelta_input == "f":
        txt_path = input("Percorso del file txt (una riga per brano, formato: Artista - Titolo): ").strip()
        with open(txt_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                if " - " in line:
                    artist, title = line.split(" - ", 1)
                    TRACKLIST.append((artist.strip(), title.strip()))
                else:
                    print(f"Formato non valido nella riga: {line}")
    else:
        print("\nInserisci le canzoni (formato: Artista - Titolo), una per riga. Lascia vuoto per terminare:")
        while True:
            line = input()
            if not line.strip():
                break
            if " - " in line:
                artist, title = line.split(" - ", 1)
                TRACKLIST.append((artist.strip(), title.strip()))
            else:
                print("Formato non valido. Usa: Artista - Titolo")

    # Salva la nuova compilation
    compilations.append({
        "dest_base": dest_base,
        "name": compilation_name,
        "tracklist": TRACKLIST
    })
    save_compilations(compilations)

DEST_FOLDER = os.path.join(dest_base, compilation_name)
os.makedirs(DEST_FOLDER, exist_ok=True)

def normalize(s):
    s = s.lower().replace("’", "'").replace("`", "'").replace("‘", "'").replace("-", " ").replace("_", " ").strip()
    # Rimuove accenti e caratteri speciali
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(c for c in s if not unicodedata.combining(c))
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
                if MutagenFile:
                    try:
                        audio = MutagenFile(path)
                        duration = int(audio.info.length) if audio and audio.info else 0
                        album_tag = audio.tags.get('TALB') if audio and audio.tags else None
                        if album_tag:
                            album = album_tag.text[0] if hasattr(album_tag, 'text') else str(album_tag)
                    except Exception:
                        pass
                matches.append((1.0, path, file, duration, size, 0, album))
    return matches

# --- RACCOLTA VARIANTI ---
all_found = []
not_found = []

conn = sqlite3.connect(DB_PATH)

for i, (artist, title) in enumerate(TRACKLIST, 1):
    print(f"Cercando: {artist} - {title}")
    matches = find_all_matches_db(conn, artist, title)
    if not matches:
        matches = find_all_matches_folder(SECOND_FOLDER, artist, title)
    if matches:
        all_found.append((i, artist, title, matches))
    else:
        not_found.append(f"{artist} - {title}")

conn.close()

# --- SCELTA UTENTE ---
found = []
for i, artist, title, matches in all_found:
    print(f"\n{i}. {artist} - {title}:")
    for idx, (score, path, filename, duration, size, bitrate, album) in enumerate(matches, 1):
        size_mb = size / (1024*1024)
        dur_min = int(duration // 60) if duration else "-"
        dur_sec = int(duration % 60) if duration else "-"
        print(f"  {idx}) {filename} | {size_mb:.1f} MB | Durata: {dur_min}:{dur_sec} | Album: {album}")
    while True:
        scelta = input(f"   Scegli la versione da usare (1-{len(matches)}, invio per saltare): ")
        if not scelta:
            break
        if scelta.isdigit() and 1 <= int(scelta) <= len(matches):
            sel = matches[int(scelta)-1]
            ext = os.path.splitext(sel[2])[1]
            new_name = f"{i}. {artist} - {title}{ext}"
            dest_path = os.path.join(DEST_FOLDER, new_name)
            found.append((sel[1], dest_path))
            break
        print("   Input non valido. Riprova.")

# --- COPIA ---
print("\n📁 Copia dei file in corso...")
not_copied = []
for src, dst in tqdm(found, desc="Copiando", unit="file"):
    try:
        shutil.copy2(src, dst)
    except FileNotFoundError:
        print(f"\n⚠️  File non trovato: {src}")
        not_copied.append(os.path.basename(dst))
    except Exception as e:
        print(f"\n⚠️  Errore copiando {src}: {e}")
        not_copied.append(os.path.basename(dst))

# --- TRACKLIST ---
tracklist_path = os.path.join(DEST_FOLDER, "tracklist.txt")
with open(tracklist_path, "w", encoding="utf-8") as f:
    for i, (artist, title) in enumerate(TRACKLIST, 1):
        f.write(f"{i}. {artist} - {title}\n")

# --- RISULTATI ---
if not_found or not_copied:
    print("\n🚫 Brani non trovati o non copiati:")
    for t in not_found:
        print("-", t)
    for t in not_copied:
        print("-", t)
else:
    print("\n✅ Tutti i brani trovati e copiati.")