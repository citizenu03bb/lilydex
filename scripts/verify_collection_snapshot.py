"""Rebuild a restored library offline and prepare a representative evaluation sample."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import socket
import sys

import pandas as pd


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('restored', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    project = args.restored.resolve() / 'project'
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(project / 'src'))
    from pokeprice.library import build_library
    from pokeprice.report import read_report

    # Network access must not be required to recover the existing collection.
    def deny_network(*args, **kwargs):
        raise RuntimeError('Network disabled during snapshot recovery')
    socket.socket = deny_network
    manifest = json.loads((project / 'pokeprice_library_manifest.json').read_text())
    for album in manifest['albums']:
        album['report'] = str(project / album['report'])
        album['photos'] = str(args.restored.resolve() / 'photos' / album['id'])
    recovered_manifest = out / 'restored_manifest.json'
    recovered_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    result = build_library(recovered_manifest, out / 'pokeprice_library')
    assert result == {'copies': 401, 'editions': 347, 'unresolved': 1, 'albums': 3}
    original = read_report(project / 'pokeprice_library.csv')
    rebuilt = read_report(out / 'pokeprice_library.csv')
    fields = [c for c in original.columns if c != 'Rapport_Source']
    pd.testing.assert_frame_equal(original[fields], rebuilt[fields], check_dtype=False)

    frozen_json = json.loads((project / 'pokeprice_library.json').read_text())
    rebuilt_json = json.loads((out / 'pokeprice_library.json').read_text())
    for payload in [frozen_json, rebuilt_json]:
        for group in payload['groups']:
            for copy in group['copies']:
                copy.pop('report_url', None)
    assert frozen_json == rebuilt_json
    def embedded(path):
        return json.loads(re.search(r'const LIBRARY = (.*?);\nconst search', path.read_text(), re.S).group(1))
    old_embedded = embedded(project / 'pokeprice_library.html')
    new_embedded = embedded(out / 'pokeprice_library.html')
    old_crops = {c['id']: c['image'] for g in old_embedded['groups'] for c in g['copies']}
    new_crops = {c['id']: c['image'] for g in new_embedded['groups'] for c in g['copies']}
    assert old_crops == new_crops and len(new_crops) == 401

    expected_counts = {'diamond-pearl': 111, 'platinium': 110, 'platinium-3x3': 180}
    assert rebuilt.Album_ID.value_counts().to_dict() == expected_counts
    assert int((rebuilt.Statut_Identification == 'confirmed').sum()) == 400
    assert int(((rebuilt.Statut_Identification == 'confirmed') & rebuilt.Prix_Reference_EUR.isna()).sum()) == 22
    excluded = json.loads((project / 'outputs/fixes-2026-10-04/excluded_entries.json').read_text())
    for entry in excluded:
        rows = rebuilt[rebuilt.Rapport_Source.str.endswith(entry['report'] + '.csv')]
        assert not ((rows.Fichier_Image == entry['image_file']) & (rows.Position == entry['position'])).any()
        album_id = rows.Album_ID.iloc[0]
        assert (args.restored / 'photos' / album_id / entry['image_file']).is_file()
    photo_exclusions = json.loads((project / 'outputs/platinium-3x3/input_manifest.json').read_text())['excluded']
    for entry in photo_exclusions:
        assert not ((rebuilt.Album_ID == 'platinium-3x3') & (rebuilt.Fichier_Image == entry['file'])).any()
        assert (args.restored / 'photos/platinium-3x3' / entry['file']).is_file()

    # Explicit corrections and contrasting printings are checked against the snapshot.
    cases = [
        ('diamond-pearl', 11, 4, 'PV corrigés, référence confirmée'),
        ('diamond-pearl', 19, 3, 'carte anglaise'),
        ('diamond-pearl', 20, 2, 'carte japonaise hors catalogue, prix absent'),
        ('diamond-pearl', 14, 2, 'identité non résolue'),
        ('diamond-pearl', 23, 3, 'extension et référence corrigées'),
        ('platinium', 16, 3, 'carte japonaise hors catalogue, prix absent'),
        ('platinium', 24, 3, 'carte anglaise avec référence corrigée'),
        ('platinium', 19, 4, 'Octillery 58/127 corrigé'),
        ('platinium', 3, 3, 'Kirlia 51/127 corrigé'),
        ('platinium', 4, 4, 'Pikachu 5/12, doublon 1'),
        ('platinium', 5, 3, 'Pikachu 5/12, doublon 2'),
        ('platinium', 8, 1, 'Pikachu 5/12, doublon 3'),
        ('platinium', 14, 1, 'identité confirmée sans prix'),
        ('platinium', 2, 1, 'Arbok, variante holo'),
        ('platinium-3x3', 1, 1, 'Zarbi L, doublon 1'),
        ('platinium-3x3', 1, 2, 'Zarbi L, doublon 2'),
        ('platinium-3x3', 9, 1, 'Capidextre 35/100 corrigé'),
        ('platinium-3x3', 15, 7, 'Fossile Crâne 120/127 corrigé'),
        ('platinium-3x3', 18, 9, 'PokéNav 81/106 corrigé'),
        ('platinium-3x3', 6, 3, 'Arbok, variante non holo'),
    ]
    frames = []
    sample_dir = out / 'sample'
    (sample_dir / 'photos').mkdir(parents=True)
    photo_manifest = []
    for album, page, position, case in cases:
        selection = rebuilt[(rebuilt.Album_ID == album) & (rebuilt.Page == page) & (rebuilt.Position == position)].copy()
        assert len(selection) == 1
        copy_id = selection.Exemplaire_ID.iloc[0]
        asset = 'photos/' + hashlib.sha256(copy_id.encode()).hexdigest()[:16] + '.jpg'
        crop = base64.b64decode(new_crops[copy_id].split(',', 1)[1])
        (sample_dir / asset).write_bytes(crop)
        photo_manifest.append({'id': copy_id, 'path': asset, 'sha256': hashlib.sha256(crop).hexdigest()})
        selection['Evaluation_Case'] = case
        selection['Evaluation_Photo'] = asset
        frames.append(selection)
    sample = pd.concat(frames, ignore_index=True)
    assert len(sample) == sample.Exemplaire_ID.nunique() == 20
    for album, page, pos, reference in [('platinium', 19, 4, '58/127'), ('platinium', 3, 3, '51/127'),
                                        ('platinium-3x3', 9, 1, '35/100'), ('platinium-3x3', 15, 7, '120/127'),
                                        ('platinium-3x3', 18, 9, '81/106')]:
        row = sample[(sample.Album_ID == album) & (sample.Page == page) & (sample.Position == pos)].iloc[0]
        assert row.Numero_Officiel == reference and row.Statut_Identification == 'confirmed'
    sample.to_csv(sample_dir / 'sample.csv', index=False)
    (sample_dir / 'sample.json').write_text(sample.to_json(orient='records', force_ascii=False, indent=2) + '\n')
    (sample_dir / 'photo_manifest.json').write_text(json.dumps(photo_manifest, indent=2) + '\n')
    (sample_dir / 'exclusions.json').write_text(json.dumps({'pockets': excluded, 'photos': photo_exclusions}, ensure_ascii=False, indent=2) + '\n')
    summary = {'library': result, 'album_counts': expected_counts, 'confirmed_copies': 400,
               'confirmed_without_price': 22, 'restored_crops_identical': len(new_crops),
               'sample_size': len(sample), 'excluded_pockets': len(excluded),
               'excluded_photos': len(photo_exclusions), 'network_disabled': True,
               'runtime_python': sys.version, 'source_module': str(Path(sys.modules['pokeprice.library'].__file__))}
    (out / 'validation.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
