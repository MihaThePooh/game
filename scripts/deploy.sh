#!/usr/bin/env bash
# Выкладка игры на https://game.michaelperov.com/ (spb-node, хаб).
# Собирает dist/, на узле делает бэкап того, что сейчас на сайте, потом
# синхронизирует. Сервис сохранений живёт в репозитории хаба (services/game),
# настройка nginx там же (deploy/nginx/game.conf).
# Тесты перед выкладкой: ~/tools/uitest/game.js и gamemenu.js.
set -euo pipefail
cd "$(dirname "$0")/.."
NODE=spb-node
TARGET=/srv/game
BACKUPS='~/backups/game'

python3 scripts/stage.py

# Бэкап живой версии на узле; держим последние 5.
ssh "$NODE" "mkdir -p $BACKUPS && if [ -n \"\$(ls -A $TARGET 2>/dev/null)\" ]; then tar czf $BACKUPS/game-\$(date +%Y%m%d-%H%M%S).tar.gz -C $TARGET . && ls -1t $BACKUPS/game-*.tar.gz | tail -n +6 | xargs -r rm --; fi"

# --delete: убранное из игры пропадает и с сайта.
rsync -a --delete dist/ "$NODE:$TARGET/"
echo "live: https://game.michaelperov.com/"
