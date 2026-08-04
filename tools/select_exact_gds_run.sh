#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 EXPECTED_HEAD OUTPUT_JSON" >&2
  exit 2
fi

expected_head=$1
output_json=$2
timeout_seconds=${GDS_WAIT_TIMEOUT_SECONDS:-1800}
poll_interval=${GDS_POLL_INTERVAL_SECONDS:-15}

if [[ ! $expected_head =~ ^[0-9a-f]{40}$ ]] ||
   [[ ! $timeout_seconds =~ ^[0-9]+$ ]] ||
   [[ ! $poll_interval =~ ^[0-9]+$ ]]; then
  echo "invalid exact-head GDS selector configuration" >&2
  exit 2
fi

if [[ -n ${GDS_MAX_POLLS:-} ]]; then
  max_polls=$GDS_MAX_POLLS
elif ((poll_interval > 0)); then
  max_polls=$((timeout_seconds / poll_interval + 1))
else
  echo "a zero poll interval requires an explicit GDS_MAX_POLLS test bound" >&2
  exit 2
fi
if [[ ! $max_polls =~ ^[1-9][0-9]*$ ]]; then
  echo "invalid exact-head GDS poll bound" >&2
  exit 2
fi

for ((poll = 1; poll <= max_polls; poll++)); do
  runs=$(gh run list --workflow gds.yaml --branch main --commit "$expected_head" \
    --limit 20 --json databaseId,headSha,url,status,conclusion,createdAt)
  run=$(jq -c --arg head "$expected_head" \
    '[.[] | select(.headSha == $head)] | sort_by(.createdAt, .databaseId) | last // empty' \
    <<<"$runs")

  if [[ -n $run ]]; then
    run_id=$(jq -r '.databaseId' <<<"$run")
    status=$(jq -r '.status' <<<"$run")
    conclusion=$(jq -r '.conclusion // ""' <<<"$run")
    url=$(jq -r '.url' <<<"$run")

    if [[ $status == completed ]]; then
      if [[ $conclusion != success ]]; then
        echo "exact-head GDS run $run_id completed with conclusion '$conclusion': $url" >&2
        exit 1
      fi
      printf '%s\n' "$run" >"$output_json"
      echo "exact-head GDS run $run_id completed successfully: $url" >&2
      exit 0
    fi
    echo "waiting for exact-head GDS run $run_id (status '$status', poll $poll/$max_polls): $url" >&2
  else
    echo "waiting for a GDS run for exact head $expected_head (poll $poll/$max_polls)" >&2
  fi

  if ((poll < max_polls)); then
    sleep "$poll_interval"
  fi
done

echo "timed out after $max_polls polls waiting for successful GDS evidence for exact head $expected_head" >&2
exit 1
