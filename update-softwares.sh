#!/bin/bash
set -eu

# root check
if [ "$(id -u)" -ne 0 ]; then
  echo "Please run as root"
  exit 1
fi

# Required: git, python3
function check_command() {
  if ! type "$1" >/dev/null 2>&1; then
    read -p "Do you want to install $1? [y/n]: " yn
    if [ "$yn" = "y" ]; then
      if type apt >/dev/null 2>&1; then
        apt update
        apt install -y "$1"
      elif type yum >/dev/null 2>&1; then
        yum install -y "$1"
      else
        echo "Not found package manager"
        exit 1
      fi
    else
      echo "Please install $1"
      exit 1
    fi
  fi
}

if [ -z "${ISSUE_NUMBER:-}" ]; then
  echo "ISSUE_NUMBER is not defined. Exiting script."
  exit 1
fi

check_command git
check_command python3

install -d -m 755 /opt/update-softwares
cd /opt/update-softwares || exit 1

# clone repository
if [ ! -d /opt/update-softwares/.git ]; then
  git clone https://github.com/book000/update-softwares.git .
else
  git pull
fi

install -d -m 700 /opt/update-softwares/logs

# On Debian/Ubuntu, ensurepip is only included in python3-venv
if ! python3 -c "import ensurepip" >/dev/null 2>&1; then
  if type apt >/dev/null 2>&1; then
    apt update
    apt install -y python3-venv
  else
    echo "ensurepip is unavailable for python3; install the package that provides venv"
    exit 1
  fi
fi

# create venv and install requirements
# A venv can have venv/bin/pip without a working pip module, so check that pip actually runs
if ! venv/bin/python3 -m pip --version >/dev/null 2>&1; then
  python3 -m venv --clear venv
fi

venv/bin/pip install -r requirements.txt

export UPDATE_SOFTWARES_LOG_DIR=/opt/update-softwares/logs
venv/bin/python3  -m src "$ISSUE_NUMBER"
