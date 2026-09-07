#!/bin/sh
set -eu

BASE_URL=${BASE_URL:-http://127.0.0.1:8000}

curl --fail --silent --show-error "$BASE_URL/health"
curl --fail --silent --show-error "$BASE_URL/ready"
curl --fail --silent --show-error \
  --header "Content-Type: application/json" \
  --data '{"kind":"lead","customer_name":"Smoke Test","phone":"+70000000000","source":"smoke"}' \
  "$BASE_URL/api/requests"
printf '\n%s\n' "PostgreSQL smoke test passed"
