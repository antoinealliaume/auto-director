# Auto Director Studio

Studio privé de création vidéo automatisée : upload de rushs, queue Redis, rendu FFmpeg, TTS et suivi des jobs.

## Déploiement Render

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/antoinealliaume/auto-director)

Le Blueprint `render.yaml` utilise les ressources Render existantes :
- `auto-director-postgres`
- `auto-director-queue`

Pendant le déploiement, Render demandera uniquement `STUDIO_PASSWORD`.

## Services

- `auto-director-web` : dashboard + API FastAPI
- `auto-director-worker` : worker de rendu vidéo

## Pipeline

Upload → Queue → FFmpeg vertical 720×1280 → TTS → rendu MP4 → galerie
