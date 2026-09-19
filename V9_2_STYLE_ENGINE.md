# Auto Director V9.2 — Style & Editing Engine

V9.2 ajoute une vraie couche de direction visuelle au Quality Engine V9.1.

## Styles automatiques

Le Director peut désormais produire des variantes visuellement différentes avec les presets :

- `viral` — cuts dynamiques, punch text, flashs, couleurs saturées ;
- `cinematic` — fondus, mouvement doux, contraste film, texte minimal ;
- `kinetic` — texte animé, vitesse, mouvement et transitions rapides ;
- `clean` — montage lisible et sobre ;
- `retro` — teintes chaudes, grain léger, highlights colorés ;
- `glitch` — accents numériques, contraste fort, shake contrôlé ;
- `meme` — texte fort, zooms courts et rythme comique ;
- `dreamy` — ralentissements légers, fondus et rendu doux.

En mode `auto`, le style dépend de la stratégie Director, du mode choisi, de l'intensité et du numéro de variante. Plusieurs variantes d'un même job explorent donc naturellement plusieurs looks.

## Nouveau rendu FFmpeg

Chaque segment peut recevoir indépendamment :

- color grading ;
- accent color ;
- style de hook ;
- style de sous-titre ;
- drift / push / shake contrôlé ;
- speed edit borné ;
- flash d'impact ;
- transition fade, dissolve, wipe, slide ou circle.

Les transitions utilisent `xfade` + `acrossfade` quand disponibles. Si le build FFmpeg local ne fournit pas un filtre ou si une transition échoue, le renderer revient automatiquement au concat sécurisé au lieu de faire échouer le job.

## Sécurité ressources

Les effets sont déterministes et bornés. L'intensité `soft` réduit automatiquement vitesse, zooms et flashs. Les filtres lourds restent facultatifs et détectés avant utilisation.

## Worker PC

L'agent PC passe en `2.7`. Le Studio demandera une mise à jour aux installations 2.6 afin que le worker local récupère le Style Engine V9.2.
