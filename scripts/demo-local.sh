#!/usr/bin/env bash
# Demarre une instance de demonstration de Moulaga a l'interieur du depot, pour la
# validation visuelle d'une fonctionnalite terminee.
#
# Toutes les donnees restent synthetiques et confinees dans .data/ (ignore par Git).
# Le repertoire de production /data et le port Docker 8000 ne sont jamais utilises.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT/backend"
FRONTEND_DIR="$ROOT/frontend"
VENV_DIR="$BACKEND_DIR/.venv"
DATA_DIR="$ROOT/.data/demo"
RUNTIME_DIR="$ROOT/.data/demo-runtime"
PID_FILE="$RUNTIME_DIR/uvicorn.pid"
PORT_FILE="$RUNTIME_DIR/port"
LOG_FILE="$RUNTIME_DIR/uvicorn.log"

HOST="127.0.0.1"
PORT="${MOULAGA_DEMO_PORT:-8010}"
PORT_EXPLICIT=0
[ -n "${MOULAGA_DEMO_PORT:-}" ] && PORT_EXPLICIT=1
COMMAND="start"
DO_BUILD=1
DO_SEED=1
DO_OPEN=0

usage() {
  cat <<'EOF'
Usage: scripts/demo-local.sh [start|stop|restart|status|logs] [options]

Commandes :
  start      installe les dependances manquantes, construit le frontend, seme la
             base de demonstration puis sert l'application (defaut)
  stop       arrete l'instance de demonstration locale
  restart    equivaut a stop puis start
  status     indique si l'instance repond
  logs       affiche le journal de l'instance

Options :
  --port N       port d'ecoute (defaut 8010, ou MOULAGA_DEMO_PORT)
  --skip-build   reutilise le build frontend existant
  --keep-data    ne rejoue pas la seed, conserve la base de demonstration
  --open         ouvre l'URL dans le navigateur par defaut
  -h, --help     affiche cette aide
EOF
}

log() { printf '%s\n' "$*"; }
fail() {
  printf 'ERREUR : %s\n' "$*" >&2
  exit 1
}

case "${1:-}" in
  start | stop | restart | status | logs)
    COMMAND="$1"
    shift
    ;;
esac

while [ $# -gt 0 ]; do
  case "$1" in
    --port)
      [ $# -ge 2 ] || fail "--port attend une valeur."
      PORT="$2"
      PORT_EXPLICIT=1
      shift 2
      ;;
    --port=*)
      PORT="${1#*=}"
      PORT_EXPLICIT=1
      shift
      ;;
    --skip-build)
      DO_BUILD=0
      shift
      ;;
    --keep-data)
      DO_SEED=0
      shift
      ;;
    --open)
      DO_OPEN=1
      shift
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      fail "option inconnue : $1"
      ;;
  esac
done

case "$PORT" in
  '' | *[!0-9]*) fail "port invalide : $PORT" ;;
esac

running_pid() {
  [ -f "$PID_FILE" ] || return 1
  local pid
  pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  case "$pid" in
    '' | *[!0-9]*) return 1 ;;
  esac
  kill -0 "$pid" 2>/dev/null || return 1
  printf '%s' "$pid"
}

current_port() {
  if [ -f "$PORT_FILE" ]; then
    cat "$PORT_FILE"
  else
    printf '%s' "$PORT"
  fi
}

stop_instance() {
  local pid
  if ! pid="$(running_pid)"; then
    rm -f "$PID_FILE" "$PORT_FILE"
    log "Aucune instance de demonstration locale en cours."
    return 0
  fi
  kill "$pid" 2>/dev/null || true
  for _ in $(seq 1 40); do
    kill -0 "$pid" 2>/dev/null || break
    sleep 0.25
  done
  if kill -0 "$pid" 2>/dev/null; then
    kill -9 "$pid" 2>/dev/null || true
  fi
  rm -f "$PID_FILE" "$PORT_FILE"
  log "Instance de demonstration arretee (pid $pid)."
}

health_url() {
  printf 'http://%s:%s/api/health' "$HOST" "$1"
}

show_status() {
  local pid port
  if pid="$(running_pid)"; then
    port="$(current_port)"
    if curl -fsS --max-time 3 "$(health_url "$port")" >/dev/null 2>&1; then
      log "Demonstration active sur http://$HOST:$port (pid $pid)."
      return 0
    fi
    log "Processus present (pid $pid) mais l'API ne repond pas encore sur le port $port."
    return 1
  fi
  log "Aucune instance de demonstration locale en cours."
  return 1
}

port_is_free() {
  ! (exec 3<>"/dev/tcp/$HOST/$1") 2>/dev/null
}

resolve_port() {
  if port_is_free "$PORT"; then
    return 0
  fi
  if [ "$PORT_EXPLICIT" -eq 1 ]; then
    fail "le port $PORT est deja utilise. Relance avec --port <autre-port>."
  fi
  local candidate
  for candidate in $(seq $((PORT + 1)) $((PORT + 20))); do
    if port_is_free "$candidate"; then
      log "Port $PORT occupe, bascule sur $candidate."
      PORT="$candidate"
      return 0
    fi
  done
  fail "aucun port libre entre $PORT et $((PORT + 20)). Relance avec --port <autre-port>."
}

ensure_backend_env() {
  if [ ! -x "$VENV_DIR/bin/python" ]; then
    log "Creation de l'environnement Python backend..."
    command -v python3 >/dev/null 2>&1 || fail "python3 est requis."
    python3 -m venv "$VENV_DIR"
  fi
  if [ ! -x "$VENV_DIR/bin/uvicorn" ] || [ ! -x "$VENV_DIR/bin/moulaga-seed-demo" ]; then
    log "Installation des dependances backend..."
    (cd "$BACKEND_DIR" && "$VENV_DIR/bin/python" -m pip install --quiet --upgrade pip)
    (cd "$BACKEND_DIR" && "$VENV_DIR/bin/python" -m pip install --quiet -e '.[dev]')
  fi
}

build_frontend() {
  command -v npm >/dev/null 2>&1 || fail "npm est requis pour construire le frontend."
  if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
    log "Installation des dependances frontend..."
    if [ -f "$FRONTEND_DIR/package-lock.json" ]; then
      (cd "$FRONTEND_DIR" && npm ci)
    else
      (cd "$FRONTEND_DIR" && npm install)
    fi
  fi
  log "Build du frontend..."
  (cd "$FRONTEND_DIR" && npm run build)
}

seed_demo_data() {
  log "Generation de la seed de demonstration..."
  rm -rf "$DATA_DIR"
  mkdir -p "$DATA_DIR"
  (cd "$BACKEND_DIR" && MOULAGA_DATA_DIR="$DATA_DIR" "$VENV_DIR/bin/moulaga-seed-demo" --reset)
}

open_url() {
  if command -v open >/dev/null 2>&1; then
    open "$1" >/dev/null 2>&1 || true
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$1" >/dev/null 2>&1 || true
  fi
}

start_instance() {
  mkdir -p "$RUNTIME_DIR"
  stop_instance >/dev/null

  resolve_port

  ensure_backend_env
  if [ "$DO_BUILD" -eq 1 ]; then
    build_frontend
  elif [ ! -f "$BACKEND_DIR/app/static/index.html" ]; then
    fail "aucun build frontend disponible : relance sans --skip-build."
  fi
  if [ "$DO_SEED" -eq 1 ]; then
    seed_demo_data
  elif [ ! -f "$DATA_DIR/moulaga.db" ]; then
    fail "aucune base de demonstration disponible : relance sans --keep-data."
  fi

  log "Demarrage du serveur local..."
  (
    cd "$BACKEND_DIR"
    MOULAGA_DATA_DIR="$DATA_DIR" MOULAGA_DEMO_MODE=false \
      nohup "$VENV_DIR/bin/uvicorn" app.main:app --host "$HOST" --port "$PORT" \
      >"$LOG_FILE" 2>&1 &
    printf '%s' "$!" >"$PID_FILE"
  )
  printf '%s' "$PORT" >"$PORT_FILE"

  local pid
  pid="$(cat "$PID_FILE")"
  for _ in $(seq 1 60); do
    if curl -fsS --max-time 2 "$(health_url "$PORT")" >/dev/null 2>&1; then
      log ""
      log "Demonstration prete : http://$HOST:$PORT"
      log "Donnees synthetiques dans .data/demo, journal dans .data/demo-runtime/uvicorn.log."
      log "Arret : scripts/demo-local.sh stop"
      [ "$DO_OPEN" -eq 1 ] && open_url "http://$HOST:$PORT"
      return 0
    fi
    if ! kill -0 "$pid" 2>/dev/null; then
      break
    fi
    sleep 0.5
  done

  log "Dernieres lignes du journal :" >&2
  tail -n 20 "$LOG_FILE" >&2 || true
  stop_instance >/dev/null
  fail "le serveur de demonstration n'a pas repondu sur http://$HOST:$PORT."
}

case "$COMMAND" in
  start) start_instance ;;
  restart)
    stop_instance
    start_instance
    ;;
  stop) stop_instance ;;
  status) show_status ;;
  logs)
    [ -f "$LOG_FILE" ] || fail "aucun journal disponible."
    tail -n 100 "$LOG_FILE"
    ;;
esac
