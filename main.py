import os
import io
import re
import sys
import json
import shutil
import mimetypes
import threading
import traceback

try:
    import certifi
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
except Exception:
    pass

from kivy.app import App
from kivy.clock import Clock
from kivy.core.clipboard import Clipboard
from kivy.lang import Builder
from kivy.logger import Logger
from kivy.uix.boxlayout import BoxLayout
from kivy.utils import platform


# --------------------------------------------------------------------------
# Perbaikan error  'str' object has no attribute 'write'
# Kivy mengganti sys.stderr dengan objek yang atribut .buffer-nya berupa str.
# yt-dlp memakai out.buffer.write(...) sehingga crash. Ganti dengan stream aman.
# --------------------------------------------------------------------------
class SafeStream:
    encoding = "utf-8"
    errors = "ignore"

    def __init__(self, fn):
        self._fn = fn
        self._busy = False

    def write(self, s):
        n = len(s) if hasattr(s, "__len__") else 0
        if self._busy:
            return n
        self._busy = True
        try:
            if isinstance(s, bytes):
                s = s.decode("utf-8", "ignore")
            s = str(s).strip()
            if s:
                self._fn(s)
        except Exception:
            pass
        finally:
            self._busy = False
        return n

    def flush(self):
        pass

    def isatty(self):
        return False


def fix_std_streams():
    sys.stdout = SafeStream(lambda m: Logger.info("yt: " + m))
    sys.stderr = SafeStream(lambda m: Logger.warning("yt: " + m))


fix_std_streams()

import yt_dlp  # noqa: E402  (setelah stream diperbaiki)

REQ_COOKIE = 7101
REQ_TREE = 7102
RESULT_OK = -1

COOKIE_FILE = "File cookies.txt (Paling Aman, Disimpan)"
COOKIE_NONE = "Tanpa cookie"
SAVE_AUTO = "Folder Otomatis (Tanya Sekali & Ingat)"
SAVE_MANUAL = "Manual (Pilih Folder Tiap Unduhan)"
SAVE_DEFAULT = "Download/SosmedDownloader (Bawaan)"

KV = """
<Lbl@Label>:
    font_size: '13sp'
    text_size: self.width, None
    halign: 'left'
    valign: 'middle'
    size_hint_y: None
    height: dp(24)
    color: .85, .85, .85, 1

<Sp@Spinner>:
    size_hint_y: None
    height: dp(46)
    font_size: '14sp'

<Root>:
    ScrollView:
        do_scroll_x: False
        GridLayout:
            cols: 1
            size_hint_y: None
            height: self.minimum_height
            padding: dp(16)
            spacing: dp(8)

            Label:
                text: 'Sosmed Downloader'
                font_size: '22sp'
                bold: True
                size_hint_y: None
                height: dp(44)

            Lbl:
                text: 'URL (YouTube, TikTok, Instagram, X, Facebook, dll):'
            BoxLayout:
                size_hint_y: None
                height: dp(48)
                spacing: dp(8)
                TextInput:
                    id: url
                    multiline: False
                    hint_text: 'https://...'
                Button:
                    text: 'Tempel'
                    size_hint_x: None
                    width: dp(80)
                    on_release: root.paste()

            Lbl:
                text: 'Jenis media:'
            Sp:
                id: kind
                text: 'Video + Audio'
                values: ['Video + Audio', 'Video Saja (tanpa suara)', 'Audio Saja']

            Lbl:
                text: 'Resolusi maksimum (video):'
            Sp:
                id: res
                text: 'Terbaik'
                values: ['Terbaik', '1080p', '720p', '480p', '360p']

            Lbl:
                text: 'Format audio (untuk Audio Saja):'
            Sp:
                id: acodec
                text: 'M4A / AAC (jika ada)'
                values: ['M4A / AAC (jika ada)', 'Asli sumber (WebM/Opus)']

            Lbl:
                text: 'Sumber Cookie (Atasi Error Chrome):'
                bold: True
            Sp:
                id: cookie
                on_text: root.on_cookie_mode(self.text)
            BoxLayout:
                size_hint_y: None
                height: dp(44)
                spacing: dp(8)
                Button:
                    text: 'Pilih cookies.txt'
                    on_release: root.pick_cookie()
                Button:
                    text: 'Hapus'
                    size_hint_x: None
                    width: dp(80)
                    on_release: root.delete_cookie()
            Lbl:
                id: cookie_lbl
                text: ''
                font_size: '12sp'

            Lbl:
                text: 'Lokasi Simpan:'
                bold: True
            Sp:
                id: save
                on_text: root.on_save_mode(self.text)
            BoxLayout:
                size_hint_y: None
                height: dp(44)
                spacing: dp(8)
                Button:
                    text: 'Pilih / Ganti Folder'
                    on_release: root.pick_folder_only()
            Lbl:
                id: folder_lbl
                text: ''
                font_size: '12sp'

            Button:
                id: btn
                text: 'UNDUH'
                bold: True
                size_hint_y: None
                height: dp(54)
                on_release: root.start()

            ProgressBar:
                id: bar
                max: 100
                value: 0
                size_hint_y: None
                height: dp(12)

            Label:
                id: status
                text: 'Siap.'
                font_size: '13sp'
                text_size: self.width, None
                halign: 'left'
                valign: 'top'
                size_hint_y: None
                height: max(dp(60), self.texture_size[1] + dp(10))
"""


# --------------------------------------------------------------------------
# Konfigurasi (disimpan di folder privat aplikasi)
# --------------------------------------------------------------------------
def data_dir():
    app = App.get_running_app()
    d = app.user_data_dir if app else os.path.expanduser("~/.sosmeddl")
    os.makedirs(d, exist_ok=True)
    return d


def cfg_path():
    return os.path.join(data_dir(), "config.json")


def cookie_path():
    return os.path.join(data_dir(), "cookies.txt")


def load_cfg():
    try:
        with open(cfg_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_cfg(cfg):
    try:
        with open(cfg_path(), "w", encoding="utf-8") as f:
            json.dump(cfg, f)
    except Exception:
        pass


# --------------------------------------------------------------------------
# Helper Android
# --------------------------------------------------------------------------
def _resolver():
    from jnius import autoclass
    return autoclass("org.kivy.android.PythonActivity").mActivity.getContentResolver()


def copy_uri_to_file(uri, dst):
    pfd = _resolver().openFileDescriptor(uri, "r")
    fd = pfd.detachFd()
    with os.fdopen(fd, "rb") as fin, open(dst, "wb") as fout:
        shutil.copyfileobj(fin, fout)


def copy_file_to_uri(src, uri):
    pfd = _resolver().openFileDescriptor(uri, "w")
    fd = pfd.detachFd()
    with open(src, "rb") as fin, os.fdopen(fd, "wb") as fout:
        shutil.copyfileobj(fin, fout)


def tree_display_name(uri_s):
    try:
        from jnius import autoclass
        Uri = autoclass("android.net.Uri")
        DC = autoclass("android.provider.DocumentsContract")
        doc_id = DC.getTreeDocumentId(Uri.parse(uri_s))
        name = doc_id.split(":", 1)[-1] if ":" in doc_id else doc_id
        return name or "Penyimpanan internal"
    except Exception:
        return uri_s


def save_to_tree(tree_uri_s, src):
    from jnius import autoclass
    Uri = autoclass("android.net.Uri")
    DC = autoclass("android.provider.DocumentsContract")
    tree = Uri.parse(tree_uri_s)
    parent = DC.buildDocumentUriUsingTree(tree, DC.getTreeDocumentId(tree))
    name = os.path.basename(src)
    # octet-stream agar Android tidak menambah ekstensi sendiri
    new_uri = DC.createDocument(_resolver(), parent, "application/octet-stream", name)
    if new_uri is None:
        raise RuntimeError("Gagal membuat file di folder tujuan.")
    copy_file_to_uri(src, new_uri)
    return tree_display_name(tree_uri_s) + "/" + name


def save_to_downloads(src):
    name = os.path.basename(src)
    mime = mimetypes.guess_type(name)[0] or "application/octet-stream"

    if platform != "android":
        dst_dir = os.path.join(os.path.expanduser("~"), "Downloads", "SosmedDownloader")
        os.makedirs(dst_dir, exist_ok=True)
        dst = os.path.join(dst_dir, name)
        shutil.copy2(src, dst)
        return dst

    from jnius import autoclass

    Version = autoclass("android.os.Build$VERSION")
    if Version.SDK_INT >= 29:
        ContentValues = autoclass("android.content.ContentValues")
        MediaStoreDownloads = autoclass("android.provider.MediaStore$Downloads")
        values = ContentValues()
        values.put("_display_name", name)
        values.put("mime_type", mime)
        values.put("relative_path", "Download/SosmedDownloader")
        uri = _resolver().insert(MediaStoreDownloads.EXTERNAL_CONTENT_URI, values)
        if uri is None:
            raise RuntimeError("Gagal membuat file di folder Download.")
        copy_file_to_uri(src, uri)
        return "Download/SosmedDownloader/" + name

    Environment = autoclass("android.os.Environment")
    base = Environment.getExternalStoragePublicDirectory(
        Environment.DIRECTORY_DOWNLOADS
    ).getAbsolutePath()
    dst_dir = os.path.join(base, "SosmedDownloader")
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, name)
    shutil.copy2(src, dst)
    return dst


def deliver(path, tree_uri):
    if platform == "android" and tree_uri:
        return save_to_tree(tree_uri, path)
    return save_to_downloads(path)


# --------------------------------------------------------------------------
# yt-dlp
# --------------------------------------------------------------------------
class QuietLogger:
    def debug(self, msg):
        pass

    def info(self, msg):
        pass

    def warning(self, msg):
        pass

    def error(self, msg):
        pass


def build_format(kind, res, acodec):
    h = None if res == "Terbaik" else int(res.replace("p", ""))
    hf = f"[height<={h}]" if h else ""
    # Tanpa FFmpeg tidak ada penggabungan video+audio terpisah,
    # jadi dipakai format tunggal (progresif) yang sudah berisi audio.
    if kind == "Video + Audio":
        return f"best{hf}[ext=mp4]/best{hf}/best"
    if kind == "Video Saja (tanpa suara)":
        return f"bestvideo{hf}[ext=mp4]/bestvideo{hf}/bestvideo"
    if acodec.startswith("M4A"):
        return "bestaudio[ext=m4a]/bestaudio"
    return "bestaudio"


def friendly_error(e):
    msg = re.sub(r"\x1b\[[0-9;]*m", "", str(e)).strip()
    low = msg.lower()
    hint = ""
    if "not a bot" in low or "sign in to confirm" in low or "cookies" in low:
        hint = ("\n\nYouTube meminta login. Pilih Sumber Cookie: File cookies.txt, "
                "lalu tekan 'Pilih cookies.txt' (format Netscape).")
    if not isinstance(e, yt_dlp.utils.DownloadError):
        tb = traceback.format_exc().strip().splitlines()[-4:]
        hint += "\n\nDetail teknis:\n" + "\n".join(tb)
    return msg[:500] + hint


# --------------------------------------------------------------------------
# UI
# --------------------------------------------------------------------------
class Root(BoxLayout):
    busy = False
    cfg = {}
    pending = None  # unduhan yang menunggu pemilihan folder

    def __init__(self, **kw):
        super().__init__(**kw)
        self.cfg = load_cfg()
        Clock.schedule_once(self._init_ui, 0)

    def _init_ui(self, dt):
        ids = self.ids
        ids.cookie.values = [COOKIE_FILE, COOKIE_NONE]
        ids.save.values = [SAVE_AUTO, SAVE_MANUAL, SAVE_DEFAULT]
        ids.cookie.text = self.cfg.get("cookie_mode") or COOKIE_FILE
        ids.save.text = self.cfg.get("save_mode") or SAVE_AUTO
        self.refresh_labels()

    # ---- util UI ----
    def ui(self, status=None, pct=None, enable=None):
        def _do(dt):
            if status is not None:
                self.ids.status.text = status
            if pct is not None:
                self.ids.bar.value = pct
            if enable is not None:
                self.ids.btn.disabled = not enable
        Clock.schedule_once(_do, 0)

    def refresh_labels(self):
        has_cookie = os.path.isfile(cookie_path()) and os.path.getsize(cookie_path()) > 0
        self.ids.cookie_lbl.text = (
            "cookies.txt: tersimpan ✓" if has_cookie else "cookies.txt: belum dipilih"
        )
        uri = self.cfg.get("tree_uri")
        mode = self.ids.save.text
        if mode == SAVE_AUTO:
            self.ids.folder_lbl.text = (
                "Folder tersimpan: " + tree_display_name(uri) if uri
                else "Folder belum dipilih (akan ditanya saat unduhan pertama)"
            )
        elif mode == SAVE_MANUAL:
            self.ids.folder_lbl.text = "Folder akan ditanya setiap kali mengunduh"
        else:
            self.ids.folder_lbl.text = "Disimpan ke Download/SosmedDownloader"

    def on_cookie_mode(self, text):
        if text:
            self.cfg["cookie_mode"] = text
            save_cfg(self.cfg)

    def on_save_mode(self, text):
        if text:
            self.cfg["save_mode"] = text
            save_cfg(self.cfg)
            if "folder_lbl" in self.ids:
                self.refresh_labels()

    def paste(self):
        try:
            self.ids.url.text = (Clipboard.paste() or "").strip()
        except Exception:
            pass

    # ---- cookies ----
    def pick_cookie(self):
        if platform != "android":
            self.ui(status="Pemilih file hanya tersedia di Android.")
            return
        from jnius import autoclass
        Intent = autoclass("android.content.Intent")
        act = autoclass("org.kivy.android.PythonActivity").mActivity
        intent = Intent(Intent.ACTION_OPEN_DOCUMENT)
        intent.addCategory(Intent.CATEGORY_OPENABLE)
        intent.setType("*/*")
        act.startActivityForResult(intent, REQ_COOKIE)

    def delete_cookie(self):
        try:
            os.remove(cookie_path())
        except OSError:
            pass
        self.refresh_labels()
        self.ui(status="cookies.txt dihapus.")

    def _got_cookie(self, uri):
        if uri is None:
            self.ui(status="Pemilihan cookies.txt dibatalkan.")
            return
        try:
            copy_uri_to_file(uri, cookie_path())
            with open(cookie_path(), "r", encoding="utf-8", errors="ignore") as f:
                head = f.read(4096)
            ok = "\t" in head or "Netscape" in head
            self.cfg["cookie_mode"] = COOKIE_FILE
            save_cfg(self.cfg)

            def _do(dt):
                self.ids.cookie.text = COOKIE_FILE
                self.refresh_labels()
            Clock.schedule_once(_do, 0)
            if ok:
                self.ui(status="cookies.txt disimpan dan akan diingat.")
            else:
                self.ui(status="File tersimpan, tapi formatnya tidak terlihat seperti "
                               "cookies.txt (Netscape). Pastikan file ekspor yang benar.")
        except Exception as e:
            self.ui(status=f"Gagal membaca file: {e}")

    # ---- folder ----
    def ask_folder(self):
        from jnius import autoclass
        Intent = autoclass("android.content.Intent")
        act = autoclass("org.kivy.android.PythonActivity").mActivity
        intent = Intent(Intent.ACTION_OPEN_DOCUMENT_TREE)
        intent.addFlags(
            Intent.FLAG_GRANT_READ_URI_PERMISSION
            | Intent.FLAG_GRANT_WRITE_URI_PERMISSION
            | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION
            | Intent.FLAG_GRANT_PREFIX_URI_PERMISSION
        )
        act.startActivityForResult(intent, REQ_TREE)

    def pick_folder_only(self):
        if platform != "android":
            self.ui(status="Pemilih folder hanya tersedia di Android.")
            return
        self.pending = None
        self.ask_folder()

    def _got_tree(self, uri):
        pending, self.pending = self.pending, None
        if uri is None:
            self.ui(status="Pemilihan folder dibatalkan.", enable=True)
            self.busy = False
            return
        try:
            from jnius import autoclass
            Intent = autoclass("android.content.Intent")
            _resolver().takePersistableUriPermission(
                uri,
                Intent.FLAG_GRANT_READ_URI_PERMISSION
                | Intent.FLAG_GRANT_WRITE_URI_PERMISSION,
            )
        except Exception:
            pass
        uri_s = uri.toString()
        manual = self.ids.save.text == SAVE_MANUAL and pending is not None
        if not manual:
            self.cfg["tree_uri"] = uri_s
            if pending is None:
                self.cfg["save_mode"] = SAVE_AUTO
            save_cfg(self.cfg)

        def _do(dt):
            if pending is None:
                self.ids.save.text = SAVE_AUTO
            self.refresh_labels()
        Clock.schedule_once(_do, 0)

        if pending:
            self.launch(pending["url"], pending["fmt"], pending["use_cookie"], uri_s)
        else:
            self.ui(status="Folder tersimpan dan akan diingat.")

    def on_activity_result(self, req, res, intent):
        if req not in (REQ_COOKIE, REQ_TREE):
            return
        uri = intent.getData() if (res == RESULT_OK and intent is not None) else None
        if req == REQ_COOKIE:
            self._got_cookie(uri)
        else:
            self._got_tree(uri)

    # ---- unduh ----
    def start(self):
        url = self.ids.url.text.strip()
        if not url:
            self.ui(status="URL tidak boleh kosong!")
            return
        if self.busy:
            return

        use_cookie = self.ids.cookie.text == COOKIE_FILE
        if use_cookie and not (os.path.isfile(cookie_path()) and os.path.getsize(cookie_path()) > 0):
            self.ui(status="Mode cookie aktif tapi cookies.txt belum dipilih.\n"
                           "Tekan 'Pilih cookies.txt', atau ganti Sumber Cookie ke 'Tanpa cookie'.")
            return

        fmt = build_format(self.ids.kind.text, self.ids.res.text, self.ids.acodec.text)
        mode = self.ids.save.text
        self.busy = True
        self.ui(pct=0, enable=False)

        if platform == "android" and mode == SAVE_MANUAL:
            self.pending = {"url": url, "fmt": fmt, "use_cookie": use_cookie}
            self.ui(status="Pilih folder tujuan...")
            self.ask_folder()
            return
        if platform == "android" and mode == SAVE_AUTO:
            if not self.cfg.get("tree_uri"):
                self.pending = {"url": url, "fmt": fmt, "use_cookie": use_cookie}
                self.ui(status="Pilih folder tujuan (hanya ditanya sekali)...")
                self.ask_folder()
                return
            self.launch(url, fmt, use_cookie, self.cfg["tree_uri"])
            return
        self.launch(url, fmt, use_cookie, None)

    def launch(self, url, fmt, use_cookie, tree_uri):
        self.busy = True
        self.ui(status="Mengambil informasi...", pct=0, enable=False)
        threading.Thread(
            target=self.worker, args=(url, fmt, use_cookie, tree_uri), daemon=True
        ).start()

    def worker(self, url, fmt, use_cookie, tree_uri):
        fix_std_streams()
        tmp = os.path.join(data_dir(), "tmp")
        shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(tmp, exist_ok=True)

        def hook(d):
            if d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                done = d.get("downloaded_bytes") or 0
                pct = (done / total * 100) if total else 0
                self.ui(status=f"Mengunduh... {pct:.1f}%", pct=pct)
            elif d.get("status") == "finished":
                self.ui(status="Memproses file...", pct=100)

        opts = {
            "format": fmt,
            "outtmpl": os.path.join(tmp, "%(title).120B [%(id)s].%(ext)s"),
            "noplaylist": True,
            "progress_hooks": [hook],
            "logger": QuietLogger(),
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "retries": 5,
            "fragment_retries": 5,
        }
        try:
            if use_cookie:
                cp = os.path.join(tmp, "cookies.txt")
                shutil.copy(cookie_path(), cp)  # salinan, supaya file asli tidak berubah
                opts["cookiefile"] = cp

            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if info.get("_type") == "playlist" and info.get("entries"):
                    info = info["entries"][0]
                req = info.get("requested_downloads") or []
                path = req[0]["filepath"] if req else ydl.prepare_filename(info)
            if not os.path.exists(path):
                raise RuntimeError("File hasil unduhan tidak ditemukan.")

            self.ui(status="Menyimpan ke folder tujuan...")
            try:
                where = deliver(path, tree_uri)
            except Exception as e:
                if tree_uri and "ecurity" in str(e):
                    self.cfg.pop("tree_uri", None)
                    save_cfg(self.cfg)
                    Clock.schedule_once(lambda dt: self.refresh_labels(), 0)
                    raise RuntimeError("Izin ke folder hilang. Tekan UNDUH lagi lalu pilih folder ulang.")
                raise
            self.ui(status=f"Selesai!\nTersimpan di: {where}", pct=100)
        except Exception as e:
            self.ui(status="Gagal: " + friendly_error(e), pct=0)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            self.busy = False
            self.ui(enable=True)


class SosmedApp(App):
    title = "Sosmed Downloader"

    def build(self):
        Builder.load_string(KV)
        self.root_widget = Root()
        return self.root_widget

    def on_start(self):
        if platform == "android":
            try:
                from android import activity as android_activity
                android_activity.bind(on_activity_result=self.root_widget.on_activity_result)
            except Exception as e:
                Logger.warning("bind activity result gagal: %s", e)
            try:
                from android.permissions import request_permissions, Permission
                request_permissions([Permission.WRITE_EXTERNAL_STORAGE])
            except Exception:
                pass


if __name__ == "__main__":
    SosmedApp().run()
