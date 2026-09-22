"""Optional helper: rebuild assets/map/source.blend from source.blend.partNNN files."""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
map_dir = root / 'assets' / 'map'
parts = sorted(map_dir.glob('source.blend.part[0-9][0-9][0-9]'))
out_path = map_dir / 'source.blend'
if not parts:
    raise SystemExit('No source.blend.partNNN files found.')
with out_path.open('wb') as out:
    for part in parts:
        print('Adding', part.name)
        with part.open('rb') as src:
            while True:
                chunk = src.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
print('Created:', out_path, out_path.stat().st_size, 'bytes')
