#!/usr/bin/env bash
# Create or refresh the local CI virtual environment.
#
#   ci_bootstrap.sh <venv dir> <requirements file>
#
# The environment is reused only when its stamp matches the SHA-256 of the
# requirements file. Otherwise (changed requirements or missing stamp) it is
# recreated from scratch with `venv --clear`, so a removed dependency never
# lingers. The old stamp is removed before installing and the new stamp is
# written only after a successful install, so a failed install is retried on
# the next run.
set -euo pipefail

venv="${1:?venv dir}"
requirements="${2:?requirements file}"

want="$(python3 -c 'import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "${requirements}")"
have="$(cat "${venv}/.requirements-sha256" 2>/dev/null || true)"

if [ -x "${venv}/bin/python3" ] && [ "${have}" = "${want}" ]; then
  exit 0
fi

rm -f "${venv}/.requirements-sha256"
python3 -m venv --clear "${venv}"
"${venv}/bin/python3" -m pip install --quiet --disable-pip-version-check -r "${requirements}"
printf '%s' "${want}" > "${venv}/.requirements-sha256"
