# Slime Atlas V4.1

Dossier isolé pour héberger Slime Atlas sur Railway, indépendamment d'AppDeploy.

## Structure

- `public/` : site statique Slime Atlas
- `server.js` : serveur statique Node
- `package.json` : commande de démarrage
- `railway.json` : configuration Railway

Le reste du dépôt auto-director n'est pas modifié.

## Six métamorphoses intégrées — V4.1

Obsidien, Géodelle, Phénicendre, Aurorine, Séraphine et Astraroi disposent chacun
 de cinq directions artistiques dans `v4/designs.js` : palettes dédiées,
 matières propres à l’espèce, motifs attachés aux surfaces et évolution des ailes,
 cristaux et diadèmes existants. Le rendu ne génère aucun objet autour du modèle.
 Les 90 autres espèces conservent leur rendu précédent.

Les motifs utilisent les coordonnées de repos pour suivre la peau animée. La
 lumière des yeux et la bouche restent séparées des matières décoratives. Les
 mouvements des matières suivent la timeline et respectent les mouvements réduits.
 Le filtre « Nouveaux designs · 6 » permet de retrouver les six espèces.

`tests/design-smoke.html`, copié temporairement dans `public/`, vérifie les 30
 apparences, les 96 modèles, 300 scènes, les erreurs WebGL et l’absence de volumes
 supplémentaires. L’export GLB et les aperçus sans WebGL restent les originaux,
 explicitement indiqués dans l’interface ; les matières procédurales et les
 déformations de silhouette sont propres au rendu de l’atlas.

## Retrait des objets — 24 septembre 2026

Les volumes ajoutés par la V4 ont été retirés du viewer à la demande de l’utilisateur. Le rendu 3D et le mode compatible ne dessinent plus ces objets. Les modèles, leurs apparences et leurs animations restent disponibles. Le moteur de volumes ci-dessous est conservé dans les sources pour historique, mais le viewer ne l’appelle plus.

## Moteur V4 conservé pour historique

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
