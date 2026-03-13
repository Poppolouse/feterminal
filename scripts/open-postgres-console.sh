#!/usr/bin/env bash

set -euo pipefail

container=""
database=""
user="postgres"
password=""
host="127.0.0.1"
port="5432"

while (($#)); do
  case "$1" in
    --container)
      container="$2"
      shift 2
      ;;
    --database)
      database="$2"
      shift 2
      ;;
    --user)
      user="$2"
      shift 2
      ;;
    --password)
      password="$2"
      shift 2
      ;;
    --host)
      host="$2"
      shift 2
      ;;
    --port)
      port="$2"
      shift 2
      ;;
    *)
      printf 'Unknown argument: %s\n' "$1" >&2
      exit 1
      ;;
  esac
done

if [[ -z "$database" ]]; then
  printf 'Missing required --database value\n' >&2
  exit 1
fi

runtime=""
if [[ -n "$container" ]]; then
  if command -v podman >/dev/null 2>&1; then
    runtime="podman"
  elif command -v docker >/dev/null 2>&1; then
    runtime="docker"
  fi
fi

if [[ -n "$runtime" ]]; then
  env_args=()
  if [[ -n "$password" ]]; then
    env_args=(-e "PGPASSWORD=$password")
  fi
  exec "$runtime" exec -it "${env_args[@]}" "$container" psql -U "$user" -d "$database"
fi

if command -v psql >/dev/null 2>&1; then
  if [[ -n "$password" ]]; then
    export PGPASSWORD="$password"
  fi
  exec psql -h "$host" -p "$port" -U "$user" -d "$database"
fi

printf 'Unable to open Postgres console. Install psql or docker/podman, or set explicit commands.\n' >&2
exit 1
