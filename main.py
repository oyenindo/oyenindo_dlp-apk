import os
import mimetypes
import shutil
import threading

try:
    import certifi
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
except Exception:
    pass

from kivy.app import App
from kivy.clock import Clock
from kivy.core.clipboard import Clipboard
from kivy.lang import Builder
from kivy.uix.boxlayout import BoxLayout
from kivy.utils import platform

import yt_dlp

KV = """
<Root>:
    orientation: 'vertical'
    padding: dp(16)
    spacing: dp(10)

    Label:
        text: 'Sosmed Downloader'
        font_size: '22sp'
        bold: True
        size_hint_y: None
        height: dp(44)

    Label:
        text: 'URL (YouTube, TikTok, Instagram, X, Facebook, dll):'
        font_size: '13sp'
        text_size: self.width, None
        halign: 'left'
        size_hint_y: None
        height: dp(22)

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

    Label:
        text: 'Jenis media:'
        font_size: '13sp'
        text_size: self.width, None
        halign: 'left'
        size_hint_y: None
        height: dp(22)
    Spinner:
        id: kind
        text: 'Video + Audio'
        values: ['Video + Audio', 'Video Saja (tanpa suara)', 'Audio Saja']
        size_hint_y: None
        height: dp(46)

    Label:
        text: 'Resolusi maksimum (video):'
        font_size: '13sp'
        text_size: self.width, None
        halign: 'left'
        size_hint_y: None
        height: dp(22)
    Spinner:
        id: res
        text: 'Terbaik'
        values: ['Terbaik', '1080p', '720p', '480p', '360p']
        size_hint_y: None
        height: dp(46)

    Label:
        text: 'Format audio (untuk Audio Saja):'
        font_size: '13sp'
        text_size: self.width, None
        halign: 'left'
        size_hint_y: None
        height: dp(22)
    Spinner:
        id: acodec
        text: 'M4A / AAC (jika ada)'
        values: ['M4A / AAC (jika ada)', 'Asli sumber (WebM/Opus)']
        size_hint_y: None
        height: dp(46)

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
"""


def save_to_downloads(src):
    """Salin file ke folder Download/SosmedDownloader. Mengembalikan lokasi (teks)."""
    name = os.path.basename(src)
    mime = mimetypes.guess_type(name)[0] or "application/octet-stream"

    if platform != "android":
        dst_dir = os.path.join(os.path.expanduser("~"), "Downloads", "SosmedDownloader")
        os.makedirs(dst_dir, exist_ok=True)
        dst = os.path.join(dst_dir, name)
        shutil.copy2(src, dst)
        return dst

    from jnius import autoclass, cast

    Version = autoclass("android.os.Build$VERSION")
    if Version.SDK_INT >= 29:
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        ContentValues = autoclass("android.content.ContentValues")
        MediaStore = autoclass("android.provider.MediaStore$Downloads")
        FileInputStream = autoclass("java.io.FileInputStream")
        FileUtils = autoclass("android.os.FileUtils")

        resolver = PythonActivity.mActivity.getContentResolver()
        values = ContentValues()
        values.put("_display_name", name)
        values.put("mime_type", mime)
        values.put("relative_path", "Download/SosmedDownloader")
        uri = resolver.insert(MediaStore.EXTERNAL_CONTENT_URI, values)
        out = resolver.openOutputStream(uri)
        fis = FileInputStream(src)
        FileUtils.copy(
            cast("java.io.InputStream", fis),
            cast("java.io.OutputStream", out),
        )
        fis.close()
        out.close()
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


class Root(BoxLayout):
    busy = False

    def paste(self):
        try:
            self.ids.url.text = (Clipboard.paste() or "").strip()
        except Exception:
            pass

    def ui(self, status=None, pct=None, enable=None):
        def _do(dt):
            if status is not None:
                self.ids.status.text = status
            if pct is not None:
                self.ids.bar.value = pct
            if enable is not None:
                self.ids.btn.disabled = not enable
        Clock.schedule_once(_do, 0)

    def start(self):
        url = self.ids.url.text.strip()
        if not url:
            self.ui(status="URL tidak boleh kosong!")
            return
        if self.busy:
            return
        self.busy = True
        self.ui(status="Mengambil informasi...", pct=0, enable=False)
        fmt = build_format(self.ids.kind.text, self.ids.res.text, self.ids.acodec.text)
        threading.Thread(target=self.worker, args=(url, fmt), daemon=True).start()

    def worker(self, url, fmt):
        tmp = os.path.join(App.get_running_app().user_data_dir, "tmp")
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
            "restrictfilenames": False,
            "progress_hooks": [hook],
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "retries": 5,
            "fragment_retries": 5,
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if info.get("_type") == "playlist" and info.get("entries"):
                    info = info["entries"][0]
                req = info.get("requested_downloads") or []
                path = req[0]["filepath"] if req else ydl.prepare_filename(info)
            if not os.path.exists(path):
                raise RuntimeError("File hasil unduhan tidak ditemukan.")
            self.ui(status="Menyimpan ke folder Download...")
            where = save_to_downloads(path)
            self.ui(status=f"Selesai!\nTersimpan di: {where}", pct=100)
        except Exception as e:
            self.ui(status=f"Gagal: {e}", pct=0)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            self.busy = False
            self.ui(enable=True)


class SosmedApp(App):
    title = "Sosmed Downloader"

    def build(self):
        Builder.load_string(KV)
        return Root()

    def on_start(self):
        if platform == "android":
            try:
                from android.permissions import request_permissions, Permission
                request_permissions([Permission.WRITE_EXTERNAL_STORAGE])
            except Exception:
                pass


if __name__ == "__main__":
    SosmedApp().run()
