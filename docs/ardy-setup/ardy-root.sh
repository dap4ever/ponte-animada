#!/usr/bin/env bash
# Compilador de C++ e CMake no Ubuntu: o ARDY compila uma extensao propria ao instalar
# (o README dele pede "sudo apt install cmake build-essential"). Roda como root.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq build-essential cmake
echo "--- instalado"
g++ --version | head -1
make --version | head -1
cmake --version | head -1
