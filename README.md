# cage-cloud

Облачный [Cage](https://github.com/masesmirnov/Claude-Cage) на **main**: интерфейс Claude Code в браузере на [claude.maserov.com](https://claude.maserov.com) и терминал на `/console`, оба за единым входом maserov.com.

`integration/deploy.py` создаёт пользователя `cage` с отдельным диапазоном subuid/subgid, разрешает rootlesskit user namespaces через профиль AppArmor, скачивает закреплённые `cloud-linux-amd64.tar` и `lifecycle.sh` из релиза форка, сверяет SHA-256 и ставит Cage штатным `lifecycle.sh install`. Cage слушает `127.0.0.1:17777` от имени `cage`, свой rootless Docker и гостевой образ лежат в `/home/cage/.claude-cage/cloud-host`. Повторный deploy только проверяет, что служба запущена. Если закреплён новый релиз, а входы образа гостя, юниты служб и установочные скрипты гостя в нём те же, deploy заменяет бинарники `cage` и `mihomo` и перезапускает службу; иначе останавливается с ошибкой.

`integration/access.py` кладёт proof единого входа в `/etc/cage-cloud/token` (группа `cage`, как у других служб не от root) и добавляет службе `CAGE_PUBLIC_ORIGIN` и `CAGE_PROXY_TOKEN_FILE`: Cage принимает запросы на публичном домене только с этим proof, его подставляет Caddy за OAuth2 Proxy.

После первой установки аккаунт Cage и узел прокси настраиваются в самом интерфейсе. Пароль аккаунта нужен после каждого перезапуска службы.
