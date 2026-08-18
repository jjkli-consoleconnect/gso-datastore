#!/usr/bin/env bash
set -euo pipefail

# macOS-compatible BigQuery pull script.
# Usage: ./pull_macos.sh [path/to/bq-sync.config.json]

CONFIG_PATH="${1:-$(dirname "$0")/bq-sync.config.json}"

# Pre-flight checks
command -v python3 >/dev/null 2>&1 || { echo "python3 not found. Install Python 3 and retry." >&2; exit 1; }
command -v bq >/dev/null 2>&1 || { echo "bq (BigQuery CLI) not found. Install Google Cloud SDK and enable bq component." >&2; exit 1; }
command -v gcloud >/dev/null 2>&1 || { echo "gcloud not found. Install Google Cloud SDK (gcloud)." >&2; exit 1; }

python3 - "$CONFIG_PATH" <<'PY'
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

def bq_query_json(project, loc_flag, sql):
    args = ['bq', '--format=prettyjson', 'query', f'--project_id={project}']
    if loc_flag:
        args.append(f'--location={loc_flag}')
    args += ['--nouse_legacy_sql', '--quiet', sql]
    out = run_check_output(args)
    return json.loads(out)

def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)

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

def main():
    cfg_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('bq-sync.config.json')
    if not cfg_path.exists():
        print(f'Config not found: {cfg_path}', file=sys.stderr)
        sys.exit(2)
    cfg = load_config(cfg_path)

    projects = cfg.get('projects') or []
    if not projects:
        print('No projects configured. Add at least one project ID in bq-sync.config.json', file=sys.stderr)
        sys.exit(2)

    location = cfg.get('location')
    initialize_google_auth(cfg, cfg_path)

    output_root = Path(cfg.get('outputDir'))
    if not output_root.is_absolute():
        output_root = (cfg_path.parent / output_root).resolve()
    ensure_dir(output_root)

    start = time.time()
    print('Starting BigQuery pull...')
    print('Projects: ' + ', '.join(projects))

    for project in projects:
        print(f'\nProcessing project: {project}')
        datasets = cfg.get('datasets') or []
        if not datasets:
            ls_args = ['ls', f'--project_id={project}']
            if location:
                ls_args.append(f'--location={location}')
            ls_args.append('-d')
            j = bq_json(ls_args)
            datasets = [d['datasetReference']['datasetId'] for d in j]

        print(f'  Found {len(datasets)} dataset(s)')
        for dataset in datasets:
            print(f'  Dataset: {dataset}')
            try:
                show_args = ['show']
                if location:
                    show_args.append(f'--location={location}')
                show_args += ['--dataset', f'{project}:{dataset}']
                dinfo = bq_json(show_args)
                if location and dinfo.get('location') and dinfo.get('location') != location:
                    print(f"Skipping dataset {project}:{dataset} in location {dinfo.get('location')} (wanted {location})")
                    continue
            except Exception as e:
                print(f'Failed to read dataset info for {project}:{dataset}: {e}', file=sys.stderr)
                continue

            base = output_root / project / dataset
            views_dir = base / 'views'
            mviews_dir = base / 'materialized_views'
            routines_dir = base / 'routines'
            if cfg.get('include', {}).get('views'):
                ensure_dir(views_dir)
            if cfg.get('include', {}).get('materializedViews'):
                ensure_dir(mviews_dir)
            if cfg.get('include', {}).get('routines'):
                ensure_dir(routines_dir)

            if cfg.get('include', {}).get('views') or cfg.get('include', {}).get('materializedViews'):
                if cfg.get('include', {}).get('views'):
                    sql = f"SELECT table_name, view_definition FROM `{project}.{dataset}.INFORMATION_SCHEMA.VIEWS` ORDER BY table_name"
                    try:
                        views = bq_query_json(project, location, sql)
                        print(f'    Views: {len(views)}')
                        for row in views:
                            t = row.get('table_name')
                            sqltext = row.get('view_definition')
                            path = views_dir / f"{t}.sql"
                            write_text(path, (sqltext or '') + '\n')
                            print(f'      OK {t}')
                    except Exception as e:
                        print(f'Failed to export views for {project}:{dataset}: {e}', file=sys.stderr)

                if cfg.get('include', {}).get('materializedViews'):
                    sql = f"SELECT table_name FROM `{project}.{dataset}.INFORMATION_SCHEMA.TABLES` WHERE table_type='MATERIALIZED VIEW' ORDER BY table_name"
                    try:
                        mviews = bq_query_json(project, location, sql)
                        print(f'    Materialized views: {len(mviews)}')
                        for row in mviews:
                            t = row.get('table_name')
                            try:
                                fq = f"{project}:{dataset}.{t}"
                                info = bq_json(['show'] + ([f'--location={location}'] if location else []) + [fq])
                                sqltext = info.get('materializedView', {}).get('query')
                                path = mviews_dir / f"{t}.sql"
                                write_text(path, (sqltext or '') + '\n')
                                print(f'      OK {t}')
                            except Exception as e:
                                print(f'Failed to export materialized view {t} in {project}:{dataset}: {e}', file=sys.stderr)
                    except Exception as e:
                        print(f'Failed to list materialized views for {project}:{dataset}: {e}', file=sys.stderr)

            if cfg.get('include', {}).get('routines'):
                try:
                    sql = f"SELECT routine_name FROM `{project}.{dataset}.INFORMATION_SCHEMA.ROUTINES` ORDER BY routine_name"
                    routines = bq_query_json(project, location, sql)
                    print(f'    Routines: {len(routines)}')
                    for row in routines:
                        r = row.get('routine_name')
                        try:
                            fq = f"{project}:{dataset}.{r}"
                            info = bq_json(['show'] + ([f'--location={location}'] if location else []) + ['--routine', fq])
                            body = info.get('definitionBody')
                            meta = {
                                'language': info.get('language'),
                                'routineType': info.get('routineType'),
                                'returnType': info.get('returnType'),
                                'importedLibraries': info.get('importedLibraries'),
                                'arguments': info.get('arguments'),
                            }
                            write_text(routines_dir / f"{r}.sql", (body or '') + '\n')
                            write_text(routines_dir / f"{r}.meta.json", json.dumps(meta, indent=2))
                            print(f'      OK {r}')
                        except Exception as e:
                            print(f'Failed to inspect routine {r} in {project}:{dataset}: {e}', file=sys.stderr)
                except Exception as e:
                    print(f'Failed to list routines for {project}:{dataset}: {e}', file=sys.stderr)

    elapsed = time.time() - start
    print(f"\nPull complete in {elapsed:.1f}s. Output: {output_root}")

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

echo "Done. Run: chmod +x BigQuerySync/pull_macos.sh && ./BigQuerySync/pull_macos.sh"
