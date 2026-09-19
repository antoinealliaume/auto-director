# Auto Director — Continuous Audit

- Généré : `2026-09-19T14:09:36+00:00`
- Commit audité : `202be9c6ff96611e5e52e57dba45f9ec56b1f28c`
- État : **CRITICAL**
- Critiques : **1** · Avertissements : **1** · Infos : **0** · Contrôles échoués : **1**

## Priorités proposées

### 🔴 Échec: Dependency vulnerability audit
**Catégorie :** checks

Name             Version ID                  Fix Versions
---------------- ------- ------------------- ------------
python-multipart 0.0.20  PYSEC-2026-1852     0.0.22
python-multipart 0.0.20  PYSEC-2026-3038     0.0.26
python-multipart 0.0.20  PYSEC-2026-3039     0.0.27
python-multipart 0.0.20  PYSEC-2026-3040     0.0.31
python-multipart 0.0.20  PYSEC-2026-3036     0.0.30
python-multipart 0.0.20  PYSEC-2026-3037     0.0.30
python-multipart 0.0.20  PYSEC-2026-1852     0.0.22
python-multipart 0.0.20  PYSEC-2026-3038     0.0.26
python-multipart 0.0.20  PYSEC-2026-3037     0.0.30
python-multipart 0.0.20  PYSEC-2026-3036     0.0.30
python-multipart 0.0.20  PYSEC-2026-3040     0.0.31
python-multipart 0.0.20  PYSEC-2026-3039     0.0.27
cryptography     46.0.7  PYSEC-2026-3554     49.0.0
cryptography     46.0.7  PYSEC-2026-3552     50.0.0
cryptography     46.0.7  PYSEC-2026-3553     49.0.0
cryptography     46.0.7  PYSEC-2026-3552     50.0.0
cryptography     46.0.7  PYSEC-2026-3553     49.0.0
cryptography     46.0.7  PYSEC-2026-3554     49.0.0
cryptography     46.0.7  GHSA-537c-gmf6-5ccf 48.0.1
starlette        0.47.3  PYSEC-2026-1942     0.49.1
starlette        0.47.3  PYSEC-2026-161      1.0.1
starlette        0.47.3  PYSEC-2026-161      1.0.1
starlette        0.47.3  PYSEC-2026-2281     1.1.0
starlette        0.47.3  PYSEC-2026-2280     1.1.0
starlette        0.47.3  PYSEC-2026-249      1.3.1
starlette        0.47.3  PYSEC-2026-248      1.3.0
starlette        0.47.3  PYSEC-2026-249      1.3.1
starlette        0.47.3  PYSEC-2026-248      1.3.0
starlette        0.47.3  PYSEC-2026-1942     0.49.1
starlette        0.47.3  PYSEC-2026-2281     1.1.0
starlette        0.47.3  PYSEC-2026-2280     1.1.0

Found 31 known vulnerabilities in 3 packages

**Action proposée :** Corriger avant toute fusion vers main.

### 🟠 Artefacts legacy présents
**Catégorie :** maintenance

app/main.py.new
app/main_v7.py
app/ACTIVATE_V7_NOW
app/README_V7_SWITCH.txt
app/STOP_PLACEHOLDER
app/activate_v7.txt

**Action proposée :** Vérifier qu'ils ne sont plus référencés puis les supprimer dans une PR dédiée si sûrs.

## Contrôles automatiques

- ✅ **Python compileall** (code `0`)
- ✅ **Core unit tests** (code `0`)
- ✅ **pip dependency consistency** (code `0`)
- ✅ **JS syntax: app.js** (code `0`)
- ✅ **JS syntax: publication.js** (code `0`)
- ✅ **JS syntax: secure-media.js** (code `0`)
- ✅ **JS syntax: worker-status.js** (code `0`)
- ✅ **PowerShell syntax: app/static/Install-AutoDirector.ps1** (code `0`)
- ✅ **PowerShell syntax: self_hosted_worker/START_LOCAL_WORKER_WINDOWS.ps1** (code `0`)
- ✅ **PowerShell syntax: self_hosted_worker/local_agent.ps1** (code `0`)
- ✅ **PowerShell syntax: self_hosted_worker/run_worker_logged.ps1** (code `0`)
- ✅ **Ruff fatal/static errors** (code `0`)
- ❌ **Dependency vulnerability audit** (code `1`)
- ✅ **Worker installer version alignment** (code `0`)

## Règles d'automatisation

- Ce rapport ne modifie jamais `main`.
- Les corrections automatiques doivent être faites sur une branche dédiée avec PR.
- Aucun merge automatique pour les changements de sécurité, OAuth TikTok, stockage, base de données, publication ou architecture worker.
- Une absence de finding ne prouve pas l'absence de bug : l'audit est un filet de sécurité, pas une preuve formelle.
