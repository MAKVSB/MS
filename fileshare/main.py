import os
import pickle
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import hashlib
import json
import time
import threading 
import platform
import shutil # Nový import pro rekurzivní mazání složek
from datetime import datetime 

from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload

# === CONSTANTS ===
SCOPES = ["https://www.googleapis.com/auth/drive"] 
SYNC_DIR = "synced_files" 
SYNC_STATUS_FILE = "sync_status.json" 
SYNC_INTERVAL_SECONDS = 40 # Kontrola každou minutu (Mějte na paměti, že rekurzivní synchronizace může trvat déle)

if not os.path.exists(SYNC_DIR):
    os.makedirs(SYNC_DIR)

# === AUTH ===
def get_drive_service():
    """Zajišťuje autentizaci s Google Drive API."""
    creds = None
    if os.path.exists("token.pickle"):
        with open("token.pickle", "rb") as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        with open("token.pickle", "wb") as token:
            pickle.dump(creds, token)
    return build("drive", "v3", credentials=creds)

# === DRIVE OPERATIONS ===
def list_files_in_folder(service, folder_id="root"):
    """Vrátí seznam souborů a složek v dané složce."""
    results = service.files().list(
        q=f"'{folder_id}' in parents and trashed=false",
        pageSize=100,
        fields="files(id, name, mimeType, fileExtension, modifiedTime)", 
    ).execute()
    return results.get("files", [])

def download_file(service, file_id, file_name, local_path):
    """
    Stáhne soubor z Google Drive. 
    Klíčové: Zajistí existenci lokální cesty pro zachování struktury.
    """
    # ZAJIŠTĚNÍ EXISTENCE SLOŽEK: Vytvoří nadřazené adresáře, pokud neexistují
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    
    request = service.files().get_media(fileId=file_id)
    try:
        with open(local_path, "wb") as fh:
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
        return local_path
    except Exception as e:
        # Příklad: Pokud by soubor zmizel, nebo došlo k chybě zápisu.
        print(f"Chyba při stahování {file_name}: {e}")
        return None

def upload_new_file(service, local_filepath, parent_folder_id):
    """Nahraje nový soubor na Google Drive."""
    filename = os.path.basename(local_filepath)
    file_metadata = {
        'name': filename,
        'parents': [parent_folder_id]
    }
    media = MediaFileUpload(local_filepath, resumable=True)
    file = service.files().create(body=file_metadata, media_body=media, fields='id, name, mimeType').execute()
    return file.get('id'), file.get('name'), file.get('mimeType')

def update_file_content(service, file_id, local_filepath):
    """Aktualizuje obsah existujícího souboru na Google Drive."""
    media = MediaFileUpload(local_filepath, resumable=True)
    file = service.files().update(fileId=file_id, media_body=media).execute()
    return file.get('id')

# === SYNCHRONIZATION LOGIC ===

def load_sync_status():
    """Načte stav synchronizace z lokálního JSON souboru."""
    if os.path.exists(SYNC_STATUS_FILE):
        with open(SYNC_STATUS_FILE, "r") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}

def save_sync_status(status_data):
    """Uloží stav synchronizace do lokálního JSON souboru."""
    with open(SYNC_STATUS_FILE, "w") as f:
        json.dump(status_data, f, indent=4)

def get_local_file_hash(filepath):
    """Vypočítá SHA1 hash lokálního souboru."""
    hash_sha1 = hashlib.sha1()
    try:
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_sha1.update(chunk)
        return hash_sha1.hexdigest()
    except FileNotFoundError:
        return None

def open_local_file(filepath):
    """Otevře lokální soubor pomocí výchozí aplikace OS."""
    if platform.system() == "Windows":
        os.startfile(filepath)
    elif platform.system() == "Darwin":  # macOS
        os.system(f"open \"{filepath}\"")
    else:  # Linux (předpokládá se použití xdg-open)
        os.system(f"xdg-open \"{filepath}\"")

# --- REKURZIVNÍ LOGIKA ---

def _recursively_get_folder_content(service, drive_id, local_path_prefix, sync_root_id):
    """
    Rekurzivně prochází složky na Disku.
    Yields: (file_metadata, drive_relative_path, full_local_path)
    """
    try:
        files = list_files_in_folder(service, drive_id)
    except Exception as e:
        print(f"Error accessing Drive ID {drive_id}: {e}")
        return
    
    for f in files:
        f_name = f['name']
        f_id = f['id']
        is_folder = f["mimeType"] == "application/vnd.google-apps.folder"
        
        # Sestavení relativní cesty (např. 'Slozka/Soubor.txt')
        drive_relative_path = os.path.join(local_path_prefix, f_name)
        # Sestavení plné lokální cesty (např. 'synced_files/Slozka/Soubor.txt')
        full_local_path = os.path.join(SYNC_DIR, drive_relative_path)

        yield f, drive_relative_path, full_local_path

        if is_folder:
            # Rekurze do podsložek
            yield from _recursively_get_folder_content(
                service, 
                f_id, 
                drive_relative_path, 
                sync_root_id
            )

# === GUI ===
class DriveBrowser(tk.Tk):
    def __init__(self, service):
        super().__init__()
        self.title("Google Drive Browser (Synchronizace složek)")
        self.geometry("900x600")
        self.service = service
        self.current_folder_id = "root"
        self.sync_status = load_sync_status() 
        self.history = []

        # Folder path label
        self.path_label = tk.Label(self, text="Folder: root", anchor="w")
        self.path_label.pack(fill="x", padx=10, pady=5)

        # Treeview for file list
        columns = ("Name", "Type", "ID", "Sync Status", "Last Synced At")
        self.tree = ttk.Treeview(self, columns=columns, show="headings")
        self.tree.heading("Name", text="Name")
        self.tree.heading("Type", text="Type")
        self.tree.heading("ID", text="ID")
        self.tree.heading("Sync Status", text="Sync Status")
        self.tree.heading("Last Synced At", text="Last Synced At")
        self.tree.column("Name", width=250, anchor=tk.W)
        self.tree.column("Type", width=80, anchor=tk.CENTER)
        self.tree.column("ID", width=150)
        self.tree.column("Sync Status", width=120, anchor=tk.CENTER)
        self.tree.column("Last Synced At", width=150, anchor=tk.CENTER)
        self.tree.pack(fill="both", expand=True, padx=10, pady=5)

        # Scrollbar
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        
        # Frame for buttons
        btn_frame = ttk.Frame(self)
        btn_frame.pack(pady=5)

        # Back button
        self.back_btn = ttk.Button(btn_frame, text="⬅ Zpět", command=self.go_back)
        self.back_btn.pack(side="left", padx=5)

        # Sync/Unsync button (text se bude měnit dynamicky v load_folder)
        self.sync_btn = ttk.Button(btn_frame, text="Sync/Unsync", command=self.toggle_sync)
        self.sync_btn.pack(side="left", padx=5)

        # Upload button
        self.upload_btn = ttk.Button(btn_frame, text="⬆ Nahrát soubor", command=self.open_upload_dialog)
        self.upload_btn.pack(side="left", padx=5)

        # Bind double-click event
        self.tree.bind("<Double-1>", self.on_item_double_click)
        self.tree.bind("<<TreeviewSelect>>", self.on_selection_change)
        
        # Load root files
        self.load_folder("root")
        self.on_selection_change() # Nastaví text tlačítka na začátku
        
        # Spuštění monitorovacího vlákna
        self.sync_monitor_thread = threading.Thread(target=self.start_sync_monitor, daemon=True)
        self.sync_monitor_thread.start()

    def on_selection_change(self, event=None):
        """Aktualizuje text na synchronizačním tlačítku podle výběru."""
        selected = self.tree.selection()
        if not selected:
            self.sync_btn.config(text="Vyberte položku")
            return
            
        file_id = selected[0]
        item = self.tree.item(file_id)
        name, ftype, _, _, _ = item["values"]
        
        if file_id in self.sync_status:
            if self.sync_status[file_id]['is_folder']:
                self.sync_btn.config(text=f"Zrušit sync složky '{name}'")
            else:
                self.sync_btn.config(text=f"Zrušit sync souboru '{name}'")
        else:
            if ftype == "Folder":
                # OPRAVENO: Použijte klíčové slovo 'text=' pro nastavení textu tlačítka
                self.sync_btn.config(text=f"Synchronizovat složku '{name}'")
            else:
                # OPRAVENO: Použijte klíčové slovo 'text=' pro nastavení textu tlačítka
                self.sync_btn.config(text=f"Synchronizovat soubor '{name}'")
        
    def start_sync_monitor(self):
        """Vlákno, které periodicky kontroluje lokální a vzdálené změny."""
        while True:
            # print("Thread ping")
            # 1. Kontrola a nahrání lokálních změn (Local -> Remote)
            self.check_and_sync_local_changes()
            
            # 2. Kontrola a stažení vzdálených změn (Remote -> Local)
            self.check_and_sync_remote_changes()
            
            time.sleep(SYNC_INTERVAL_SECONDS)

    def update_treeview_sync_status(self, file_id, file_name, status_text):
        """Bezpečně aktualizuje stav jednoho souboru v Treeview (voláno z after)."""
        if file_id in self.tree.get_children():
            status_data = self.sync_status.get(file_id, {})
            last_sync_ts = status_data.get('last_synced_time')
            
            last_sync = ""
            if last_sync_ts:
                last_sync = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(last_sync_ts))
             
            item = self.tree.item(file_id)
            # Získáme staré hodnoty a aktualizujeme pouze Name, Sync Status a Last Synced At
            _, ftype, fid, _, _ = item["values"]
            self.tree.item(file_id, values=(file_name, ftype, fid, status_text, last_sync))
        
        # Po aktualizaci položky je dobré zajistit aktualizaci tlačítka, pokud je vybraná
        self.after(0, self.on_selection_change) 


    def load_folder(self, folder_id, folder_name="root"):
        """Načte a zobrazí obsah složky."""
        try:
            self.tree.delete(*self.tree.get_children())
            files = list_files_in_folder(self.service, folder_id)
            for f in files:
                ftype = (
                    "Folder"
                    if f["mimeType"] == "application/vnd.google-apps.folder"
                    else (f.get("fileExtension", "") or "File")
                )
                
                # Zjištění stavu synchronizace
                file_id = f["id"]
                sync_status_text = ""
                last_sync = ""
                
                if file_id in self.sync_status:
                    if self.sync_status[file_id]['is_folder']:
                         sync_status_text = "SYNCED FOLDER ✅"
                    else:
                         sync_status_text = "SYNCED FILE ✅"
                         
                    last_sync_ts = self.sync_status[file_id]['last_synced_time']
                    if last_sync_ts:
                        last_sync = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(last_sync_ts))
                
                self.tree.insert("", "end", values=(f["name"], ftype, file_id, sync_status_text, last_sync), iid=file_id)
                
            self.path_label.config(text=f"Složka: {folder_name}")
            self.current_folder_id = folder_id
        except Exception as e:
            messagebox.showerror("Chyba", f"Nepodařilo se načíst složku: {str(e)}")

    def on_item_double_click(self, event):
        """Při dvojkliku navigace do složky nebo otevření souboru/řešení konfliktu."""
        selected = self.tree.selection()
        if not selected:
            return
            
        file_id = selected[0] 
        item = self.tree.item(file_id)
        name, ftype, _, sync_status_text, _ = item["values"] 

        if ftype == "Folder":
            # Ukládáme aktuální ID a text cesty do historie pro tlačítko zpět
            self.history.append((self.current_folder_id, self.path_label.cget("text"))) 
            self.load_folder(file_id, name)
            
        elif file_id in self.sync_status:
            # Soubor je synchronizován - použijeme uloženou lokální cestu (včetně struktury)
            local_path = self.sync_status[file_id]['local_path']

            if "KONFLIKT 💥" in sync_status_text:
                self.handle_conflict(file_id, name, local_path)
            
            elif os.path.exists(local_path):
                 try:
                     open_local_file(local_path)
                 except Exception as e:
                     messagebox.showerror("Chyba při otevírání", f"Nepodařilo se otevřít soubor: {str(e)}")
            else:
                 messagebox.showinfo("Info", "Soubor je označen jako SYNCED, ale lokální kopie chybí.")

    def handle_conflict(self, file_id, file_name, local_path):
        """Zobrazí dialog pro řešení konfliktu pro daný soubor."""
        
        conflict_window = tk.Toplevel(self)
        conflict_window.title("Vyřešit konflikt")
        
        window_width = 400
        window_height = 200
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        center_x = int(screen_width/2 - window_width/2)
        center_y = int(screen_height/2 - window_height/2)
        conflict_window.geometry(f'{window_width}x{window_height}+{center_x}+{center_y}')
        
        msg = f"Byl detekován konflikt pro '{file_name}'. Jak ho chcete vyřešit?"
        tk.Label(conflict_window, text=msg, wraplength=window_width - 20, padx=10, pady=10).pack()
        
        button_frame = ttk.Frame(conflict_window)
        button_frame.pack(pady=10)

        def upload_local():
            self._resolve_conflict_upload(file_id, file_name, local_path)
            conflict_window.destroy()

        def download_remote():
            self._resolve_conflict_download(file_id, file_name, local_path)
            conflict_window.destroy()

        def open_local():
            try:
                open_local_file(local_path)
            except Exception as e:
                 messagebox.showerror("Chyba při otevírání", f"Nepodařilo se otevřít soubor: {str(e)}")
            conflict_window.destroy() 
            
        ttk.Button(button_frame, text="⬆️ Nahrát lokální (ponechat lokální)", width=40, command=upload_local).pack(pady=5)
        ttk.Button(button_frame, text="⬇️ Stáhnout vzdálenou (přepsat lokální)", width=40, command=download_remote).pack(pady=5)
        ttk.Button(button_frame, text="📄 Otevřít lokální soubor", width=40, command=open_local).pack(pady=5)

    # --- Implementace řešení konfliktů (vlákna) ---
    def _resolve_conflict_upload(self, file_id, file_name, local_filepath):
        # ... (Logika zůstává stejná, jen používá local_filepath, který už obsahuje cestu)
        def upload_worker():
            try:
                update_file_content(self.service, file_id, local_filepath)
                
                current_local_hash = get_local_file_hash(local_filepath)
                remote_metadata_after_upload = self.service.files().get(fileId=file_id, fields='modifiedTime').execute()

                self.sync_status[file_id].update({
                    "last_synced_time": time.time(),
                    "local_hash_at_sync": current_local_hash,
                    "remote_modified_time": remote_metadata_after_upload['modifiedTime']
                })
                save_sync_status(self.sync_status)
                
                self.after(0, lambda: messagebox.showinfo("Konflikt vyřešen", f"Lokální verze '{file_name}' úspěšně nahrána."))
                self.after(0, lambda: self.update_treeview_sync_status(file_id, file_name, "NAHRÁNO ✅"))
                
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Chyba nahrávání", f"Nepodařilo se nahrát '{file_name}': {str(e)}"))
                self.after(0, lambda: self.update_treeview_sync_status(file_id, file_name, "NAHRÁNÍ SELHALO ❌"))
                
        threading.Thread(target=upload_worker, daemon=True).start()

    def _resolve_conflict_download(self, file_id, file_name, local_filepath):
        # ... (Logika zůstává stejná)
        def download_worker():
            try:
                remote_metadata = self.service.files().get(fileId=file_id, fields='modifiedTime, name').execute()
                remote_modified_time = remote_metadata['modifiedTime']
                
                download_file(self.service, file_id, remote_metadata['name'], local_filepath) 
                
                new_local_hash = get_local_file_hash(local_filepath)
                # Aktualizujeme status pro správnou kontrolu hashe
                self.sync_status[file_id].update({
                    "name": remote_metadata['name'],
                    "local_path": local_filepath,
                    "last_synced_time": time.time(),
                    "remote_modified_time": remote_modified_time,
                    "local_hash_at_sync": new_local_hash,
                })
                save_sync_status(self.sync_status)
                
                self.after(0, lambda: messagebox.showinfo("Konflikt vyřešen", f"Vzdálená verze '{file_name}' úspěšně stažena (lokální soubor přepsán)."))
                self.after(0, lambda: self.update_treeview_sync_status(file_id, file_name, "STAŽENO ⬇️"))
                
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Chyba stahování", f"Nepodařilo se stáhnout '{file_name}': {str(e)}"))
                self.after(0, lambda: self.update_treeview_sync_status(file_id, file_name, "STAŽENÍ SELHALO ❌"))

        threading.Thread(target=download_worker, daemon=True).start()

    def go_back(self):
        """Návrat do předchozí složky."""
        if not self.history:
            return
        folder_id, folder_name_text = self.history.pop()
        folder_name = folder_name_text.split(": ", 1)[-1] 
        self.load_folder(folder_id, folder_name)

    # --- REKURZIVNÍ SYNCHRONIZACE S FUNKCÍ download_and_track ---

    def download_and_track(self, file_id, file_name, is_folder, drive_relative_path, full_local_path, sync_root_id):
        """
        Stáhne soubor/Vytvoří složku, uloží ji lokálně a aktualizuje stav synchronizace.
        Používá se pro soubory i složky (složené cesty).
        """
        
        remote_modified_time = ""
        local_hash = ""

        if is_folder:
            # 1. Pouze vytvoří lokální složku a uloží status
            os.makedirs(full_local_path, exist_ok=True)
        else:
            # 1. Získání vzdálených metadat před stažením
            try:
                remote_metadata = self.service.files().get(fileId=file_id, fields='modifiedTime').execute()
                remote_modified_time = remote_metadata['modifiedTime']
            except Exception as e:
                print(f"Chyba při získávání metadat pro {file_name}: {str(e)}")
                return False

            # 2. Stažení souboru (sestavená cesta full_local_path zajistí strukturu)
            if not download_file(self.service, file_id, file_name, full_local_path):
                 return False

            # 3. Uložení stavu synchronizace
            local_hash = get_local_file_hash(full_local_path)
        
        self.sync_status[file_id] = {
            "name": file_name,
            "is_folder": is_folder, # Nové: Ukládáme typ
            "local_path": full_local_path,
            "last_synced_time": time.time(),
            "remote_modified_time": remote_modified_time, 
            "local_hash_at_sync": local_hash,
            "drive_root_id": sync_root_id, # Nové: ID složky, která je kořenem syncu
            "drive_relative_path": drive_relative_path
        }
        save_sync_status(self.sync_status)
        return True

    def _start_recursive_sync(self, drive_folder_id, folder_name):
        """Worker vlákno pro rekurzivní synchronizaci složky."""
        
        self.after(0, lambda fid=drive_folder_id, name=folder_name: 
                 self.update_treeview_sync_status(fid, name, "SYNCING... 🔄"))

        sync_root_id = drive_folder_id
        
        # 1. Synchronizovat samotnou kořenovou složku (jen vytvořit lokální adresář a trackovat)
        drive_relative_path = folder_name
        full_local_path = os.path.join(SYNC_DIR, folder_name)

        # Před rekurzivním voláním musíme zajistit, že nadřazená složka existuje
        # Pokud je drive_folder_id jiná než 'root', potřebujeme znát jejího nadřazeného.
        # V tomto kontextu se synchronizuje složka, která je vybraná v GUI, takže lokální cesta
        # bude vždy pod SYNC_DIR.
        self.download_and_track(drive_folder_id, folder_name, True, drive_relative_path, full_local_path, sync_root_id)
        
        # 2. Iterovat rekurzivně přes její obsah a stahovat soubory / trackovat podsložky
        for f, drive_relative_path, full_local_path in _recursively_get_folder_content(
            self.service, 
            drive_folder_id, 
            folder_name, 
            sync_root_id
        ):
            try:
                is_folder = f["mimeType"] == "application/vnd.google-apps.folder"
                
                # Zde je klíčové, že download_and_track již vytvoří lokální složky pro zachování struktury
                self.download_and_track(
                    f['id'], 
                    f['name'], 
                    is_folder, 
                    drive_relative_path, 
                    full_local_path, 
                    sync_root_id
                )
                
                # Aktualizace GUI pro soubory, které byly právě staženy
                if not is_folder:
                    self.after(0, lambda fid=f['id'], name=f['name']: 
                             self.update_treeview_sync_status(fid, name, "SYNCED FILE ✅"))
            except Exception as e:
                print(f"Chyba při rekurzivní synchronizaci {f['name']}: {str(e)}")
        
        # 3. Finální GUI update
        self.after(0, lambda fid=drive_folder_id, name=folder_name: 
                 self.update_treeview_sync_status(fid, name, "SYNCED FOLDER ✅"))
        self.after(0, lambda: messagebox.showinfo("Synchronizace dokončena", f"Složka '{folder_name}' a veškerý obsah synchronizován."))


    def _recursively_unsync(self, drive_id):
        """
        Zruší synchronizaci pro dané ID a všechny jeho rekurzivní děti v sync_status.
        Zároveň smaže odpovídající lokální soubory/složky.
        """
        
        # 1. Najít všechny položky, které mají dané ID jako kořen
        items_to_unsync = [
            fid for fid, status in self.sync_status.items() 
            if status.get('drive_root_id') == drive_id or fid == drive_id
        ]
        
        # 2. Bezpečně smazat lokální kopii kořenové složky/souboru
        if drive_id in self.sync_status:
            status = self.sync_status[drive_id]
            if status["is_folder"]:
                try:
                    # Smazat celou kořenovou lokální složku rekurzivně
                    if os.path.exists(status["local_path"]):
                        shutil.rmtree(status["local_path"])
                        print(f"Odstraněna lokální složka: {status['local_path']}")
                except Exception as e:
                    print(f"Chyba při mazání lokální složky {status['local_path']}: {str(e)}")
            else:
                # Smazat jednotlivý soubor
                if os.path.exists(status["local_path"]):
                    os.remove(status["local_path"])
                    print(f"Odstraněn lokální soubor: {status['local_path']}")

        # 3. Odstranit všechny související záznamy ze sync_status
        for fid in items_to_unsync:
            if fid in self.sync_status:
                del self.sync_status[fid]

        save_sync_status(self.sync_status)


    def toggle_sync(self):
        """Zapíná nebo vypíná synchronizaci pro vybranou položku (soubor nebo složku)."""
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Výběr", "Prosím vyberte soubor nebo složku.")
            return

        file_id = selected[0]
        item = self.tree.item(file_id)
        name, ftype, _, _, _ = item["values"]
        is_folder = (ftype == "Folder")

        # --- ZRUŠENÍ SYNCHRONIZACE ---
        if file_id in self.sync_status:
            # Nová funkce pro rekurzivní zrušení synchronizace (včetně lokálního mazání)
            self._recursively_unsync(file_id)
            messagebox.showinfo("Sync", f"Položka '{name}' a její obsah již nejsou synchronizovány. Lokální kopie smazány.")
            
            # Znovunačíst složku pro aktualizaci statusu v GUI
            self.load_folder(self.current_folder_id, self.path_label.cget("text").split(": ", 1)[-1])
            self.on_selection_change()
            return

        # --- ZAPNUTÍ SYNCHRONIZACE ---
        
        if is_folder:
            # Synchronizace složky
            if messagebox.askyesno("Synchronizovat složku", f"Chcete synchronizovat celou složku '{name}' a veškerý její obsah rekurzivně?"):
                # Spuštění rekurzivní synchronizace v novém vlákně
                threading.Thread(target=self._start_recursive_sync, args=(file_id, name), daemon=True).start()
        
        else:
            # Synchronizace jednotlivého souboru (cesta je jen název souboru)
            drive_relative_path = name
            full_local_path = os.path.join(SYNC_DIR, name)
            
            # Pro jednotlivý soubor použijeme ID aktuální složky jako kořen (jednodušší než 'root')
            sync_root_id = self.current_folder_id 
            
            if self.download_and_track(file_id, name, False, drive_relative_path, full_local_path, sync_root_id):
                messagebox.showinfo("Sync", f"Soubor '{name}' byl úspěšně synchronizován a stažen.")
                self.update_treeview_sync_status(file_id, name, "SYNCED FILE ✅")

    # --- MONITOROVACÍ LOGIKA (Upraveno pro ignorování složek) ---

    def check_and_sync_local_changes(self):
        """Iteruje přes synchronizované SOUBORY a nahrává lokální změny (Local -> Remote)."""
        
        updated_sync_status = self.sync_status.copy()
        
        for file_id, status in self.sync_status.items():
            
            # PŘESKOČIT SLOŽKY
            if status["is_folder"]:
                 continue 
                 
            local_filepath = status["local_path"]
            
            if not os.path.exists(local_filepath):
                 continue 
                 
            current_local_hash = get_local_file_hash(local_filepath)
            
            if current_local_hash != status["local_hash_at_sync"]:
                
                try:
                    remote_metadata_current = self.service.files().get(fileId=file_id, fields='modifiedTime, name').execute()
                    remote_modified_time_current = remote_metadata_current['modifiedTime']
                    
                    current_remote_time = datetime.fromisoformat(remote_modified_time_current.replace('Z', '+00:00'))
                    last_synced_remote_time = datetime.fromisoformat(status['remote_modified_time'].replace('Z', '+00:00'))
                    
                    # KONTROLA KONFLIKTU
                    if current_remote_time > last_synced_remote_time:
                        
                        print(f"KONFLIKT pro {status['name']}: Lokální a vzdálený soubor změněn. Přeskakuji nahrání.")
                        self.after(0, lambda fid=file_id, name=status['name']: 
                                 self.update_treeview_sync_status(fid, name, "KONFLIKT 💥"))
                        continue 
                        
                    # BEZPEČNÉ NAHRÁNÍ
                    print(f"Nahrávám lokální změnu: {status['name']}")
                    update_file_content(self.service, file_id, local_filepath)
                    
                    remote_metadata_after_upload = self.service.files().get(fileId=file_id, fields='modifiedTime').execute()

                    updated_sync_status[file_id]["last_synced_time"] = time.time()
                    updated_sync_status[file_id]["local_hash_at_sync"] = current_local_hash
                    updated_sync_status[file_id]["remote_modified_time"] = remote_metadata_after_upload['modifiedTime']
                    
                    self.after(0, lambda fid=file_id, name=status['name']: 
                             self.update_treeview_sync_status(fid, name, "NAHRÁNO ✅"))
                         
                except Exception as e:
                    print(f"CHYBA při synchronizaci {status['name']}: {str(e)}") 
                    self.after(0, lambda fid=file_id, name=status['name']: 
                             self.update_treeview_sync_status(fid, name, "NAHRÁNÍ SELHALO ❌"))


        self.sync_status = updated_sync_status
        save_sync_status(self.sync_status)


    def check_and_sync_remote_changes(self,):
        """Kontroluje vzdálené změny a stahuje je (Remote -> Local)."""
        
        updated_sync_status = self.sync_status.copy()
        
        for file_id, status in self.sync_status.items():
            
            # PŘESKOČIT SLOŽKY
            if status["is_folder"]:
                 continue 
                 
            try:
                # 1. Získání nejnovějších metadat z Drive
                remote_metadata = self.service.files().get(fileId=file_id, fields='modifiedTime, name').execute()
                remote_modified_time_str = remote_metadata['modifiedTime']
                
                remote_time = datetime.fromisoformat(remote_modified_time_str.replace('Z', '+00:00'))
                last_synced_remote_time = datetime.fromisoformat(status['remote_modified_time'].replace('Z', '+00:00'))
                
                # 2. Kontrola, zda je vzdálený soubor novější
                if remote_time > last_synced_remote_time:
                    
                    # Vzdálený soubor je novější. Kontrola lokálního stavu.
                    local_filepath = status["local_path"]
                    current_local_hash = get_local_file_hash(local_filepath)
                    
                    # 3. KONTROLA HASHE: Byl lokální soubor upraven?
                    if current_local_hash == status["local_hash_at_sync"]:
                        
                        # Lokální soubor NENÍ upraven -> Bezpečné stažení vzdálené aktualizace.
                        print(f"Detekována vzdálená aktualizace pro {status['name']}. Stahuji...")
                        
                        # Provedení stažení
                        download_file(self.service, file_id, remote_metadata['name'], local_filepath)
                        
                        # Aktualizace stavu po úspěšném stažení
                        new_local_hash = get_local_file_hash(local_filepath)
                        updated_sync_status[file_id].update({
                            "name": remote_metadata['name'],
                            "local_path": local_filepath,
                            "last_synced_time": time.time(),
                            "remote_modified_time": remote_modified_time_str,
                            "local_hash_at_sync": new_local_hash,
                        })
                        
                        self.after(0, lambda fid=file_id, name=remote_metadata['name']: 
                                 self.update_treeview_sync_status(fid, name, "STAŽENO ⬇️"))

                    else:
                        # Lokální soubor BYL upraven.
                        print(f"Konflikt pro {status['name']}: Lokální soubor změněn, přeskakuji vzdálené stahování.")
                        self.after(0, lambda fid=file_id, name=status['name']: 
                                 self.update_treeview_sync_status(fid, name, "KONFLIKT 💥"))
                    
            except Exception as e:
                print(f"Chyba při kontrole vzdáleného stavu pro {status['name']}: {str(e)}")


        self.sync_status = updated_sync_status
        save_sync_status(self.sync_status)
        
    # --- UPLOAD IMPLEMENTATION (Stejné jako předtím) ---

    def open_upload_dialog(self):
        """Otevře dialog pro výběr souboru k nahrání."""
        filepath = filedialog.askopenfilename(
            title="Vybrat soubor k nahrání", 
            filetypes=(("Všechny soubory", "*.*"),)
        )
        if not filepath:
            return

        try:
            # Nahrání do aktuální složky
            file_id, file_name, _ = upload_new_file(self.service, filepath, self.current_folder_id)
            messagebox.showinfo("Nahrání", f"Soubor '{file_name}' byl úspěšně nahrán!")
            
            # Znovunačtení složky
            self.load_folder(self.current_folder_id, self.path_label.cget("text").split(": ", 1)[-1])

            if messagebox.askyesno("Synchronizovat nový soubor", f"Chcete okamžitě synchronizovat '{file_name}'?"):
                 # Nastavení synchronizace (cesta je jen název souboru)
                 drive_relative_path = file_name
                 full_local_path = os.path.join(SYNC_DIR, file_name)
                 sync_root_id = self.current_folder_id 
                 
                 self.download_and_track(file_id, file_name, False, drive_relative_path, full_local_path, sync_root_id)
                 self.load_folder(self.current_folder_id, self.path_label.cget("text").split(": ", 1)[-1]) 
                 self.on_selection_change()

        except Exception as e:
            messagebox.showerror("Chyba nahrávání", f"Nepodařilo se nahrát soubor: {str(e)}")

if __name__ == "__main__":
    try:
        service = get_drive_service()
        app = DriveBrowser(service)
        app.mainloop()
    except Exception as e:
         # Důležité: Přidáno zachycení chyby při startu, pokud chybí credentials.json nebo selže autentizace
        print(f"Fatal error during startup: {e}")
        # Místo messagebox.showerror() to vypíšeme do konzole, protože GUI nemusí být plně inicializované
        # V reálné aplikaci by se zde měl zobrazit uživatelský dialog mimo hlavní smyčku Tkinter
        print("Ujistěte se, že máte soubor 'credentials.json' a 'token.pickle' v pořádku.")
        print("Aplikace ukončena.")
        
