#!/bin/sh
echo "removing old generated files"
rm -r data/*/parsed
rm -r data/*/distilled
rm -r data/*/annotations
rm -r data/*/generated
rm -r data/*/toc
echo "resetting fulltextindex"
set -e  # fail immediately on error
./ferenda-build.py devel destroyindex
echo "resetting triplestore"
./ferenda-build.py devel clearstore
echo "updating git sources"
git pull -q
echo "building everything"
./ferenda-build.py all all --processes=7
echo "createing statusreport"
./ferenda-build.py devel statusreport
echo "deploying to remote"
cd ..
fab -H colo.tomtebo.org -f tools/fabfile.py deploy

