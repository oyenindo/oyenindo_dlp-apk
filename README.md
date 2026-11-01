# Sosmed Downloader (APK)

Versi Android dari script `Social_Media_Downloader.py` (yt-dlp, tanpa FFmpeg).

## Cara A - GitHub Actions
1. Buat repo baru di GitHub, unggah SEMUA isi folder ini (termasuk folder `.github`).
2. Buka tab **Actions** > **Build APK** > **Run workflow**.
3. Setelah hijau, unduh APK di bagian **Artifacts**.

## Cara B - Google Colab
1. Buka `build_apk_colab.ipynb` di Colab.
2. Jalankan sel berurutan, unggah `main.py` dan `buildozer.spec` saat diminta.
3. APK terunduh otomatis di akhir.

Hasil unduhan tersimpan di folder `Download/SosmedDownloader`.
