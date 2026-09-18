# Auto Director - Worker local adaptatif sans credits IA

Ce mode garde le Studio web sur Render mais deplace le calcul lourd sur ton PC. Aucun credit OpenAI n'est necessaire pour le Director local.

## Ce que fait le mode adaptatif
Au lancement, `detect_profile.py` detecte automatiquement la RAM, le nombre de threads CPU et, si disponible, une carte NVIDIA + sa VRAM.

Le worker choisit ensuite un profil prudent :
- `minimal` : machine tres limitee, V8 heuristique uniquement, peu de samples, aucune auto-revision lourde.
- `light` : V8 complet en 720x1280, peu de threads, IA visuelle locale desactivee.
- `balanced-local-ai` : V8 + petit VLM `qwen2.5vl:3b`, contexte/images limites, une seule requete IA a la fois.

Le bot ne selectionne jamais automatiquement un modele plus gros que 3B. Le 1080p n'est pas active automatiquement. Il reste en 720x1280 pour eviter de saturer le PC.

## Protections ressources
- un seul job a la fois ;
- FFmpeg limite a quelques threads ;
- priorite Windows `BelowNormal` ;
- Ollama limite a 1 requete parallele et 1 modele charge ;
- contexte VLM reduit ;
- maximum 4 images par appel VLM ;
- verification de la RAM libre avant chaque appel VLM ;
- si la memoire libre devient trop faible, l'IA visuelle est sautee et le Director V8 continue ;
- si Ollama n'est pas installe ou plante, le worker continue en mode V8 leger.

## Priorite automatique local / cloud
Quand le worker local est lance, il publie un heartbeat dans Redis. Le worker Render voit ce heartbeat et se met automatiquement en retrait afin de ne pas voler les jobs.

Quand tu fermes le worker local ou eteins le PC, le heartbeat expire apres quelques secondes et Render reprend automatiquement le traitement comme secours.

## Demarrage Windows
1. Installe Python 3.12. Ollama est optionnel : si ton PC est trop limite ou si Ollama n'est pas installe, le bot fonctionne quand meme en V8 leger.
2. Dans Render, ouvre `auto-director-postgres` et `auto-director-queue`, copie leurs URL de connexion externes.
3. Lance `START_LOCAL_WORKER_WINDOWS.ps1` une premiere fois : il cree `.env`.
4. Dans `.env`, remplace uniquement `DATABASE_URL` et `REDIS_URL`.
5. Relance `START_LOCAL_WORKER_WINDOWS.ps1`.
6. Laisse la fenetre ouverte ou minimisee. Le worker local devient prioritaire automatiquement.

## Stack
- FFmpeg : montage et analyse video ;
- V8 Moment Ranker : mouvement, audio, cuts, payoff ;
- V8 Director : simulations multi-strategies ;
- Ollama + Qwen2.5-VL 3B : vision locale facultative ;
- PostgreSQL/Redis Render : controle, metadonnees et file de jobs.

## Securite
Ne publie jamais `.env`. Il contient les URL privees Postgres/Redis. Le worker initie uniquement des connexions sortantes : aucun port entrant ni ouverture de routeur n'est necessaire.
