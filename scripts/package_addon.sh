set -ex

cwd="$(basename $(pwd))"

if [ "$cwd" != "anki-leech-actions" ]; then
	echo "Please run this script from project root"
	exit 1
fi

cd anki_leech_actions
zip -r ../leech_actions.ankiaddon config.json *.py
cd -
