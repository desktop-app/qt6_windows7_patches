#!/bin/bash
# Port Windows 7 patch series from one Qt tag to another, one commit per patch:
# every patch is re-merged against upstream changes and regenerated in place.
# Details in README.md.
#
#   tools/port_to_version.sh v6.11.2 v6.12.0

set -u

FROM=${1:?usage: port_to_version.sh <from-tag> <to-tag> [workdir]}
TO=${2:?usage: port_to_version.sh <from-tag> <to-tag> [workdir]}
REPO=$(cd "$(dirname "$0")/.." && pwd)
WORK=${3:-$REPO/.port}

mkdir -p "$WORK"
WORK=$(cd "$WORK" && pwd)

clone_pristine() {
    local tag=$1
    if [ ! -d "$WORK/qtbase-$tag" ]; then
        echo "cloning pristine qtbase $tag ..."
        git -c core.autocrlf=false clone --depth 1 --branch "$tag" --single-branch \
            https://github.com/qt/qtbase.git "$WORK/qtbase-$tag" || exit 1
    fi
}
clone_pristine "$FROM"
clone_pristine "$TO"

OLD=$WORK/qtbase-$FROM
NEW=$WORK/qtbase-$TO
TMP=$WORK/tmp
OUT=$WORK/out

for d in "$OLD" "$NEW"; do
    git -C "$d" checkout -q -- . || exit 1
    git -C "$d" clean -qfdx || exit 1
done
rm -rf "$TMP" "$OUT"; mkdir -p "$TMP" "$OUT"

conflicts=0
carried=0
printf "%-62s %-12s %s\n" "FILE" "STATUS" "PATCH"

for patch in "$REPO"/[0-9][0-9][0-9][0-9]-*.patch; do
    name=$(basename "$patch")
    subject=$(sed -n 's/^Subject: \[PATCH[^]]*\] //p' "$patch" | head -1)
    if ! git -C "$OLD" apply --ignore-whitespace "$patch"; then
        echo "$name does not apply to $FROM - wrong from-tag?" >&2
        exit 1
    fi
    # qtbase paths never contain spaces, so a plain word list is safe here.
    files=$(git -C "$OLD" apply --numstat "$patch" | cut -f3)
    for f in $files; do
        mkdir -p "$(dirname "$NEW/$f")"
        if ! git -C "$OLD" cat-file -e "$FROM:$f" 2>/dev/null; then
            cp "$OLD/$f" "$NEW/$f"; st="ADDED"
        elif ! git -C "$NEW" cat-file -e "$TO:$f" 2>/dev/null; then
            cp "$OLD/$f" "$NEW/$f"; st="GONE-IN-$TO"; carried=$((carried + 1))
        else
            # Ours is cumulative, so theirs always comes from pristine <to-tag>.
            git -C "$OLD" show "$FROM:$f" > "$TMP/base"
            git -C "$NEW" show "$TO:$f" > "$TMP/theirs"
            if git merge-file -p --diff3 "$OLD/$f" "$TMP/base" "$TMP/theirs" > "$TMP/merged" 2>/dev/null; then
                st="CLEAN"
            else
                st="CONFLICT"; conflicts=$((conflicts + 1))
            fi
            cp "$TMP/merged" "$NEW/$f"
        fi
        printf "%-62s %-12s %s\n" "$f" "$st" "${name%%-*}"
    done
    git -C "$NEW" add -- $files || exit 1
    # No identity is forced: whoever regenerates the series signs it, and that
    # name lands in the From: header of every patch file.
    git -C "$NEW" commit -q -m "$subject" || exit 1
done

git -C "$NEW" format-patch -o "$OUT" "$TO..HEAD" --no-signature -q || exit 1
rm -rf "$TMP"

echo
echo "regenerated series in $OUT"
echo "$conflicts file(s) carry conflict markers, $carried file(s) no longer exist in $TO"
echo
echo "before replacing patches in this repository, check that:"
echo "  1. every patch applies to pristine $TO checkout"
echo "  2. desktop-app set still applies on top:"
echo "       git apply <patches>/qtbase_<version>/*.patch"
