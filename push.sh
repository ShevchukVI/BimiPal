#!/bin/bash
git add .
git commit -m "wip: auto-update $(date +'%d-%m %H:%M')"
git push
EOF
chmod +x push.sh