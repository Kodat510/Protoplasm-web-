"""Build dist/Protoplasm-itch.zip with pygame, pygbag and imageio-ffmpeg."""
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile

from imageio_ffmpeg import get_ffmpeg_exe

from game import SOUND_FILES


ROOT = Path(__file__).resolve().parent


def main():
    with TemporaryDirectory(prefix="protoplasm-", dir=ROOT) as temp:
        project = Path(temp) / "protoplasm"
        project.mkdir()
        shutil.copy2(ROOT / "game.py", project / "main.py")
        assets = project / "assets"
        sounds = assets / "SFXs"
        sounds.mkdir(parents=True)
        for source in (ROOT / "assets").iterdir():
            if source.is_file():
                shutil.copy2(source, assets / source.name)

        ffmpeg = get_ffmpeg_exe()
        for name in SOUND_FILES.values():
            source = ROOT / "assets" / "SFXs" / (name + ".mp3")
            target = sounds / (name + ".ogg")
            subprocess.run([ffmpeg, "-loglevel", "error", "-i", str(source),
                            "-c:a", "libvorbis", "-ac", "1", "-ar", "44100",
                            str(target)], check=True)

        subprocess.run([sys.executable, "-m", "pygbag", "--build", "--no_opt",
                        "--title", "Protoplasm", str(project)], check=True)
        web = project / "build" / "web"
        index = web / "index.html"
        html = index.read_text(encoding="utf-8")
        css = """
<style>
body { background: #0c0d19 !important; }
#canvas {
    position: absolute !important;
    inset: 0 !important;
    margin: auto !important;
    width: min(100vw, 177.7778vh) !important;
    height: min(100vh, 56.25vw) !important;
}
</style>
"""
        index.write_text(html.replace("</head>", css + "</head>", 1), encoding="utf-8")
        dist = ROOT / "dist"
        dist.mkdir(exist_ok=True)
        with ZipFile(dist / "Protoplasm-itch.zip", "w", ZIP_DEFLATED) as archive:
            for name in ("index.html", "protoplasm.apk", "protoplasm.tar.gz", "favicon.png"):
                archive.write(web / name, name)


if __name__ == "__main__":
    main()
