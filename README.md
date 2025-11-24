# Cato Provisioning v3.2 - Documentation

## Installation

### Prérequis

```bash
pip install requests rich
```

### Structure des Fichiers

```
projet/
├── cato_provisioning.py
├── config.ini
├── data
  ├── sites.csv
  ├── networks.csv
  ├── hosts.csv
└── provisioning_sequence.json
```

---

## Configuration

### Méthode 1 : Variables d'Environnement 

```bash
export CATO_API_API_KEY="votre-api-key-secrete"
export CATO_API_ACCOUNT_ID="5242"
export CATO_API_API_URL="https://api.catonetworks.com/api/v1/graphql2"

python cato_provisioning.py
```

### Méthode 2 : Fichier config.ini

```ini
[api]
api_key = votre-api-key
account_id = 5242
api_url = https://api.catonetworks.com/api/v1/graphql2

[files]
sequence_file = provisioning_sequence.json
output_dir = ./logs

[execution]
enable_http_logging = true
request_timeout = 30

[display]
log_level = DEBUG
```

---

## 🔐 Variables d'Environnement

### Format

`CATO_{SECTION}_{KEY}`

- **SECTION** : Section du config.ini en majuscules
- **KEY** : Clé en majuscules

### Liste Complète

| Variable | Section | Clé | Type | Défaut |
|----------|---------|-----|------|--------|
| `CATO_API_API_KEY` | api | api_key | string | - |
| `CATO_API_ACCOUNT_ID` | api | account_id | string | - |
| `CATO_API_API_URL` | api | api_url | string | https://... |
| `CATO_FILES_SEQUENCE_FILE` | files | sequence_file | string | provisioning_sequence.json |
| `CATO_FILES_OUTPUT_DIR` | files | output_dir | string | ./logs |
| `CATO_EXECUTION_ENABLE_HTTP_LOGGING` | execution | enable_http_logging | boolean | true |
| `CATO_EXECUTION_REQUEST_TIMEOUT` | execution | request_timeout | float | 30 |
| `CATO_DISPLAY_LOG_LEVEL` | display | log_level | string | INFO |

---

## Utilisation

### Commande de Base

```bash
python cato_provisioning.py
```

### Mode Debug

```bash
export CATO_DISPLAY_LOG_LEVEL=DEBUG
python cato_provisioning.py
```

---

## Exemple Fichiers de Données

### sites.csv

```csv
site_name,site_type,connection_type,wan1_bw_upstream,wan1_bw_downstream,wan1_precedence,wan2_bw_upstream,wan2_bw_downstream,wan2_precedence,description,native_range,country,city,timezone
Paris-HQ,HEADQUARTERS,SOCKET_X1500,100,100,ACTIVE,25,25,ACTIVE,Siege social Paris,192.168.10.0/24,FR,Paris,Europe/Paris
Lyon-Branch,BRANCH,SOCKET_X1500,50,50,ACTIVE,50,50,ACTIVE,Agence Lyon,192.168.20.0/24,FR,Lyon,Europe/Paris
```

### networks.csv

```csv
site_name,lan_name,network_type,lan_subnet,lan_gateway,lan_vlan
Paris-HQ,VLAN-Prod,VLAN,192.168.1.0/24,192.168.1.1,1
Paris-HQ,Static-DMZ,STATIC,10.0.1.0/24,10.0.1.1,
```

---

## Séquence JSON

### Structure de Base

```json
{
  "description": "Provisionnement sites et réseaux",
  "version": "3.2",
  "master_data_source": "sites.csv",
  "master_iterate_over": "sites",
  "sequence": [
    {
      "step_name": "Créer site",
      "operation": "add_site",
      "enabled": true,
      "wait_seconds": 2,
      "store_result_as": "site",
      "graphql_query": "mutation ...",
      "params": {
        "name": "@site_name",
        "siteType": "@site_type"
      }
    }
  ]
}
```

**Comportement** :
- Pour chaque ligne de `sites.csv`
- Exécuter toutes les étapes de la séquence
- Contexte isolé par site

### Étapes avec Itération

```json
{
  "step_name": "Créer réseaux",
  "iterate_over": "networks",
  "data_source_file": "networks.csv",
  "join_on": {
    "local_key": "site_name",
    "context_key": "site_name"
  },
  "params": {
    "name": "@lan_name"
  }
}
```

**Comportement** :
- Exécuter l'étape 
- Pour chaque ligne de `networks.csv`
- Avec un 'site_name' correspondant aux 'site_name' du fichier master


---

## Résolution de Variables

### Variables des fichiers CSV (@)

```json
{
  "name": "@site_name",
  "city": "@city"
}
```

Résout depuis la ligne CSV courante.

### Variables Contexte ($)

```json
{
  "siteId": "${site.data.site.addSocketSite.siteId}"
}
```

Résout depuis le contexte global (résultats précédents).

### Objets Imbriqués

```json
{
  "parent": {
    "id": "${site.data.site.addSocketSite.siteId}",
    "type": "site"
  }
}
```

### Listes avec Index

```json
{
  "interfaceId": "${lan_interface.data.entityLookup.items.0.entity.id}"
}
```

---

## 📊 Logs et Résultats

### Logs Générés

```
logs/
├── execution_20251028_143000.log      # Logs détaillés
├── http_requests_20251028_143000.json # Requêtes HTTP
└── results_20251028_143000.json       # Résultats
```