"""Serveur FastAPI : analyse (/api/info) et téléchargement (/api/download) de vidéos via yt-dlp."""
import asyncio
import os
import re
import shutil
import tempfile
import time
from collections import defaultdict, deque
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp
from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.background import BackgroundTask

# ---------- Configuration (modifiable par variables d'environnement) ----------
MAX_DURATION = int(os.getenv("MAX_DURATION", 3600))   # durée max en secondes (1 h)
MAX_PARALLEL = int(os.getenv("MAX_PARALLEL", 2))      # téléchargements simultanés max
TMP_ROOT = Path(tempfile.gettempdir()) / "videodl"    # dossier des fichiers temporaires
TMP_ROOT.mkdir(exist_ok=True)

# Domaines autorisés -> nom affiché (sert aussi de protection contre les liens louches)
PLATEFORMES = {
    "youtube.com": "YouTube", "youtu.be": "YouTube",
    "tiktok.com": "TikTok",
    "instagram.com": "Instagram",
    "facebook.com": "Facebook", "fb.watch": "Facebook",
    "twitter.com": "X / Twitter", "x.com": "X / Twitter",
    "reddit.com": "Reddit", "redd.it": "Reddit",
    "twitch.tv": "Twitch",
    "vimeo.com": "Vimeo", "dailymotion.com": "Dailymotion",
}

# Options communes à yt-dlp
OPTS_BASE = {"quiet": True, "no_warnings": True, "noplaylist": True, "socket_timeout": 20}
if os.getenv("COOKIES_FILE"):  # optionnel : fichier cookies.txt (utile contre les blocages YouTube)
    OPTS_BASE["cookiefile"] = os.getenv("COOKIES_FILE")

app = FastAPI(title="VideoDL")
sem = asyncio.Semaphore(MAX_PARALLEL)


# ---------- Rate limiting simple en mémoire (par IP) ----------
_hits: dict = defaultdict(deque)

def limiter(request: Request, nom: str, max_req: int, fenetre: int = 60):
    """Refuse la requête si l'IP a dépassé max_req appels sur la dernière minute."""
    # Derrière Render/Railway, la vraie IP est dans X-Forwarded-For
    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "?")
    ip = ip.split(",")[0].strip()
    file, now = _hits[(nom, ip)], time.time()
    while file and now - file[0] > fenetre:
        file.popleft()
    if len(file) >= max_req:
        raise HTTPException(429, "Trop de requêtes, réessaie dans une minute.")
    file.append(now)


# ---------- Validation du lien ----------
def valider_url(url: str):
    """Retourne (url propre, plateforme) ou lève une erreur 400."""
    url = (url or "").strip()
    p = urlparse(url)
    if len(url) > 2000 or p.scheme not in ("http", "https") or not p.hostname:
        raise HTTPException(400, "Lien invalide. Colle une adresse complète (https://...).")
    host = p.hostname.lower()
    for domaine, nom in PLATEFORMES.items():
        if host == domaine or host.endswith("." + domaine):
            return url, nom
    raise HTTPException(400, "Plateforme non supportée.")


def traduire_erreur(e: Exception) -> str:
    """Transforme les erreurs techniques de yt-dlp en messages clairs."""
    m = str(e).lower()
    if "private" in m:
        return "Cette vidéo est privée."
    if "sign in" in m or "log in" in m or "login" in m or "cookies" in m or "bot" in m:
        return "Cette vidéo demande une connexion, ou la plateforme bloque le serveur."
    if "not available in your country" in m or "geo" in m:
        return "Cette vidéo n'est pas disponible dans la région du serveur."
    if "unavailable" in m or "removed" in m or "deleted" in m or "does not exist" in m or "404" in m:
        return "Vidéo supprimée ou indisponible."
    if "unsupported url" in m or "no video" in m:
        return "Aucune vidéo trouvée sur ce lien."
    return "Impossible de récupérer cette vidéo. Réessaie plus tard."


class InfoIn(BaseModel):
    url: str


# ---------- POST /api/info : infos de la vidéo ----------
@app.post("/api/info")
async def info(corps: InfoIn, request: Request):
    limiter(request, "info", 10)
    url, plateforme = valider_url(corps.url)
    try:
        with yt_dlp.YoutubeDL(OPTS_BASE) as ydl:
            data = await run_in_threadpool(lambda: ydl.extract_info(url, download=False))
    except yt_dlp.utils.DownloadError as e:
        raise HTTPException(422, traduire_erreur(e))
    if data.get("entries"):  # playlist : on garde la première vidéo
        data = list(data["entries"])[0]
    hauteurs = [f["height"] for f in data.get("formats", []) if f.get("height") and f.get("vcodec") != "none"]
    return {
        "titre": data.get("title") or "Sans titre",
        "miniature": data.get("thumbnail"),
        "duree": data.get("duration") or 0,
        "plateforme": plateforme,
        "hauteur_max": max(hauteurs) if hauteurs else None,  # le front grise les qualités trop hautes
        "trop_longue": (data.get("duration") or 0) > MAX_DURATION,
    }


# ---------- Nettoyage des vieux fichiers temporaires ----------
def purger_anciens(age_max: int = 3600):
    for d in TMP_ROOT.iterdir():
        if time.time() - d.stat().st_mtime > age_max:
            shutil.rmtree(d, ignore_errors=True)


def choisir_format(fmt: str, qualite: str) -> str:
    """Construit le sélecteur de format yt-dlp (vidéo+audio fusionnés par ffmpeg)."""
    if fmt == "mp3":
        return "bestaudio/best"
    if qualite == "best":
        return "bestvideo+bestaudio/best"
    h = int(qualite)
    return f"bestvideo[height<={h}]+bestaudio/best[height<={h}]/best"


# ---------- GET /api/download : télécharge le fichier ----------
@app.get("/api/download")
async def download(request: Request, url: str, format: str = "mp4", quality: str = "best"):
    limiter(request, "dl", 3)
    url, _ = valider_url(url)
    if format not in ("mp4", "mp3") or quality not in ("360", "720", "1080", "best"):
        raise HTTPException(400, "Paramètres invalides.")

    purger_anciens()
    dossier = Path(tempfile.mkdtemp(dir=TMP_ROOT))  # dossier temporaire unique pour cette demande
    opts = {**OPTS_BASE, "format": choisir_format(format, quality),
            "outtmpl": str(dossier / "%(id)s.%(ext)s")}
    if format == "mp3":   # ffmpeg extrait l'audio et le convertit en MP3
        opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}]
    else:                 # on force un conteneur MP4 (compatible partout)
        opts["merge_output_format"] = "mp4"
        opts["postprocessors"] = [{"key": "FFmpegVideoConvertor", "preferedformat": "mp4"}]

    def travail():
        with yt_dlp.YoutubeDL(opts) as ydl:
            infos = ydl.extract_info(url, download=False)
            if (infos.get("duration") or 0) > MAX_DURATION:
                raise HTTPException(413, f"Vidéo trop longue (max {MAX_DURATION // 60} min).")
            ydl.process_ie_result(infos, download=True)
            return infos

    try:
        async with sem:  # limite le nombre de téléchargements en parallèle
            infos = await run_in_threadpool(travail)
        fichiers = [f for f in dossier.iterdir() if f.is_file()]
        if not fichiers:
            raise RuntimeError("fichier introuvable")
        fichier = max(fichiers, key=lambda f: f.stat().st_size)
    except HTTPException:
        shutil.rmtree(dossier, ignore_errors=True)
        raise
    except yt_dlp.utils.DownloadError as e:
        shutil.rmtree(dossier, ignore_errors=True)
        raise HTTPException(422, traduire_erreur(e))
    except Exception:
        shutil.rmtree(dossier, ignore_errors=True)
        raise HTTPException(500, "Erreur pendant le téléchargement.")

    # Nom de fichier propre
    nom = re.sub(r"[^\w\- ]", "", infos.get("title") or "video").strip()[:80] or "video"
    return FileResponse(
        fichier, filename=f"{nom}{fichier.suffix}",
        media_type="audio/mpeg" if format == "mp3" else "video/mp4",
        background=BackgroundTask(shutil.rmtree, dossier, ignore_errors=True),  # suppression après envoi
    )


# ---------- Site statique (doit rester en dernier) ----------
app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
