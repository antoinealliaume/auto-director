# Auto Director - Worker local adaptatif sans credits IA

Ce mode garde le Studio web disponible mais deplace le calcul lourd sur ton PC. Aucun credit OpenAI n'est necessaire pour le Director local.

## Demarrage le plus simple
Sous Windows, double-clique sur `START_LOCAL_WORKER.bat`.

Au premier lancement :
1. le script cree automatiquement `self_hosted_worker/.env` ;
2. il utilise par defaut `https://auto-director-web.onrender.com` ;
3. il te demande le mot de passe du Studio dans une saisie masquee ;
4. il ouvre une session HTTPS et recupere la configuration Postgres/Redis en memoire ;
5. il detecte le materiel ;
6. il installe l'environnement Python local si necessaire ;
7. il lance un diagnostic complet ;
8. il demarre le worker.

Tu n'as donc plus besoin de connaitre ton CPU, ta RAM, ta carte graphique, ni de copier manuellement les mots de passe Postgres/Redis.

Tu peux aussi double-cliquer sur `CHECK_MY_PC.bat` pour voir le profil choisi sans lancer un rendu.

## Profils automatiques
`detect_profile.py` detecte la RAM, le nombre de threads CPU et, si disponible, une carte NVIDIA avec sa VRAM. Le choix reste volontairement prudent :
- `safe-minimal` : machine inconnue ou tres limitee ; V8 heuristique, 720x1280, 24 fps, 1-2 threads, pas de revision lourde ;
- `safe-light` : machine modeste ; V8 complet, 720x1280, 24 fps, IA visuelle lourde desactivee ;
- `safe-balanced` : machine confortable sans GPU suffisamment fiable ; 720x1280, 30 fps, toujours sans forcer un VLM sur le CPU ;
- `safe-local-ai` : seulement si une marge suffisante est detectee, notamment RAM correcte + GPU NVIDIA d'environ 6 Go de VRAM ou plus. Le modele reste plafonne a `qwen2.5vl:3b`.

Le bot ne selectionne jamais automatiquement un modele plus gros que 3B et n'active jamais le 1080p automatiquement.

## Protections ressources
- un seul job video a la fois ;
- FFmpeg limite a quelques threads ;
- processus Windows en priorite `BelowNormal` ;
- 24 ou 30 fps suivant le profil ;
- Ollama limite a 1 requete parallele et 1 modele charge ;
- contexte VLM reduit ;
- maximum 3 images par appel VLM ;
- verification de la RAM libre avant chaque appel IA ;
- si la RAM devient trop faible, l'appel IA est saute et le Director V8 continue ;
- si Ollama n'est pas installe ou ne repond plus, le worker continue en mode V8 leger ;
- si le materiel ne peut pas etre mesure de maniere fiable, le systeme choisit le profil le plus prudent.

## Doctor avant demarrage
`doctor.py` verifie automatiquement :
- Python ;
- FFmpeg ;
- PostgreSQL ;
- Redis ;
- profil materiel ;
- Ollama si l'IA locale est activee.

Un probleme critique bloque le demarrage avec un message clair au lieu de lancer un worker partiellement casse.

## Priorite automatique local / cloud
Quand le worker local tourne, il publie un heartbeat Redis contenant son profil, sa resolution, son nombre de threads et son mode IA. Le worker Render detecte ce heartbeat et se met en retrait.

Quand tu fermes le worker local ou eteins ton PC, le heartbeat expire apres quelques secondes et Render reprend automatiquement comme secours.

Le Studio affiche egalement l'etat courant : `PC local prioritaire` ou `Render en secours`, ainsi que le profil, la resolution et la file de jobs.

## Stack
- FFmpeg : montage, analyse video et rendu ;
- V8 Moment Ranker : mouvement, audio, cuts et payoff ;
- V8 Director : simulations multi-strategies ;
- Critic : controle qualite + revision ;
- Ollama + Qwen2.5-VL 3B : vision locale facultative ;
- PostgreSQL / Redis Render : controle, metadonnees et file de jobs ;
- Studio HTTPS bootstrap : configuration locale sans copier les secrets de base de donnees.

## Securite
Le mot de passe du Studio peut rester uniquement en memoire : laisse `STUDIO_PASSWORD=` vide dans `.env` et le lanceur le demandera a chaque demarrage. Les URL Postgres/Redis recues par HTTPS restent elles aussi uniquement dans l'environnement du processus et disparaissent lorsque la fenetre est fermee.

Le worker initie uniquement des connexions sortantes ; aucun port entrant et aucune ouverture de routeur ne sont necessaires. `.gitignore` protege egalement `.env` et `.auto_profile.env` contre un commit accidentel.
