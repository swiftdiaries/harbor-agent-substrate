#!/bin/sh
set -eu
mkdir -p /logs/verifier
if [ "$(cat /logs/artifacts/answer.txt)" = substrate-ok ]; then
    printf '1\n' > /logs/verifier/reward.txt
else
    printf '0\n' > /logs/verifier/reward.txt
fi
