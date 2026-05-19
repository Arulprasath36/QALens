#!/usr/bin/env bash
set -e

pip install --upgrade pip
pip install .

curl -L https://github.com/Arulprasath36/QALens/releases/download/v0.1.2/shopnow-demo.zip -o shopnow-demo.zip
unzip -o shopnow-demo.zip
