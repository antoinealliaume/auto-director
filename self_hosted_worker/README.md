# Auto Director - Worker local adaptatif sans credits IA

Ce mode garde le Studio web disponible mais deplace le calcul lourd sur ton PC. Aucun credit OpenAI n'est necessaire pour le Director local.

## Demarrage le plus simple
Sous Windows, double-clique sur `START_LOCAL_WORKER.bat`.

Au premier lancement, le script cree `self_hosted_worker/.env`. Tu dois uniquement y renseigner les deux URL externes de connexion Render :
- `DATABASE_URL`
- `REDIS_URL`

Ensuite, relance `START_LOCAL_WORKER.bat`. Tu n'as pas besoin de connaitre ton CPU, ta RAM ou ta carte graphique.

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

## Priorite automatique local / cloud
Quand le worker local tourne, il publie un heartbeat Redis contenant son profil, sa resolution et son mode IA. Le worker Render detecte ce heartbeat et se met en retrait.

Quand tu fermes le worker local ou eteins ton PC, le heartbeat expire apres quelques secondes et Render reprend automatiquement comme secours.

Le Studio affiche egalement l'etat courant : `PC local prioritaire` ou `Render en secours`.

## Stack
- FFmpeg : montage, analyse video et rendu ;
- V8 Moment Ranker : mouvement, audio, cuts et payoff ;
- V8 Director : simulations multi-strategies ;
- Critic : controle qualite + revision ;
- Ollama + Qwen2.5-VL 3B : vision locale facultative ;
- PostgreSQL / Redis Render : controle, metadonnees et file de jobs.

## Securite
Ne publie jamais `self_hosted_worker/.env`. Il contient des URL privees Postgres/Redis. Le worker initie uniquement des connexions sortantes ; aucun port entrant et aucune ouverture de routeur ne sont necessaires.
