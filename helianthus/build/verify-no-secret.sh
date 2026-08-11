#!/bin/sh
set -eu

if [ "$#" -lt 2 ]; then
  echo "usage: verify-no-secret NEEDLE PATH..." >&2
  exit 2
fi

needle=$1
shift

if [ -z "$needle" ]; then
  exit 0
fi

set +e
grep -R -F -l -- "$needle" "$@" >/dev/null 2>&1
status=$?
set -e

case "$status" in
  0)
    echo "secret material persisted in builder filesystem" >&2
    exit 1
    ;;
  1)
    exit 0
    ;;
  *)
    echo "secret persistence scan failed with status $status" >&2
    exit "$status"
    ;;
esac
