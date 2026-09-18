# Auto Director - Worker local sans credits API

Ce mode garde le Studio web sur Render mais deplace le calcul lourd sur ton PC. Aucun credit OpenAI n'est requis quand `LOCAL_VLM_URL` pointe vers Ollama.

## Stack locale
- FFmpeg: montage et analyse video
- Ollama + Qwen2.5-VL: vision, hook, reordonnancement des moments, captions, critic
- V8 Moment Ranker: mouvement, audio, changements de scene, payoff
- PostgreSQL/Redis Render: uniquement controle et file de jobs

## Demarrage Windows
1. Installe Python 3.12 et Ollama.
2. Dans Ollama, le lanceur telecharge automatiquement le modele configure.
3. Dans Render, ouvre `auto-director-postgres` et `auto-director-queue`, copie leurs URL de connexion **externes**.
4. Copie `.env.example` vers `.env` (le script le fait au premier lancement) et remplace `DATABASE_URL` / `REDIS_URL`.
5. Lance `START_LOCAL_WORKER_WINDOWS.ps1`.
6. Garde le worker ouvert/minimise. Les jobs du site seront pris automatiquement.

## Modeles conseilles
- 4-6 Go VRAM: `qwen2.5vl:3b`
- 8-12 Go VRAM: `qwen2.5vl:7b`
- 12 Go+ VRAM: `gemma3:12b` ou un VLM plus gros si la machine le supporte
- CPU seulement: le bot fonctionne, mais l'analyse VLM sera plus lente. La V8 heuristique reste disponible si Ollama n'est pas configure.

## Important
Ce mode evite les credits par requete, mais il ne cree pas de calcul gratuit: la puissance vient de ton PC, de ton GPU et de l'electricite. Si le PC est eteint, les jobs restent en attente et le worker Render peut rester comme fallback heuristique.

## Securite
Ne publie jamais le fichier `.env`. Il contient les URL de connexion privees a Postgres/Redis. Le worker initie uniquement des connexions sortantes; aucun port du routeur n'a besoin d'etre ouvert.
