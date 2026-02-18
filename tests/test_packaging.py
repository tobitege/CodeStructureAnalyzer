import os
import subprocess
import sys
import zipfile
from pathlib import Path


def test_wheel_includes_subpackages_and_cli_runs(tmp_path):
    """Wheel build/install smoke test for packaged runtime behavior."""
    repo_root = Path(__file__).resolve().parents[1]
    dist_dir = tmp_path / 'dist'
    install_dir = tmp_path / 'install'
    smoke_dir = tmp_path / 'smoke'
    dist_dir.mkdir()
    install_dir.mkdir()
    smoke_dir.mkdir()

    subprocess.run(
        [
            sys.executable,
            '-m',
            'pip',
            'wheel',
            str(repo_root),
            '--no-deps',
            '-w',
            str(dist_dir),
        ],
        check=True,
        cwd=repo_root,
    )

    wheels = sorted(dist_dir.glob('csa-*.whl'))
    assert wheels, 'Expected a built csa wheel'
    wheel_path = wheels[-1]

    with zipfile.ZipFile(wheel_path) as wheel_zip:
        names = wheel_zip.namelist()
    assert any(name.startswith('csa/reporters/') for name in names)
    assert any(name.startswith('csa/retrieval/') for name in names)

    subprocess.run(
        [
            sys.executable,
            '-m',
            'pip',
            'install',
            '--no-deps',
            '--target',
            str(install_dir),
            str(wheel_path),
        ],
        check=True,
        cwd=repo_root,
    )

    env = os.environ.copy()
    existing_pythonpath = env.get('PYTHONPATH', '')
    env['PYTHONPATH'] = (
        str(install_dir)
        if not existing_pythonpath
        else f'{install_dir}{os.pathsep}{existing_pythonpath}'
    )

    import_check = subprocess.run(
        [
            sys.executable,
            '-c',
            'import csa.reporters; import csa.retrieval; print("ok")',
        ],
        cwd=smoke_dir,
        env=env,
        capture_output=True,
        text=True,
    )
    assert import_check.returncode == 0, import_check.stderr

    help_check = subprocess.run(
        [sys.executable, '-m', 'csa.cli', '--help'],
        cwd=smoke_dir,
        env=env,
        capture_output=True,
        text=True,
    )
    assert help_check.returncode == 0, help_check.stderr
    assert 'Code Structure Analyzer' in help_check.stdout
