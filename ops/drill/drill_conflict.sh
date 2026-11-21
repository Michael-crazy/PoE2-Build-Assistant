#!/bin/bash
# U05 drill 2: an upstream release v0.23.100 that conflicts with our PoB branch (on top of v0.23.99).
set -euo pipefail
D=${1:-$HOME/workspaces/u05-drill}
cd "$D"
export GIT_AUTHOR_NAME=Claude GIT_AUTHOR_EMAIL=noreply@anthropic.com GIT_COMMITTER_NAME=Claude GIT_COMMITTER_EMAIL=noreply@anthropic.com
parent=$(git -C up-pob.git rev-parse v0.23.99^{commit})
path=src/Classes/EditControl.lua   # our P07 paste patch changes this file
idx=$(mktemp)
blob=$(printf -- '-- drill: upstream rewrote this file\nreturn {}\n' | git -C up-pob.git hash-object -w --stdin)
GIT_INDEX_FILE=$idx git -C up-pob.git read-tree "$parent"
GIT_INDEX_FILE=$idx git -C up-pob.git update-index --cacheinfo "100644,$blob,$path"
tree=$(GIT_INDEX_FILE=$idx git -C up-pob.git write-tree); rm -f "$idx"
c=$(git -C up-pob.git commit-tree "$tree" -p "$parent" -m "drill: conflicting upstream change to $path")
git -C up-pob.git update-ref refs/heads/dev "$c"; git -C up-pob.git tag v0.23.100 "$c"
echo "conflict tag v0.23.100 = $c"
