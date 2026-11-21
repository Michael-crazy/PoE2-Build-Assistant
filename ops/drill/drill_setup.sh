#!/bin/bash
# U05 drill: local fake upstream/home/fork/private/public repositories (nothing touches GitHub).
set -euo pipefail
D=${1:-$HOME/workspaces/u05-drill}
PRIV_REF=${2:-task/U05}
rm -rf "$D"; mkdir -p "$D"; cd "$D"
export GIT_AUTHOR_NAME=Claude GIT_AUTHOR_EMAIL=noreply@anthropic.com GIT_COMMITTER_NAME=Claude GIT_COMMITTER_EMAIL=noreply@anthropic.com
POB_HOME=$HOME/git/PathOfBuilding-PoE2.git; EE2_HOME=$HOME/git/Exiled-Exchange-2.git
POB_BASE=601768bd105869618c3d6581b883e5d7aeec91b2; EE2_BASE=cca30662bf31eaf38bd711e2ec1a6b899a06c40e

# commit_file REPO PARENT PATH CONTENT -> new commit on PARENT that sets PATH to CONTENT
commit_file() {
  local repo=$1 parent=$2 path=$3 content=$4 idx; idx=$(mktemp)
  local blob; blob=$(printf '%s\n' "$content" | git -C "$repo" hash-object -w --stdin)
  GIT_INDEX_FILE=$idx git -C "$repo" read-tree "$parent"
  GIT_INDEX_FILE=$idx git -C "$repo" update-index --add --cacheinfo "100644,$blob,$path"
  local tree; tree=$(GIT_INDEX_FILE=$idx git -C "$repo" write-tree); rm -f "$idx"
  git -C "$repo" commit-tree "$tree" -p "$parent" -m "drill: upstream change to $path"
}

git clone -q --bare --shared "$POB_HOME" up-pob.git
git -C up-pob.git update-ref refs/heads/dev $POB_BASE
c=$(commit_file up-pob.git $POB_BASE drill-upstream.txt "fake upstream release v0.23.99")
git -C up-pob.git update-ref refs/heads/dev "$c"; git -C up-pob.git tag v0.23.99 "$c"
git -C up-pob.git tag v2.99.0 "$c"   # PoE1-style tag: must be ignored (same commit, so a wrong pick would still be visible in logs)

git clone -q --bare --shared "$EE2_HOME" up-ee2.git
git -C up-ee2.git update-ref refs/heads/master $EE2_BASE
c=$(commit_file up-ee2.git $EE2_BASE drill-upstream.txt "fake upstream release v0.16.99")
git -C up-ee2.git update-ref refs/heads/master "$c"; git -C up-ee2.git tag v0.16.99 "$c"

for k in pob ee2; do
  src=$POB_HOME; [ $k = ee2 ] && src=$EE2_HOME
  git clone -q --bare --shared "$src" home-$k.git
  git clone -q --bare --shared "$src" fork-$k.git
done
git -C home-pob.git remote add upstream "$D/up-pob.git"

git clone -q --bare "$HOME/git/PoE2-Build-Assistant.git" priv.git
git -C priv.git update-ref refs/heads/main "$(git -C "$HOME/git/PoE2-Build-Assistant.git" rev-parse "$PRIV_REF")"
git clone -q --bare "$HOME/workspaces/public-export" pub.git

cat > drill.json <<JSON
{
  "state": "$D/state",
  "project_home": "$D/priv.git",
  "public_remote": "$D/pub.git",
  "public_terms": "$HOME/workspaces/PoE2-Build-Assistant/ops/public-check-terms.txt",
  "forks": {"pob": "$D/fork-pob.git", "ee2": "$D/fork-ee2.git"},
  "overrides": {"pob": {"home": "$D/home-pob.git", "upstream": "$D/up-pob.git"},
                "ee2": {"home": "$D/home-ee2.git", "upstream": "$D/up-ee2.git"}},
  "notify": "dry-run", "hold": false, "fetch": false, "trade_fetch": false
}
JSON
echo "drill ready: $D"
