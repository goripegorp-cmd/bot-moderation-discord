#!/usr/bin/env bash
# Vérification du socle après chaque lot (HANDOFF.md §6).
# Usage : bash outils/verif_socle.sh
# Sortie non nulle si une fonction critique a disparu.
set -u
cd "$(dirname "$0")/.."

FAIL=0

echo "── Fonctions critiques (§6) ────────────────────────────────"
for f in on_member_join on_message on_ready is_immune sanction _record_infraction \
         create_ticket check_badwords _ocr_scam_check task_supervisor \
         check_expired_restrictions; do
  c=$(grep -c "def $f" bot.py)
  if [ "$c" -gt 0 ]; then
    printf '  OK        %-28s (%s)\n' "$f" "$c"
  else
    printf '  MANQUANT  %-28s (0)\n' "$f"
    FAIL=1
  fi
done

echo
echo "── Points d'entrée NEVER_DELETE (§5 piège 1) ───────────────"
for f in help_cmd notify_cmd hub_cmd; do
  c=$(grep -c "def $f" bot.py)
  if [ "$c" -gt 0 ]; then
    printf '  OK        %-28s (%s)\n' "$f" "$c"
  else
    printf '  MANQUANT  %-28s (0)\n' "$f"
    FAIL=1
  fi
done

echo
echo "── Compilation ─────────────────────────────────────────────"
if PYTHONIOENCODING=utf-8 python3 -c "import ast,sys; ast.parse(open('bot.py',encoding='utf-8').read())" 2>/dev/null; then
  echo "  OK        bot.py se parse (ast.parse)"
else
  echo "  ÉCHEC     bot.py NE SE PARSE PAS"
  FAIL=1
fi

echo
echo "── Taille ──────────────────────────────────────────────────"
printf '  bot.py    %s lignes\n' "$(wc -l < bot.py)"
printf '  modules   %s fichiers .py à la racine\n' "$(ls *.py | wc -l)"

echo
if [ "$FAIL" -eq 0 ]; then
  echo "RÉSULTAT : socle intact."
else
  echo "RÉSULTAT : ✖ RÉGRESSION — ne pas commiter."
fi
exit "$FAIL"
