from mutagen import File as MutagenFile
import customtkinter as ctk
from tkinter import filedialog, messagebox
import customtkinter as ctk
import threading
import subprocess
import os
import sqlite3
import shutil

from create_Compilation import run_compilation_process, load_compilations, save_compilations, DB_PATH, SECOND_FOLDER, COMPILATIONS_FILE, normalize, find_all_matches_db, find_all_matches_folder

class CompilationApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Compilation Creator")
        self.root.geometry("900x700")
        self.index_folder = ctk.StringVar(value="/Volumes/NAS/Storage/Backup/Music")  # valore di default
        self.alternative_index_folder = ctk.StringVar(value="/Volumes/Incoming")
        self.tracklist = []
        self.dest_folder = ctk.StringVar()
        self.compilation_name = ctk.StringVar()
        self.txt_path = ctk.StringVar()
        self.manual_tracklist = []

        self.compilations = load_compilations()
        self.saved_comp_var = ctk.StringVar(value="Nuova Compilation")
        self.saved_comp_options = ["Nuova Compilation"] + [comp['name'] for comp in self.compilations]

        self.build_ui()

    def build_ui(self):
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        frame = ctk.CTkFrame(self.root)
        frame.pack(padx=20, pady=20, fill="both", expand=True)

        ctk.CTkButton(frame, text="Indicizza Libreria", command=self.run_indexing).pack(pady=10)
        
        ctk.CTkLabel(frame, text="Cartella da indicizzare:").pack(pady=(10, 0))
        index_frame = ctk.CTkFrame(frame)
        index_frame.pack()
        ctk.CTkEntry(index_frame, textvariable=self.index_folder, width=400).pack(side="left", padx=5)
        ctk.CTkButton(index_frame, text="Scegli", command=self.choose_index_folder).pack(side="left")

        ctk.CTkLabel(frame, text="Nome Compilation:").pack()
        ctk.CTkEntry(frame, textvariable=self.compilation_name, width=500).pack(pady=5)

        ctk.CTkLabel(frame, text="Cartella di destinazione:").pack()
        folder_frame = ctk.CTkFrame(frame)
        folder_frame.pack()
        ctk.CTkEntry(folder_frame, textvariable=self.dest_folder, width=400).pack(side="left", padx=5)
        ctk.CTkButton(folder_frame, text="Scegli", command=self.choose_dest).pack(side="left")

        ctk.CTkLabel(frame, text="File tracklist (.txt):").pack(pady=(10, 0))
        file_frame = ctk.CTkFrame(frame)
        file_frame.pack()
        ctk.CTkEntry(file_frame, textvariable=self.txt_path, width=400).pack(side="left", padx=5)
        ctk.CTkButton(file_frame, text="Scegli", command=self.choose_txt).pack(side="left")

        ctk.CTkLabel(frame, text="Carica Compilation Salvata:").pack(pady=(15, 5))
        self.saved_comp_menu = ctk.CTkOptionMenu(frame, variable=self.saved_comp_var, values=self.saved_comp_options, command=self.load_saved_compilation)
        self.saved_comp_menu.pack(pady=5)

        ctk.CTkButton(frame, text="Avvia Creazione", command=self.run).pack(pady=10)
        ctk.CTkButton(frame, text="Ricarica GUI", command=self.reload_ui).pack(pady=5)

        self.log_text = ctk.CTkTextbox(frame, height=200, width=800)
        self.log_text.pack(pady=10, fill="both", expand=True)
    
    def choose_index_folder(self):
        path = filedialog.askdirectory()
        if path:
            self.index_folder.set(path)    

    def reload_ui(self):
        for widget in self.root.winfo_children():
            widget.destroy()
        self.__init__(self.root)

    def choose_dest(self):
        path = filedialog.askdirectory()
        if path:
            self.dest_folder.set(path)

    def choose_txt(self):
        path = filedialog.askopenfilename(filetypes=[("Text Files", "*.txt")])
        if path:
            self.txt_path.set(path)
            self.log(f"Percorso file tracklist selezionato: {self.txt_path.get()}")

    def log(self, message):
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.update()

    def load_saved_compilation(self, selected_name):
        if selected_name == "Nuova Compilation":
            self.compilation_name.set("")
            self.dest_folder.set("")
            self.txt_path.set("")
            self.tracklist = []
            self.log("\nNuova compilation selezionata.")
            return

        for comp in self.compilations:
            if comp['name'] == selected_name:
                self.dest_folder.set(comp['dest_base'])
                self.compilation_name.set(comp['name'])
                self.tracklist = comp['tracklist']
                self.log(f"\nCompilation '{selected_name}' caricata. ({len(self.tracklist)} brani)")
                return
        self.log(f"Errore: Compilation '{selected_name}' non trovata.")
    
    def ask_user_choice(self, artist, title, matches):
        win = ctk.CTkToplevel(self.root)
        win.title(f"Scegli versione per: {artist} - {title}")
        win.geometry("900x650")
        win.grab_set()

        ctk.CTkLabel(
            win,
            text=f"Seleziona la versione per:\n{artist} - {title}",
            font=ctk.CTkFont(size=16, weight="bold")
        ).pack(pady=10)

        scroll_frame = ctk.CTkScrollableFrame(win, width=850, height=400)
        scroll_frame.pack(padx=20, pady=10, fill="both", expand=True)

        choice = {"path": None}
        current_matches = matches

        def refresh_matches(new_matches):
            # Pulisci la lista e mostra i nuovi match
            for widget in scroll_frame.winfo_children():
                widget.destroy()
            filtered_matches = [m for m in new_matches if (m[5] or 0) >= 320000]
            sorted_matches = sorted(filtered_matches, key=lambda m: m[5] if m[5] else 0, reverse=True)

            def seleziona(idx):
                choice["path"] = sorted_matches[idx][1]
                win.destroy()

            header = f"{'N.':<3} {'File':<50} {'Durata':<8} {'MB':<6} {'kbps':<6} Album"
            ctk.CTkLabel(scroll_frame, text=header, font=ctk.CTkFont(size=13, weight="bold")).pack(anchor="w")

            for idx, match in enumerate(sorted_matches):
                score, path, filename, duration, size, bitrate, album = match
                dur_min = int(duration // 60) if duration else 0
                dur_sec = int(duration % 60) if duration else 0
                size_mb = size / (1024 * 1024)
                bitrate_kbps = bitrate // 1000 if bitrate else 0
                album = album or "—"
                label_text = f"{idx+1:<3} {filename[:50]:<50} {dur_min}:{dur_sec:02d}   {size_mb:5.1f}  {bitrate_kbps:5}  {album}"
                btn = ctk.CTkButton(scroll_frame, text=label_text, anchor="w", command=lambda i=idx: seleziona(i))
                btn.pack(fill="x", padx=5, pady=2)

            if not sorted_matches:
                ctk.CTkLabel(scroll_frame, text="Nessun file trovato con bitrate ≥ 320kbps.", text_color="red").pack(pady=20)

        # Prima visualizzazione
        refresh_matches(current_matches)

        def search_in_second_folder():
            # Cerca nel secondo percorso e aggiorna la lista
            new_matches = find_all_matches_folder(SECOND_FOLDER, artist, title)
            refresh_matches(new_matches)

        btn_frame = ctk.CTkFrame(win)
        btn_frame.pack(pady=10)

        ctk.CTkButton(btn_frame, text="Cerca anche in cartella alternativa", command=search_in_second_folder).pack(side="left", padx=10)
        ctk.CTkButton(btn_frame, text="Salta questo brano", command=win.destroy, fg_color="gray").pack(side="left", padx=10)

        win.wait_window()
        return choice["path"]

    def run_indexing(self):
        folder = self.index_folder.get()
        if not folder:
            messagebox.showerror("Errore", "Seleziona una cartella da indicizzare.")
            return

        def indicizza():
            self.log(f"Indicizzazione in corso della cartella:\n{folder}")
            try:
                # Avvia lo script index_library.py come processo separato
                result = subprocess.run(
                    ["python3", "index_library.py", folder],
                    capture_output=True, text=True, cwd=os.path.dirname(__file__)
                )
                self.log(result.stdout)
                if result.stderr:
                    self.log(result.stderr)
                self.log("Indicizzazione completata.")
            except Exception as e:
                self.log(f"Errore durante l'indicizzazione: {e}")

        threading.Thread(target=indicizza, daemon=True).start()

    def review_and_edit_selection(self, tracklist, selected_paths, matches_dict):
        """
        Mostra una finestra per rivedere e modificare i brani selezionati.
        Permette di cambiare la scelta richiamando ask_user_choice.
        """
        win = ctk.CTkToplevel(self.root)
        win.title("Riepilogo brani selezionati")
        win.geometry("1000x600")
        win.grab_set()

        ctk.CTkLabel(win, text="Riepilogo brani selezionati (doppio click per cambiare versione)", font=ctk.CTkFont(size=16, weight="bold")).pack(pady=10)

        frame = ctk.CTkScrollableFrame(win, width=950, height=450)
        frame.pack(padx=10, pady=10, fill="both", expand=True)

        rows = []

        def refresh():
            for widget in frame.winfo_children():
                widget.destroy()
            for idx, (track, path) in enumerate(zip(tracklist, selected_paths)):
                artist, title = track
                display = f"{idx+1:<3} {artist} - {title}  |  {os.path.basename(path) if path else '---'}"
                row = ctk.CTkLabel(frame, text=display, anchor="w", font=ctk.CTkFont(size=13))
                row.pack(fill="x", padx=5, pady=2)
                def on_double_click(event, i=idx):
                    # Richiama la scelta solo se ci sono alternative
                    matches = matches_dict.get(i, [])
                    if matches:
                        new_path = self.ask_user_choice(artist, title, matches)
                        if new_path:
                            selected_paths[i] = new_path
                            refresh()
                row.bind("<Double-Button-1>", on_double_click)
                rows.append(row)

        refresh()

        def conferma():
            win.destroy()

        ctk.CTkButton(win, text="Conferma e avvia copia", command=conferma).pack(pady=15)
        win.wait_window()    

    def run(self):
        if not self.compilation_name.get() or not self.dest_folder.get():
            messagebox.showerror("Errore", "Nome compilation e cartella di destinazione obbligatori.")
            return

        if self.txt_path.get():
            import re
            path = self.txt_path.get()
            self.tracklist = []
            # Regex: accetta vari tipi di trattino come separatore
            sep_regex = re.compile(r"\s*[-–—‒―]\s*")
            with open(path, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    self.log(f"Riga {line_num}: '{line.rstrip()}'")
                    line = line.strip()
                    match = sep_regex.split(line, maxsplit=1)
                    if len(match) == 2:
                        artist, title = match
                        self.log(f"  -> Artista: '{artist.strip()}', Titolo: '{title.strip()}' (aggiunto)")
                        self.tracklist.append((artist.strip(), title.strip()))
                    else:
                        self.log(f"  -> Riga ignorata (no separatore trattino valido)")
            self.log(f"Tracklist caricata: {self.tracklist}")

        self.log("Avvio ricerca brani...")

        try:
            # Log percorso DB usato
            self.log(f"Percorso database usato: {DB_PATH}")
            # Trova tutti i match per ogni brano e salva la scelta
            matches_dict = {}
            selected_paths = []
            not_found = []
            not_copied = []

            conn = sqlite3.connect(DB_PATH)
            for idx, (artist, title) in enumerate(self.tracklist):
                matches = find_all_matches_db(conn, artist, title)
                if not matches:
                    matches = find_all_matches_folder(SECOND_FOLDER, artist, title)
                matches_dict[idx] = matches
                if matches:
                    self.log(f"Cerco: '{artist}' - '{title}'")
                    path = self.ask_user_choice(artist, title, matches)
                    selected_paths.append(path)
                else:
                    selected_paths.append(None)
                    not_found.append(f"{artist} - {title}")
            conn.close()

            # Mostra la finestra di riepilogo/modifica
            self.review_and_edit_selection(self.tracklist, selected_paths, matches_dict)

            # Ora esegui la copia solo per i path selezionati validi
            not_copied = []
            for idx, path in enumerate(selected_paths):
                if path:
                    # Sostituzione path server -> path locale se necessario
                    server_root = '../media/'
                    local_root = '/Volumes/NAS/Media/Music/'
                    if path.startswith(server_root):
                        local_path = os.path.join(local_root, path[len(server_root):])
                        self.log(f"Path server '{path}' sostituito con path locale '{local_path}'")
                    else:
                        local_path = path
                    # Copia il file nella cartella di destinazione
                    artist, title = self.tracklist[idx]
                    ext = os.path.splitext(local_path)[1]
                    dest_dir = os.path.join(self.dest_folder.get(), self.compilation_name.get())
                    os.makedirs(dest_dir, exist_ok=True)
                    dest_path = os.path.join(dest_dir, f"{idx+1}. {artist} - {title}{ext}")
                    try:
                        if not os.path.exists(dest_path):
                            shutil.copy2(local_path, dest_path)
                    except Exception as e:
                        not_copied.append(f"{artist} - {title}: {e}")
                else:
                    not_copied.append(f"{self.tracklist[idx][0]} - {self.tracklist[idx][1]} (non selezionato)")

            # Salva la compilation come prima...
            new_name = self.compilation_name.get()
            self.compilations = [c for c in self.compilations if c['name'] != new_name]
            comp_data = {
                "name": self.compilation_name.get(),
                "dest_base": self.dest_folder.get(),
                "tracklist": self.tracklist,
                "selected_paths": selected_paths
            }
            save_compilations(self.compilations + [comp_data])

            # Scrivi i brani non trovati su file
            if not_found:
                not_found_path = os.path.join(self.dest_folder.get(), self.compilation_name.get(), "not_found_tracks.txt")
                with open(not_found_path, "w", encoding="utf-8") as nf:
                    for track in not_found:
                        nf.write(track + "\n")
                self.log(f"Brani non trovati scritti su: {not_found_path}")

            if not_found or not_copied:
                messagebox.showwarning("Completato con Avvisi", "Alcuni brani non sono stati trovati o copiati.")
            else:
                messagebox.showinfo("Completato", "Tutti i brani sono stati copiati.")

        except Exception as e:
            messagebox.showerror("Errore", str(e))
            self.log(f"Errore: {e}")

if __name__ == "__main__":
    root = ctk.CTk()
    app = CompilationApp(root)
    root.mainloop()