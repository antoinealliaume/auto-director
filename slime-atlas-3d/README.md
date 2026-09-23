# Slime Atlas V4

Dossier isolé pour héberger Slime Atlas sur Railway, indépendamment d'AppDeploy.

## Structure

- `public/` : site statique Slime Atlas
- `server.js` : serveur statique Node
- `package.json` : commande de démarrage
- `railway.json` : configuration Railway

Le reste du dépôt auto-director n'est pas modifié.

## Chorégraphies V4

`v4/vfx.js` contient 96 compositions explicites de volumes articulés : croissance,
déploiement, cisaillement, assemblage, chute, effondrement et reconstitution.
Le moteur ne produit plus de sprites ponctuels ni d'aura orbitale commune.
Des anneaux solides restent employés uniquement quand ils décrivent la créature
(donut, engrenage, horloge, planète, éclipse).

Les séquences Attente, Déplacement, Attaque, Spécial, Réaction, Interaction et
Apparition sont calculées à partir de la même horloge que le modèle. Les cinq
mutations modifient la construction des volumes et la réponse du corps : naturel,
écho, assemblage, instabilité, pliage spatial. Les 96 structures restent distinctes.

`npm run build` vérifie puis extrait l'archive originale des modèles, conservée au
même endpoint pour les reconstructions et retours arrière. Les fichiers versionnés
de `v4/` remplacent ensuite le viewer extrait. Les empreintes des fichiers publiés
sont recalculées. `version.json` identifie la V4 déployée.

`npm test` contrôle les 96 espèces × 5 mutations × 7 séquences à quatre instants,
les géométries indépendamment de leur couleur, la lecture arrière et les mouvements
réduits. Pour le test navigateur, copier `tests/browser-smoke.html` dans `public/`,
lancer `npm start`, puis ouvrir `/browser-smoke.html`. Ce test charge les 96 GLB,
contrôle 1 440 scènes et les erreurs WebGL. Il n'est pas publié par le build.

Le téléchargement GLB conserve les six animations originales intégrées. Les VFX
procéduraux et la séquence d'apparition V4 s'exécutent dans le site et ne sont pas
intégrés au fichier GLB. Le mode sans WebGL montre un modèle fixe avec une
projection 2D des volumes, explicitement identifiée dans l'interface.
