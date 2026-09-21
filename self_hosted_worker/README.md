# Auto Director - Worker PC V9.2

Le worker PC garde le Studio web sur Render et deplace le calcul video lourd sur le PC local. Le transport de production est HTTPS : le PC n'a pas besoin des identifiants PostgreSQL ou Redis.

## Installation recommandee

Depuis le Studio, telecharge puis lance `INSTALL_AUTO_DIRECTOR_WORKER.bat`.

L'installateur :
1. verifie qu'un Python reel >= 3.10 est disponible et installe Python 3.12 avec `winget` si necessaire ;
2. arrete proprement un ancien agent Auto Director ;
3. telecharge la derniere version du depot ;
4. installe le depot dans `%LOCALAPPDATA%\AutoDirector\repo` ;
5. configure l'agent local au demarrage de Windows ;
6. demarre l'agent local 2.8 et verifie son endpoint local `127.0.0.1:8765/status`.

Le Studio peut ensuite demander a l'agent de demarrer ou d'arreter le worker PC.

## Architecture securisee

Le navigateur authentifie la session Studio puis contacte uniquement l'agent local sur `127.0.0.1:8765`. L'agent ouvre une session worker via HTTPS avec `https://auto-director-web.onrender.com` et recoit un jeton worker temporaire.

Le worker PC utilise ce jeton pour :
- publier son heartbeat ;
- reclamer un job ;
- telecharger les rushs necessaires via l'API securisee ;
- envoyer la progression ;
- televerser le MP4 final ;
- terminer ou signaler l'echec du job.

Aucun mot de passe PostgreSQL/Redis et aucune URL de base de donnees ne sont requis sur le PC en mode normal.

## Profils automatiques

`detect_profile.py` detecte la RAM, le nombre de threads CPU et, si disponible, une carte NVIDIA avec sa VRAM. Le choix reste prudent :
- `safe-minimal` : machine inconnue ou tres limitee ; 720x1280, 24 fps, charge minimale ;
- `safe-light` : machine modeste ; 720x1280, 24 fps, modules lourds desactives ;
- `safe-balanced` : machine confortable ; 720x1280, 30 fps ;
- `safe-local-ai` : active seulement si les ressources detectees sont suffisantes, avec modele local plafonne a `qwen2.5vl:3b`.

Le bot n'active pas automatiquement le 1080p et limite volontairement la charge locale.

## Quality Engine V9.2

Selon le profil materiel, le worker peut activer des composants locaux facultatifs :
- detection de scenes ;
- analyse audio / impacts ;
- Smart Crop ;
- transcription locale `faster-whisper` ;
- Ollama + Qwen2.5-VL 3B.

Si un module facultatif ne peut pas etre installe ou execute, le worker continue avec le moteur core au lieu de bloquer le rendu.

## Protections ressources

- un seul job video a la fois ;
- FFmpeg limite a quelques threads ;
- processus Windows en priorite `BelowNormal` ;
- 24 ou 30 fps suivant le profil ;
- Ollama limite a 1 requete parallele et 1 modele charge ;
- verification du materiel avant activation des modules lourds ;
- fallback automatique vers le moteur core si l'IA ou les modules qualite ne sont pas disponibles.

## Diagnostic avant demarrage

`doctor.py` verifie en mode worker PC :
- Python ;
- FFmpeg ;
- l'acces a l'API worker HTTPS du Studio ;
- le profil materiel ;
- Ollama si l'IA locale est activee.

Le diagnostic signale egalement si des secrets cloud `DATABASE_URL` ou `REDIS_URL` sont presents alors qu'ils ne sont pas necessaires au worker PC.

## Priorite PC / Render

Quand le worker local tourne, il publie un heartbeat HTTPS. Le backend peut alors donner la priorite au PC. Lorsque le worker PC s'arrete et que le heartbeat expire, le worker Render reste disponible comme secours.

Le Studio affiche l'etat du worker et les informations utiles de profil, resolution et file de jobs.

## Securite

- l'agent local ecoute uniquement sur la boucle locale `127.0.0.1` ;
- l'origine web autorisee est limitee au Studio officiel Render ;
- le worker initie uniquement des connexions sortantes ;
- aucun port du routeur n'a besoin d'etre ouvert ;
- les jetons worker sont temporaires et renouvelables ;
- `.gitignore` protege `.env` et `.auto_profile.env` contre un commit accidentel.

Si tu lances manuellement `START_LOCAL_WORKER_WINDOWS.ps1` sans passer par le Studio, il peut demander le mot de passe du Studio afin d'obtenir lui-meme un jeton worker HTTPS. Le mot de passe n'est pas stocke par defaut.
