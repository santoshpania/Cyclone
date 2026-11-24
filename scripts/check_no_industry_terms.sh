#!/usr/bin/env bash
# CLAUDE.md rule 1: no industry concepts in application code. Industry examples belong in
# tests/fixtures and docs; reference vocabularies belong in backend/app/catalogs/.
set -euo pipefail
cd "$(dirname "$0")/.."
TERMS='dental|dentist|pharmac(y|ies)|clinic|hospital|hotel|restaurant|cafe|bakery|salon|gym|warehous|manufactur|cybersecurity|grocer|supermarket|retail(er)?s?|garage|workshop|school|plumb|construction|real estate|automotive'
if grep -rniwE "$TERMS" backend/app web/src --exclude-dir=catalogs --exclude-dir=node_modules -l; then
  echo "✗ industry-specific terms found in application code (see files above)" >&2
  exit 1
fi
echo "✓ no industry-specific terms in application code"
