import os
import sqlite3
import time
from mutagen import File as MutagenFile
import sys

# CONFIGURAZIONE
MUSIC_FOLDER = sys.argv[1] if len(sys.argv) > 1 else "/Volumes/NAS/Storage/Backup/Music"
DB_PATH = "music_library.db"
ACCEPTED_EXT = ('.mp3', '.flac', '.wav', '.aac', '.ogg', '.m4a')
EXCLUDE_KEYWORDS = []
# ['remix', 'live', 'edit', 'version', 'karaoke', 'instrumental', 'demo', 'acoustic']

# CREA DB E TABELLA
conn = sqlite3.connect(DB_PATH)
c = conn.cursor()
c.execute("""
CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE,
    filename TEXT,
    ext TEXT,
    size INTEGER,
    duration REAL,
    bitrate INTEGER,
    album TEXT,
    mtime REAL
)
""")
conn.commit()

# FUNZIONE PER SCANSIONARE E AGGIORNARE
updated = 0
skipped = 0
added = 0

found_paths = set()

print("\n🔍 Scansione della libreria in corso...")
for root, dirs, files in os.walk(MUSIC_FOLDER):
    for file in files:
        file_lower = file.lower()
        if not file_lower.endswith(ACCEPTED_EXT):
            continue
        if any(bad in file_lower for bad in EXCLUDE_KEYWORDS):
            continue

        full_path = os.path.join(root, file)
        found_paths.add(full_path) 
        
        try:
            stat = os.stat(full_path)
        except:
            continue

        mtime = stat.st_mtime
        size = stat.st_size
        ext = os.path.splitext(file)[1].lower()

        # Verifica se presente nel DB
        c.execute("SELECT mtime FROM tracks WHERE path = ?", (full_path,))
        row = c.fetchone()
        if row and abs(row[0] - mtime) < 1:
            skipped += 1
            continue  # già indicizzato e non modificato

        try:
            audio = MutagenFile(full_path)
            duration = audio.info.length if audio and audio.info else 0
            bitrate = getattr(audio.info, 'bitrate', 0) if audio and audio.info else 0
            album = audio.tags.get('TALB') if audio and audio.tags else None
            if album:
                album = album.text[0] if hasattr(album, 'text') else str(album)
            else:
                album = ""
        except:
            duration = 0
            bitrate = 0
            album = ""

        if row:
            c.execute("""
            UPDATE tracks SET filename=?, ext=?, size=?, duration=?, bitrate=?, album=?, mtime=? WHERE path=?
            """, (file, ext, size, duration, bitrate, album, mtime, full_path))
            updated += 1
        else:
            c.execute("""
            INSERT INTO tracks (path, filename, ext, size, duration, bitrate, album, mtime)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (full_path, file, ext, size, duration, bitrate, album, mtime))
            added += 1

c.execute("SELECT path FROM tracks")
all_db_paths = set(row[0] for row in c.fetchall())
to_delete = all_db_paths - found_paths

deleted = 0
for path in to_delete:
    c.execute("DELETE FROM tracks WHERE path = ?", (path,))
    deleted += 1
conn.commit()

conn.close()

print(f"\n✅ Indicizzazione completata:")
print(f"   Nuovi file aggiunti : {added}")
print(f"   File aggiornati     : {updated}")
print(f"   File ignorati       : {skipped}")
print(f"   File rimossi dal DB : {deleted}")