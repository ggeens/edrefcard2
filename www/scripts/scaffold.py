"""Auto-scaffold draft controller mappings from an uploaded .binds file.

Given a device ID and the raw .binds XML, extract every Joy_* input actually
used for that device and build a provisional data-driven mapping (grouped
boxes, two-column layout, no button anchors). The admin then uploads the clean
photo and drags the boxes into place in the mapping editor: a new controller
becomes a 10-minute editor session instead of a hand-written seed.
"""

import re

from lxml import etree

# Nominal canvas for the provisional layout: boxes are rescaled client-side
# by the editor when the real image (with its own dimensions) is uploaded.
NOMINAL_W, NOMINAL_H = 4400, 2560
_COL_W = 1380
_COL_X = (70, NOMINAL_W - _COL_W - 70)   # left and right margin columns
_TOP_Y = 200
_ROW_H = 72          # per-row height contribution (matches the AEROMAX seed)
_BOX_PAD = 40        # box chrome (header) height
_GAP = 60            # vertical gap between boxes
_MAX_ROWS_PER_BOX = 6

_POV_RE = re.compile(r'^Joy_(POV\d+)(Up|Right|Down|Left)$')
_BTN_RE = re.compile(r'^Joy_(\d+)$')
_AXIS_RE = re.compile(r'^Joy_([RUV]?[XYZ]?)Axis$')

# Direction order and axis labels follow the existing seeds' conventions.
_POV_ORDER = ('Up', 'Right', 'Down', 'Left')
_AXIS_LABELS = {
    'X': 'STICK', 'Y': 'STICK',
    'Z': 'AXIS Z (twist)',
    'RX': 'AXIS RX', 'RY': 'AXIS RY',
    'RZ': 'AXIS RZ',
    'U': 'AXIS U (slider)', 'V': 'AXIS V (dial)',
}


def extract_device_keys(xml, device_id):
    """Return the sorted set of Key values bound to device_id in a .binds XML.

    Unlike parseBindings this is NOT filtered by display groups or known
    controls: the scaffold wants every physical input the user ever touched.
    """
    parser = etree.XMLParser(encoding='utf-8', resolve_entities=False)
    tree = etree.fromstring(bytes(xml, 'utf-8'), parser=parser)
    keys = set()
    for el in tree.iter():
        if el.get('Device') != device_id:
            continue
        key = el.get('Key')
        if not key:
            continue
        # Same normalisation as the parser: digital press on analogue input
        if key.startswith('Neg_'):
            key = key[4:]
        elif key.startswith('Pos_'):
            key = key[4:]
        keys.add(key)
    return sorted(keys)


def _cluster_buttons(numbers):
    """Split sorted button numbers into consecutive runs, capped per box."""
    runs, current = [], []
    for n in numbers:
        if current and n != current[-1] + 1:
            runs.append(current)
            current = []
        current.append(n)
    if current:
        runs.append(current)
    # Cap run length so a long consecutive range doesn't make one giant box
    capped = []
    for run in runs:
        for i in range(0, len(run), _MAX_ROWS_PER_BOX):
            capped.append(run[i:i + _MAX_ROWS_PER_BOX])
    return capped


def group_keys(keys):
    """Group raw Key values into draft boxes (label + rows, no positions)."""
    povs = {}            # 'POV1' -> {'Up': key, ...}
    buttons = []         # ints
    axes = []            # 'X', 'RZ', ...
    others = []
    for key in keys:
        m = _POV_RE.match(key)
        if m:
            povs.setdefault(m.group(1), {})[m.group(2)] = key
            continue
        m = _BTN_RE.match(key)
        if m:
            buttons.append(int(m.group(1)))
            continue
        m = _AXIS_RE.match(key)
        if m and m.group(1):
            axes.append(m.group(1))
            continue
        others.append(key)

    boxes = []

    def add(label, rows):
        boxes.append({'label': label, 'rows': rows})

    # Buttons: consecutive runs become one box (physically adjacent more often
    # than not), default symbol 'press', number == Joy_N (VIRPIL convention).
    for run in _cluster_buttons(sorted(set(buttons))):
        label = f'BTN {run[0]}' if len(run) == 1 else f'BTN {run[0]}-{run[-1]}'
        add(label, [{'symbol': 'press', 'number': str(n), 'joy': f'Joy_{n}',
                     'type': 'Digital'} for n in run])

    # POV hats: fixed Up/Right/Down/Left order with direction symbols
    for pov in sorted(povs):
        rows = [{'symbol': d.lower(), 'number': None, 'joy': povs[pov][d],
                 'type': 'Digital'} for d in _POV_ORDER if d in povs[pov]]
        add(pov, rows)

    # Axes: X+Y merge into a STICK box, the rest get one box each
    axes = sorted(set(axes))
    stick = [a for a in ('X', 'Y') if a in axes]
    if stick:
        add('STICK', [{'symbol': None, 'number': a, 'joy': f'Joy_{a}Axis',
                       'type': 'Analogue'} for a in stick])
    for a in axes:
        if a in ('X', 'Y'):
            continue
        add(_AXIS_LABELS.get(a, f'AXIS {a}'),
            [{'symbol': None, 'number': a, 'joy': f'Joy_{a}Axis',
              'type': 'Analogue'}])

    # Anything unrecognised still gets a row so nothing silently drops
    for key in others:
        add(key, [{'symbol': None, 'number': None, 'joy': key,
                   'type': 'Digital'}])

    return boxes


def layout_boxes(boxes):
    """Assign provisional two-column positions on the nominal canvas."""
    col, y = 0, _TOP_Y
    for box in boxes:
        h = _BOX_PAD + _ROW_H * max(1, len(box['rows']))
        if y + h > NOMINAL_H - 100 and col == 0:
            col, y = 1, _TOP_Y
        box['box_xy'] = [_COL_X[min(col, 1)], y]
        box['box_wh'] = [_COL_W, h]
        box['button_xy'] = None
        y += h + _GAP
    return boxes


def scaffold_mapping_from_binds(xml, device_id, title=''):
    """Build a full draft mapping dict from a .binds XML for one device."""
    keys = extract_device_keys(xml, device_id)
    boxes = layout_boxes(group_keys(keys))
    return {
        'title': title or f'Controller {device_id}',
        'image': None,
        'device_ids': [device_id],
        'styling': 'Group',
        'width': NOMINAL_W,
        'height': NOMINAL_H,
        'boxes': boxes,
    }


def missing_keys(mapping, keys):
    """Return keys not covered by any row of the mapping (for enrichment)."""
    covered = set()
    for box in mapping.get('boxes', []):
        for row in box.get('rows', []):
            if row.get('joy'):
                covered.add(row['joy'])
    return [k for k in keys if k not in covered]
