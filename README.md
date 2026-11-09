# VideoDL – site de téléchargement de vidéos

FastAPI + yt-dlp + ffmpeg, front en HTML/CSS/JS pur.

## Arborescence
```
videodl/
├── main.py            # API (FastAPI) : /api/info et /api/download
├── requirements.txt   # dépendances Python
├── Dockerfile         # pour le déploiement (inclut ffmpeg)
├── README.md
└── static/
    ├── index.html     # page
    ├── style.css      # thème sombre responsive
    └── app.js         # logique front
```

## Lancer en local (Windows)
1. Installe **Python 3.10+** (python.org, coche « Add to PATH »).
2. Installe **ffmpeg** : dans PowerShell, `winget install Gyan.FFmpeg`, puis **ferme et rouvre** le terminal. Vérifie avec `ffmpeg -version`.
3. Dans le dossier du projet :
```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload
```
4. Ouvre http://127.0.0.1:8000

Mise à jour de yt-dlp (à faire régulièrement, les plateformes changent souvent) : `pip install -U yt-dlp`

## Variables d'environnement (optionnelles)
| Variable | Défaut | Rôle |
|---|---|---|
| `MAX_DURATION` | 3600 | durée max d'une vidéo (secondes) |
| `MAX_PARALLEL` | 2 | téléchargements simultanés |
| `COOKIES_FILE` | – | chemin d'un `cookies.txt` (aide contre les blocages YouTube/Instagram) |

## Déployer en ligne
**Render** : pousse le projet sur GitHub → New + Web Service → choisis le repo → Runtime **Docker** → Deploy.
**Railway** : New Project → Deploy from GitHub → il détecte le Dockerfile automatiquement.
**VPS (Ubuntu)** :
```bash
sudo apt install -y python3-venv ffmpeg
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```
Puis mets Nginx + HTTPS (certbot) devant, et lance uvicorn via systemd.

## À savoir
- **YouTube et Instagram bloquent souvent les IP de datacenters** (Render, Railway, VPS) : « Sign in to confirm you're not a bot ». En local ça marche, en ligne il faut parfois des cookies (`COOKIES_FILE`) ou un proxy résidentiel.
- Le plan gratuit de Render est limité en CPU/RAM : garde `MAX_PARALLEL` bas.
- Le rate limiting est en mémoire (se réinitialise au redémarrage, une seule instance).
- Télécharger du contenu protégé peut violer les conditions des plateformes et le droit d'auteur. Rends un site public seulement en connaissance de cause.
