#!/usr/bin/env bash
set -euo pipefail

# macOS/Linux-compatible BigQuery pull script.
# Mirrors the behaviour of pull.ps1: region-level listing for speed, orphan
# pruning so the repo matches BigQuery, and optional delta mode.
#
# Usage: ./pull_macos.sh [path/to/bq-sync.config.json] [--delta] [--dry-run] [--no-prune] [--skip-verify-removals]

CONFIG_PATH="$(dirname "$0")/bq-sync.config.json"
CONFIG_SET=0
EXTRA_ARGS=()
for arg in "$@"; do
  case "$arg" in
    --delta|--dry-run|--no-prune|--skip-verify-removals) EXTRA_ARGS+=("$arg") ;;
    *)
      if [ "$CONFIG_SET" -eq 0 ]; then
        CONFIG_PATH="$arg"
        CONFIG_SET=1
      else
        echo "Unknown argument: $arg" >&2
        exit 2
      fi
      ;;
  esac
done
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Pre-flight checks
command -v python3 >/dev/null 2>&1 || { echo "python3 not found. Install Python 3 and retry." >&2; exit 1; }
command -v bq >/dev/null 2>&1 || { echo "bq (BigQuery CLI) not found. Install Google Cloud SDK and enable bq component." >&2; exit 1; }
command -v gcloud >/dev/null 2>&1 || { echo "gcloud not found. Install Google Cloud SDK (gcloud)." >&2; exit 1; }

python3 - "$CONFIG_PATH" "$SCRIPT_DIR" "${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}" <<'PY'
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

def read_json(p: Path):
    with p.open('r', encoding='utf-8') as f:
        return json.load(f)

def load_config(base_path: Path):
    cfg = read_json(base_path)
    local_path = base_path.with_name(base_path.stem + '.config.local.json')
    if local_path.exists():
        local_cfg = read_json(local_path)
        cfg.update(local_cfg)
    return cfg

def run_check_output(args):
    try:
        out = subprocess.check_output(args, stderr=subprocess.STDOUT)
        return out.decode('utf-8')
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Command failed: {' '.join(args)}\n{e.output.decode('utf-8', errors='replace')}" )

def bq_json(args_list):
    args = ['bq', '--format=prettyjson'] + args_list
    out = run_check_output(args)
    return json.loads(out)

def bq_query_json(project, loc_value, sql):
    args = ['bq', '--format=prettyjson', 'query', f'--project_id={project}']
    if loc_value:
        args.append(f'--location={loc_value}')
    args += ['--nouse_legacy_sql', '--quiet', sql]
    out = run_check_output(args)
    return json.loads(out)

def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)

def assert_path_segment(value, name):
    if not isinstance(value, str) or not value or value in ('.', '..') or Path(value).name != value or '/' in value or '\\' in value:
        raise ValueError(f'{name} must be one safe folder name: {value}')

def write_text(path: Path, text: str):
    ensure_dir(path.parent)
    path.write_text(text, encoding='utf-8')

def initialize_google_auth(cfg, script_root: Path):
    if os.environ.get('GOOGLE_APPLICATION_CREDENTIALS') or os.environ.get('CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE'):
        print('Using credentials from current environment.')
        return
    cred = cfg.get('credentialsFile')
    if cred and cred.strip():
        full_cred = Path(cred)
        if not full_cred.is_absolute():
            full_cred = (script_root.parent / cred).resolve()
        os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = str(full_cred)
        os.environ['CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE'] = str(full_cred)
        subprocess.check_call(['gcloud', 'auth', 'activate-service-account', '--key-file', str(full_cred)])
        print('Using credentialsFile override. Prefer ADC or external env var over repo-local key files.')
        return
    print('Using current gcloud/ADC authentication. Set GOOGLE_APPLICATION_CREDENTIALS or add a local override only if needed.')

def is_missing_error(message: str) -> bool:
    lowered = message.lower()
    return 'not found' in lowered or 'notfound' in lowered or '404' in lowered or 'does not exist' in lowered

def bq_object_probe(kind, project, dataset, name, location):
    """exists: True = still exists, False = confirmed gone, None = unknown."""
    args = ['show']
    if location:
        args.append(f'--location={location}')
    if kind == 'routines':
        args += ['--routine', f'{project}:{dataset}.{name}']
    else:
        args += [f'{project}:{dataset}.{name}']
    try:
        return {'exists': True, 'info': bq_json(args)}
    except Exception as e:
        message = str(e)
        if is_missing_error(message):
            return {'exists': False, 'info': None}
        print(f'Could not confirm the status of {kind} {project}:{dataset}.{name}: {e}', file=sys.stderr)
        return {'exists': None, 'info': None}

def rescue_payload(kind, info, name):
    """Rebuild the local payload from a `bq show` result, or None when unusable."""
    if kind == 'views':
        query = (info.get('view') or {}).get('query')
        return None if not query else (f'{query}\n', None)
    if kind == 'materialized_views':
        query = (info.get('materializedView') or {}).get('query')
        return None if not query else (f'{query}\n', None)
    if kind == 'routines':
        body = info.get('definitionBody')
        if not body:
            return None
        meta = {
            'language': info.get('language'),
            'routineType': info.get('routineType'),
            'returnType': info.get('returnType'),
            'importedLibraries': info.get('importedLibraries'),
            'arguments': info.get('arguments'),
        }
        return (f'{body}\n', json.dumps(meta, indent=2))
    return None

def bq_dataset_exists(project, dataset, location):
    """True = still exists, False = confirmed gone, None = unknown."""
    args = ['show']
    if location:
        args.append(f'--location={location}')
    args += ['--dataset', f'{project}:{dataset}']
    try:
        bq_json(args)
        return True
    except Exception as e:
        if is_missing_error(str(e)):
            return False
        return None

def publish_object(state, key, payload, path, delta, dry_run, stats, label, last_altered=None, hash_payload=None):
    digest = hashlib.sha256((hash_payload if hash_payload is not None else payload).encode('utf-8')).hexdigest()
    exists = path.exists()
    previous = state['objects'].get(key, {}).get('hash')
    if delta and exists and previous == digest:
        stats['unchanged'] += 1
        print(f'      = {label}')
        return
    if not exists:
        stats['added'] += 1
    elif previous == digest:
        stats['unchanged'] += 1
    else:
        stats['updated'] += 1
    if dry_run:
        print(f'      [dry-run] write {path}')
        return
    write_text(path, payload)
    entry = {'hash': digest}
    if last_altered:
        entry['lastAltered'] = last_altered
    state['objects'][key] = entry
    print(f'      OK {label}')

def prune_files(directory, names, suffixes, kind, project, dataset, location, verify, dry_run, stats, state, delta, key_prefix):
    if not directory.is_dir():
        return
    for entry in sorted(directory.iterdir()):
        if not entry.is_file():
            continue
        suffix = next((s for s in suffixes if entry.name.endswith(s)), None)
        if suffix is None:
            continue
        base = entry.name[: -len(suffix)]
        if base.lower() in names:
            continue
        if verify:
            probe = bq_object_probe(kind, project, dataset, base, location)
            if probe['exists'] is True:
                # Metadata listings can lag or hide objects. Refresh from
                # `bq show` instead of deleting a file whose object still exists.
                rescued = rescue_payload(kind, probe['info'], base)
                if rescued is not None:
                    payload, meta_json = rescued
                    hash_payload = payload if meta_json is None else f'{payload}\n{meta_json}'
                    publish_object(state, f'{key_prefix}{base}', payload, entry, delta, dry_run, stats, base, None, hash_payload)
                    if meta_json is not None and not dry_run:
                        write_text(entry.parent / f'{base}.meta.json', meta_json)
                    names.add(base.lower())
                    print(f'{kind} {project}:{dataset}.{base} is missing from the metadata listing but still exists in BigQuery; refreshed {entry.name} instead of deleting it.', file=sys.stderr)
                    continue
                print(f'{kind} {project}:{dataset}.{base} is missing from the metadata listing but still exists in BigQuery; keeping {entry.name}.', file=sys.stderr)
                continue
            if probe['exists'] is None:
                print(f'Keeping {entry}: could not verify that {base} was removed from BigQuery.', file=sys.stderr)
                continue
        if dry_run:
            print(f'      [dry-run] delete {entry}')
        else:
            entry.unlink()
            print(f'      deleted {entry}')
        stats['deleted'] += 1

def clear_state_scope(state, prefix, names):
    for key in [k for k in state['objects'] if k.startswith(prefix)]:
        if key[len(prefix):].lower() not in names:
            del state['objects'][key]

def remove_dataset_folder(project, dataset, dataset_dir, location, state, verify, dry_run, delta, stats):
    if verify:
        exists = bq_dataset_exists(project, dataset, location)
        if exists is not False:
            print(f'Dataset {project}:{dataset} is not returned by bq ls -d but could not be confirmed as deleted; keeping {dataset_dir}.', file=sys.stderr)
            return
    print(f'  Dataset {dataset} no longer exists in BigQuery')
    suffix_map = {'views': ['.sql'], 'materialized_views': ['.sql'], 'routines': ['.sql', '.meta.json']}
    for sub, suffixes in suffix_map.items():
        sub_dir = dataset_dir / sub
        prune_files(sub_dir, set(), suffixes, sub, project, dataset, location, verify, dry_run, stats, state, delta, f'{project}|{dataset}|{sub}|')
        if not dry_run and sub_dir.is_dir() and not any(sub_dir.iterdir()):
            sub_dir.rmdir()
    clear_state_scope(state, f'{project}|{dataset}|', set())
    if dry_run:
        return
    if dataset_dir.is_dir() and not any(dataset_dir.iterdir()):
        dataset_dir.rmdir()
        print(f'      removed dataset folder {dataset_dir}')
    else:
        print(f'Dataset folder {dataset_dir} is gone from BigQuery but still holds non-managed files; left in place.', file=sys.stderr)

def main():
    flags = [a for a in sys.argv[1:] if a.startswith('-')]
    positional = [a for a in sys.argv[1:] if not a.startswith('-')]
    cfg_path = Path(positional[0]) if positional else Path('bq-sync.config.json')
    script_dir = Path(positional[1]).resolve() if len(positional) > 1 else Path.cwd()
    if not cfg_path.exists():
        print(f'Config not found: {cfg_path}', file=sys.stderr)
        sys.exit(2)
    cfg = load_config(cfg_path)

    delta = ('--delta' in flags) or bool(cfg.get('delta'))
    dry_run = '--dry-run' in flags
    do_prune = ('--no-prune' not in flags) and bool(cfg.get('prune', True))
    verify = ('--skip-verify-removals' not in flags) and bool(cfg.get('verifyRemovals', True))

    projects = [str(p).strip() for p in (cfg.get('projects') or []) if str(p).strip()]
    if not projects:
        print('No projects configured. Add at least one project ID in bq-sync.config.json', file=sys.stderr)
        sys.exit(2)

    only_datasets = [str(d).strip() for d in (cfg.get('datasets') or []) if str(d).strip()]
    location = (cfg.get('location') or '').strip() or None

    include = cfg.get('include') or {}
    inc_views = bool(include.get('views'))
    inc_mviews = bool(include.get('materializedViews'))
    inc_routines = bool(include.get('routines'))

    state_name = (cfg.get('stateFile') or '').strip() or '.bq-sync.state.json'
    state_path = Path(state_name)
    if not state_path.is_absolute():
        state_path = cfg_path.parent / state_name

    initialize_google_auth(cfg, cfg_path)

    output_root = Path(cfg.get('outputDir'))
    if not output_root.is_absolute():
        output_root = (script_dir.parent / output_root).resolve()
    resource_subdir = cfg.get('resourceSubdir', 'BigQuery')
    assert_path_segment(resource_subdir, 'resourceSubdir')
    ensure_dir(output_root)

    state = {'version': 1, 'objects': {}}
    if state_path.exists():
        try:
            loaded = read_json(state_path)
            if isinstance(loaded.get('objects'), dict):
                state['objects'] = loaded['objects']
        except Exception as e:
            print(f'Could not read state file {state_path}: {e}', file=sys.stderr)

    stats = {'added': 0, 'updated': 0, 'unchanged': 0, 'deleted': 0, 'errors': 0}

    start = time.time()
    print('Starting BigQuery pull...')
    print('Projects: ' + ', '.join(projects))
    mode = ['delta' if delta else 'full', 'mirror' if do_prune else 'no-prune']
    if do_prune:
        mode.append('verify-removals' if verify else 'no-verify')
    if dry_run:
        mode.append('dry-run')
    print('Mode: ' + ', '.join(mode))

    dataset_done = 0
    for project in projects:
        assert_path_segment(project, 'project ID')
        project_output = output_root / project / resource_subdir
        print(f'\nProcessing project: {project}')
        print(f'  Output: {project_output}')

        ls_args = ['ls', f'--project_id={project}']
        if location:
            ls_args.append(f'--location={location}')
        ls_args.append('-d')
        listing = bq_json(ls_args) or []
        live = {}
        for entry in listing:
            name = (entry.get('datasetReference') or {}).get('datasetId')
            if name:
                live[name] = entry.get('location')

        if only_datasets:
            pull_set = []
            for ds in only_datasets:
                if ds in live:
                    pull_set.append(ds)
                else:
                    print(f'Configured dataset {project}:{ds} does not exist in BigQuery.', file=sys.stderr)
        else:
            pull_set = list(live.keys())

        by_location = {}
        for ds in pull_set:
            ds_location = live.get(ds) or 'unknown'
            if location and ds_location != location:
                print(f'  Skipping dataset {ds} in location {ds_location} (wanted {location})')
                continue
            by_location.setdefault(ds_location, []).append(ds)

        dataset_total = len(pull_set)
        dataset_done = 0
        print(f'  Found {dataset_total} dataset(s) in {len(by_location)} location group(s)')

        for ds_location, group in by_location.items():
            show_location = None if ds_location == 'unknown' else ds_location
            region_queries = []
            if inc_views:
                region_queries.append(f'SELECT 1 AS kind, table_schema, table_name, view_definition AS body, CAST(NULL AS STRING) AS last_altered FROM `{project}`.`region-{ds_location}`.INFORMATION_SCHEMA.VIEWS')
            if inc_mviews:
                region_queries.append(f"SELECT 2 AS kind, table_schema, table_name, CAST(NULL AS STRING) AS body, CAST(NULL AS STRING) AS last_altered FROM `{project}`.`region-{ds_location}`.INFORMATION_SCHEMA.TABLES WHERE table_type = 'MATERIALIZED VIEW'")
            if inc_routines:
                region_queries.append(f'SELECT 3 AS kind, routine_schema AS table_schema, routine_name AS table_name, CAST(NULL AS STRING) AS body, CAST(last_altered AS STRING) AS last_altered FROM `{project}`.`region-{ds_location}`.INFORMATION_SCHEMA.ROUTINES')

            views_by_ds = None
            mviews_by_ds = None
            routines_by_ds = None
            if region_queries and ds_location != 'unknown':
                try:
                    rows = bq_query_json(project, show_location, '\nUNION ALL\n'.join(region_queries)) or []
                    views_by_ds = {ds: [] for ds in group}
                    mviews_by_ds = {ds: [] for ds in group}
                    routines_by_ds = {ds: [] for ds in group}
                    for row in rows:
                        ds = row.get('table_schema')
                        if ds not in views_by_ds:
                            continue
                        kind = row.get('kind')
                        if kind == 1:
                            views_by_ds[ds].append(row)
                        elif kind == 2:
                            mviews_by_ds[ds].append(row)
                        elif kind == 3:
                            routines_by_ds[ds].append(row)
                    print(f'  Location {ds_location}: listed with region-level query')
                except Exception as e:
                    print(f'Region-level listing failed for {project} (region-{ds_location}): {e}', file=sys.stderr)
                    views_by_ds = None
                    mviews_by_ds = None
                    routines_by_ds = None

            for dataset in group:
                dataset_done += 1
                print(f'  Dataset: {dataset} ({dataset_done}/{dataset_total}) [{ds_location}]')
                dataset_base = project_output / dataset
                views_dir = dataset_base / 'views'
                mviews_dir = dataset_base / 'materialized_views'
                routines_dir = dataset_base / 'routines'

                if inc_views:
                    rows = []
                    listed = False
                    if views_by_ds is not None:
                        rows = views_by_ds.get(dataset, [])
                        listed = True
                    else:
                        try:
                            sql = f'SELECT table_name, view_definition FROM `{project}.{dataset}.INFORMATION_SCHEMA.VIEWS` ORDER BY table_name'
                            rows = bq_query_json(project, show_location, sql) or []
                            listed = True
                        except Exception as e:
                            print(f'Failed to list views for {project}:{dataset}: {e}', file=sys.stderr)
                            stats['errors'] += 1
                    if listed:
                        if not dry_run:
                            ensure_dir(views_dir)
                        names = set()
                        for row in rows:
                            name = row.get('table_name')
                            if not name:
                                continue
                            names.add(name.lower())
                            path = views_dir / f'{name}.sql'
                            definition = row.get('view_definition') or ''
                            if not definition.strip():
                                # INFORMATION_SCHEMA sometimes returns a NULL
                                # view_definition; fetch via bq show instead of
                                # writing an empty file over a good local copy.
                                probe = bq_object_probe('views', project, dataset, name, show_location)
                                if probe['exists'] is True:
                                    rescued = rescue_payload('views', probe['info'], name)
                                    if rescued is not None:
                                        publish_object(state, f'{project}|{dataset}|views|{name}', rescued[0], path, delta, dry_run, stats, name)
                                        continue
                                print(f'Listing returned an empty definition for view {project}:{dataset}.{name}; kept {path} untouched.', file=sys.stderr)
                                stats['errors'] += 1
                                continue
                            payload = f"{definition}\n"
                            publish_object(state, f'{project}|{dataset}|views|{name}', payload, path, delta, dry_run, stats, name)
                        if do_prune:
                            prune_files(views_dir, names, ['.sql'], 'views', project, dataset, show_location, verify, dry_run, stats, state, delta, f'{project}|{dataset}|views|')
                        clear_state_scope(state, f'{project}|{dataset}|views|', names)
                        print(f'    Views: {len(rows)}')

                if inc_mviews:
                    rows = []
                    listed = False
                    if mviews_by_ds is not None:
                        rows = mviews_by_ds.get(dataset, [])
                        listed = True
                    else:
                        try:
                            sql = f"SELECT table_name FROM `{project}.{dataset}.INFORMATION_SCHEMA.TABLES` WHERE table_type = 'MATERIALIZED VIEW' ORDER BY table_name"
                            rows = bq_query_json(project, show_location, sql) or []
                            listed = True
                        except Exception as e:
                            print(f'Failed to list materialized views for {project}:{dataset}: {e}', file=sys.stderr)
                            stats['errors'] += 1
                    if listed:
                        if not dry_run:
                            ensure_dir(mviews_dir)
                        names = set()
                        for row in rows:
                            name = row.get('table_name')
                            if not name:
                                continue
                            names.add(name.lower())
                            try:
                                show_args = ['show']
                                if show_location:
                                    show_args.append(f'--location={show_location}')
                                show_args.append(f'{project}:{dataset}.{name}')
                                info = bq_json(show_args)
                                payload = f"{(info.get('materializedView') or {}).get('query') or ''}\n"
                                path = mviews_dir / f'{name}.sql'
                                if not payload.strip():
                                    print(f'Empty definition returned for materialized view {project}:{dataset}.{name}; kept {path} untouched.', file=sys.stderr)
                                    stats['errors'] += 1
                                    continue
                                publish_object(state, f'{project}|{dataset}|materialized_views|{name}', payload, path, delta, dry_run, stats, name)
                            except Exception as e:
                                print(f'Failed to export materialized view {name} in {project}:{dataset}: {e}', file=sys.stderr)
                                stats['errors'] += 1
                        if do_prune:
                            prune_files(mviews_dir, names, ['.sql'], 'materialized_views', project, dataset, show_location, verify, dry_run, stats, state, delta, f'{project}|{dataset}|materialized_views|')
                        clear_state_scope(state, f'{project}|{dataset}|materialized_views|', names)
                        print(f'    Materialized views: {len(rows)}')

                if inc_routines:
                    rows = []
                    listed = False
                    if routines_by_ds is not None:
                        rows = routines_by_ds.get(dataset, [])
                        listed = True
                    else:
                        try:
                            sql = f'SELECT routine_name, CAST(last_altered AS STRING) AS last_altered FROM `{project}.{dataset}.INFORMATION_SCHEMA.ROUTINES` ORDER BY routine_name'
                            rows = bq_query_json(project, show_location, sql) or []
                            listed = True
                        except Exception as e:
                            print(f'Failed to list routines for {project}:{dataset}: {e}', file=sys.stderr)
                            stats['errors'] += 1
                    if listed:
                        if not dry_run:
                            ensure_dir(routines_dir)
                        names = set()
                        for row in rows:
                            name = row.get('table_name')
                            if not name:
                                continue
                            names.add(name.lower())
                            key = f'{project}|{dataset}|routines|{name}'
                            sql_path = routines_dir / f'{name}.sql'
                            meta_path = routines_dir / f'{name}.meta.json'
                            last_altered = row.get('last_altered')

                            # Delta: last_altered is authoritative, so skip the
                            # per-routine bq show when nothing changed.
                            if delta and last_altered and sql_path.exists() and meta_path.exists() and state['objects'].get(key, {}).get('lastAltered') == last_altered:
                                stats['unchanged'] += 1
                                print(f'      = {name}')
                                continue

                            try:
                                show_args = ['show']
                                if show_location:
                                    show_args.append(f'--location={show_location}')
                                show_args += ['--routine', f'{project}:{dataset}.{name}']
                                info = bq_json(show_args)
                                meta = {
                                    'language': info.get('language'),
                                    'routineType': info.get('routineType'),
                                    'returnType': info.get('returnType'),
                                    'importedLibraries': info.get('importedLibraries'),
                                    'arguments': info.get('arguments'),
                                }
                                meta_json = json.dumps(meta, indent=2)
                                body = f"{info.get('definitionBody') or ''}\n"
                                if not body.strip():
                                    print(f'Empty definition returned for routine {project}:{dataset}.{name}; kept {sql_path} untouched.', file=sys.stderr)
                                    stats['errors'] += 1
                                    continue
                                publish_object(state, key, body, sql_path, delta, dry_run, stats, name, last_altered, f'{body}\n{meta_json}')
                                if not dry_run:
                                    write_text(meta_path, meta_json)
                            except Exception as e:
                                print(f'Failed to inspect routine {name} in {project}:{dataset}: {e}', file=sys.stderr)
                                stats['errors'] += 1
                        if do_prune:
                            prune_files(routines_dir, names, ['.sql', '.meta.json'], 'routines', project, dataset, show_location, verify, dry_run, stats, state, delta, f'{project}|{dataset}|routines|')
                        clear_state_scope(state, f'{project}|{dataset}|routines|', names)
                        print(f'    Routines: {len(rows)}')

        if do_prune and not only_datasets and project_output.is_dir():
            live_lower = {k.lower() for k in live}
            for folder in sorted(p for p in project_output.iterdir() if p.is_dir()):
                if folder.name.lower() in live_lower:
                    continue
                if folder.name.startswith('_'):
                    print(f'  Keeping {folder}: hidden datasets are not listed by bq ls -d')
                    continue
                print(f'  Checking local-only dataset folder {folder.name}...')
                remove_dataset_folder(project, folder.name, folder, location, state, verify, dry_run, delta, stats)

    if not dry_run:
        state_doc = {'version': 1, 'generatedAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'objects': state['objects']}
        write_text(state_path, json.dumps(state_doc, indent=2))

    elapsed = time.time() - start
    print(f'\nPull complete in {elapsed:.1f}s.')
    print(f"  added {stats['added']}, updated {stats['updated']}, unchanged {stats['unchanged']}, deleted {stats['deleted']}, errors {stats['errors']}")
    print(f'  Output: {output_root}')
    if delta and not dry_run:
        print(f'  State: {state_path}')
    if dry_run:
        print('  Dry run: nothing was written or deleted.')
    if stats['errors']:
        print(f"{stats['errors']} object(s) could not be pulled; re-run to retry (lists that failed are never pruned).", file=sys.stderr)

if __name__ == '__main__':
    try:
        main()
    except RuntimeError as e:
        msg = str(e)
        print('\nError: ' + msg, file=sys.stderr)
        if 'Reauthentic' in msg or 'reauthentic' in msg or 'Reauthentication failed' in msg or 'cannot prompt' in msg:
            print('\nAuthentication issue detected. To fix, run one of the following commands and retry:', file=sys.stderr)
            print('  gcloud auth login', file=sys.stderr)
            print('or', file=sys.stderr)
            print('  gcloud auth application-default login', file=sys.stderr)
        else:
            print('Inspect the error above and retry.', file=sys.stderr)
        sys.exit(3)
PY
