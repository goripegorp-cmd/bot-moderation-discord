#!/bin/bash

# Vérifie si les packages sont déjà installés
pip freeze > /tmp/installed.txt 2>/dev/null

NEED_INSTALL=false

while IFS= read -r package; do
    # Ignore les lignes vides et commentaires
    [[ -z "$package" || "$package" == \#* ]] && continue
    
    # Extrait le nom du package (sans version)
    pkg_name=$(echo "$package" | cut -d'=' -f1 | cut -d'>' -f1 | cut -d'<' -f1)
    
    if ! grep -qi "^$pkg_name" /tmp/installed.txt; then
        NEED_INSTALL=true
        break
    fi
done < requirements.txt

if [ "$NEED_INSTALL" = true ]; then
    echo "📦 Installation des dépendances..."
    pip install -r requirements.txt --quiet
else
    echo "✅ Dépendances déjà installées"
fi

# Lancer le bot
python3 bot.py
