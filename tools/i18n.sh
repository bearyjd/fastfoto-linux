#!/bin/sh
# Translation catalogs of the desktop app (see docs/translating.md).
#
#   tools/i18n.sh update    find the messages in the QML and Python and merge them into the .ts files
#   tools/i18n.sh release   compile every .ts file to the .qm file the app loads (finished messages
#                           only) and pin the SHA-256 of each .qm in fastfoto_<code>.qm.sha256
#   tools/i18n.sh check     update a temporary copy of each .ts and fail if the committed one differs,
#                           or if the committed .qm is not what lrelease makes of the .ts
#
# Needs Qt's lupdate and lrelease (Fedora: qt6-linguist; they are lupdate-qt6 and lrelease-qt6).
# Line numbers are left out (-locations none), so that moving code does not change the files.
set -eu

root=$(cd "$(dirname "$0")/.." && pwd)
gui="$root/src/fastfoto_linux/gui"
catalogs="$gui/translations"
languages="de"

find_tool() {
    for name in "$1-qt6" "$1"; do
        if command -v "$name" >/dev/null 2>&1; then
            command -v "$name"
            return 0
        fi
    done
    echo "i18n.sh: $1 not found (Fedora: sudo dnf install qt6-linguist)" >&2
    return 1
}

extract() { # extract <language> <ts file to create or update>
    lupdate=$(find_tool lupdate)
    "$lupdate" "$gui/qml" "$gui/report.py" "$gui/form.py" \
        -ts "$2" -target-language "$1" -locations none -no-obsolete -silent
}

mode=${1:-}
case "$mode" in
update)
    for language in $languages; do
        extract "$language" "$catalogs/fastfoto_$language.ts"
    done
    ;;
release)
    lrelease=$(find_tool lrelease)
    for language in $languages; do
        "$lrelease" -nounfinished "$catalogs/fastfoto_$language.ts" \
            -qm "$catalogs/fastfoto_$language.qm" -silent
        (cd "$catalogs" && sha256sum "fastfoto_$language.qm" >"fastfoto_$language.qm.sha256")
    done
    ;;
check)
    work=$(mktemp -d)
    trap 'rm -rf "$work"' EXIT
    status=0
    for language in $languages; do
        cp "$catalogs/fastfoto_$language.ts" "$work/fastfoto_$language.ts"
        extract "$language" "$work/fastfoto_$language.ts"
        if ! diff -u "$catalogs/fastfoto_$language.ts" "$work/fastfoto_$language.ts"; then
            echo "i18n.sh: fastfoto_$language.ts is out of date; run tools/i18n.sh update" >&2
            status=1
        fi
        lrelease=$(find_tool lrelease)
        "$lrelease" -nounfinished "$catalogs/fastfoto_$language.ts" \
            -qm "$work/fastfoto_$language.qm" -silent
        if ! cmp -s "$work/fastfoto_$language.qm" "$catalogs/fastfoto_$language.qm"; then
            echo "i18n.sh: fastfoto_$language.qm is not what lrelease makes of the .ts; run tools/i18n.sh release" >&2
            status=1
        fi
    done
    exit $status
    ;;
*)
    echo "usage: tools/i18n.sh update|release|check" >&2
    exit 2
    ;;
esac
