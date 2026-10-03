"""Prepare local owner-review packages. Never writes to the application DB."""
import argparse
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('pdf_import', ROOT / 'www/scripts/pdf_import.py')
pdf_import = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pdf_import)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pdfs', nargs='+', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    for path in args.pdfs:
        mapping, background = pdf_import.extract_mapping_from_pdf(path.read_bytes(), zoom=3)
        slug = ('vkb-stecs-space-lh' if 'SpaceThrottle' in path.name else
                'vkb-stecs-stem' if 'STEM' in path.name else 'vkb-stecs-atem')
        mapping['image'] = slug
        (args.output / (slug + '.jpg')).write_bytes(background)
        (args.output / (slug + '.json')).write_text(json.dumps(mapping, indent=2), encoding='utf-8')
        lines = [f'# {mapping["title"]}: owner review', '',
                 'Draft only. No hardware ID or Joy code has been assumed.',
                 'Upload the JPEG in the editor first, then import the JSON and select that uploaded image.',
                 'Do not publish until every retained input has been verified.', '',
                 'Please provide: exact model, modules, firmware/profile, hardware IDs from the .binds file,',
                 'and the game input code for each physical action below.',
                 'An ordinary .binds file contains only assigned controls, not a complete hardware inventory.',
                 'Row positions are top-to-bottom within each group; PDF field names are not button numbers.', '',
                 '| Group / row | PDF field (provenance only) | Game input | Confirmed by |',
                 '| --- | --- | --- | --- |']
        for box in mapping['boxes']:
            for row in box['rows']:
                lines.append(f'| {box["physical_group"]} / {row["source_row"]} | {row["source_field"]} | | |')
        lines += ['', mapping['source_credit'], '',
                  'The printed frames remain visible even when an input is unused.',
                  'Dense multi-mode text still needs a real-render review before publication.']
        (args.output / (slug + '-review.md')).write_text('\n'.join(lines) + '\n', encoding='utf-8')
        print(f'{slug}: {len(mapping["boxes"])} areas, {mapping["width"]}x{mapping["height"]}, unpublished')


if __name__ == '__main__':
    main()
