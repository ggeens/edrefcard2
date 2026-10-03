"""Import a manufacturer AcroForm reference sheet (VIRPIL-style) as a mapping.

VIRPIL (and similar) fillable PDFs are semantically structured:
  - the page artwork (photo + callout boxes + leader lines) is page CONTENT,
  - the fillable fields are annotations laid over it, one family per physical
    input: BTN<n>, HAT<n>_{U,R,D,L,P}, SWT<n>_S<k>, AXS1D<n>, AXS2D<n>_{H,V},
  - each family has _Name (the Joy number / axis letter), _Desc (the writing
    area = our box, with its exact position) and optional _Min/_Max/_Mid.

So one import gives us: a clean rendered background (annotations excluded,
keeping the manufacturer's own boxes and leader lines) plus every box already
positioned. Imported boxes carry no_chrome=True so the engine only writes the
binding text inside the manufacturer's artwork instead of redrawing frames.
"""

import io
import re

import fitz  # PyMuPDF
from PIL import Image

# Axis letters as printed on the sheets -> Elite DirectInput key names
_AXIS_JOY = {
    'X': 'Joy_XAxis', 'Y': 'Joy_YAxis', 'Z': 'Joy_ZAxis',
    'RX': 'Joy_RXAxis', 'RY': 'Joy_RYAxis', 'RZ': 'Joy_RZAxis',
    'SLDR': 'Joy_UAxis', 'SLIDER': 'Joy_UAxis',
    'DIAL': 'Joy_VAxis',
}

_DIR_SYMBOL = {'U': 'up', 'R': 'right', 'D': 'down', 'L': 'left', 'P': 'press'}

_ROLE_RE = re.compile(r'_(Name|Desc|Min|Max|Mid)$')


def _vkb_boxes(page, zoom):
    """Read VKB/UntoldForce blank worksheets, not hardware input numbers.

    A/B and 1/2 pairs are number/description columns. Field suffixes are
    authoring identifiers, NOT DirectInput numbers or reliable directions.
    Keep each writing area in its original position and retain provenance.
    """
    text = page.get_text()
    if 'VKB STECS' not in text or 'UntoldForce' not in text:
        return [], None
    widgets = {w.field_name: w for w in page.widgets() or []}
    entries = []
    for name, widget in widgets.items():
        if name.upper().startswith('USER'):
            continue
        axis = name.upper().startswith('AX_')
        pair = None
        if name.endswith('_B'):
            pair = widgets.get(name[:-2] + '_A')
        elif name.endswith('_2'):
            pair = widgets.get(name[:-2] + '_1')
        if not axis and pair is None:
            continue
        if pair is not None:
            # Fail closed if a different PDF uses this naming convention.
            if (pair.rect.x1 > widget.rect.x0 + 2 or
                    abs(pair.rect.y0 - widget.rect.y0) > 2 or
                    widget.rect.width <= pair.rect.width):
                raise ValueError(f'Unexpected VKB field geometry: {name}')
        family = re.sub(r'_[AB12]$', '', name) if not axis else name
        group = re.sub(r'_(?:\d+|UP|DN|BUT|NEU|CW|CCW|PUSH|Up|Down|Left|Right|Push|A|B)$', '', family)
        if axis:
            group = 'Axes'
        r = widget.rect
        entries.append((group, r.y0, r.x0, {
            'label': family.replace('_', ' ') + ' [VERIFY]',
            'physical_group': group,
            'box_xy': [int(r.x0 * zoom), int(r.y0 * zoom)],
            'box_wh': [max(1, int(r.width * zoom)), max(1, int(r.height * zoom))],
            'button_xy': None,
            'no_chrome': True,
            'rows': [{'symbol': None, 'number': None, 'joy': '',
                      'type': 'Analogue' if axis else 'Digital',
                      'verification': 'unverified', 'source_field': name}],
        }))
    entries.sort(key=lambda item: (item[0], item[1], item[2]))
    grouped = []
    for group in sorted({entry[0] for entry in entries}):
        members = [entry for entry in entries if entry[0] == group]
        members.sort(key=lambda item: (item[1], item[2]))
        left = min(item[3]['box_xy'][0] for item in members)
        top = min(item[3]['box_xy'][1] for item in members)
        right = max(item[3]['box_xy'][0] + item[3]['box_wh'][0] for item in members)
        bottom = max(item[3]['box_xy'][1] + item[3]['box_wh'][1] for item in members)
        rows = []
        for row_number, (_, _, _, member) in enumerate(members, 1):
            row = dict(member['rows'][0])
            row['source_row'] = row_number
            rows.append(row)
        grouped.append({
            'label': f'{group} [VERIFY]',
            'physical_group': group,
            'box_xy': [left, top],
            'box_wh': [right - left, bottom - top],
            'button_xy': None,
            'no_chrome': True,
            'rows': rows,
        })
    title = next((line.strip() for line in text.splitlines() if line.startswith('VKB STECS')), 'VKB STECS')
    return grouped, title


def _family_boxes(page):
    """Group the page's widgets into {family: {role: widget}} dicts."""
    fams = {}
    for w in page.widgets() or []:
        name = w.field_name or ''
        m = _ROLE_RE.search(name)
        fam, role = (name[:m.start()], m.group(1)) if m else (name, 'Self')
        fams.setdefault(fam, {})[role] = w
    return fams


def _row_for(family, name_value):
    """Build the mapping row (symbol/number/joy/type) for one field family."""
    val = (name_value or '').strip()
    # Axis families (AXS...): _Name holds the axis letter
    if family.upper().startswith('AXS'):
        joy = _AXIS_JOY.get(val.upper().replace(' ', ''), '')
        return {'symbol': None, 'number': val or None, 'joy': joy,
                'type': 'Analogue'}
    # Button-like families: _Name holds the Joy_N number; the suffix of the
    # family name carries the hat direction (HAT6_U) or switch position.
    symbol = 'press'
    m = re.search(r'_([URDLP])$', family)
    if m:
        symbol = _DIR_SYMBOL[m.group(1)]
    number = val if val else None
    joy = f'Joy_{val}' if val.isdigit() else ''
    return {'symbol': symbol, 'number': number, 'joy': joy, 'type': 'Digital'}


def _label_for(family, row):
    """Editor-panel label (headers are not drawn for no_chrome boxes)."""
    label = family.replace('_', ' ')
    if row['type'] == 'Analogue' and row.get('number'):
        label = f"AXIS {row['number']}"
    return label


def extract_mapping_from_pdf(pdf_bytes, zoom=1.0):
    """Convert an AcroForm reference sheet into (mapping_dict, jpeg_bytes).

    The mapping has one no_chrome box per fillable _Desc area, positioned on
    the manufacturer's own artwork; the JPEG is the page rendered WITHOUT
    annotations (empty boxes, ready to be written into by the engine).
    """
    doc = fitz.open(stream=pdf_bytes, filetype='pdf')
    if doc.page_count < 1:
        raise ValueError('Empty PDF')
    # Pick the page with the most widgets (sheets are usually single-page)
    page = max(doc, key=lambda p: len(list(p.widgets() or [])))
    fams = _family_boxes(page)

    boxes = []
    for family, roles in sorted(fams.items()):
        desc = roles.get('Desc')
        if desc is None:
            continue  # ProfileName, Mid markers, decorations...
        name_w = roles.get('Name')
        row = _row_for(family, name_w.field_value if name_w else '')
        # The manufacturer number/letter is already printed in the artwork
        # badge next to the writing area, so the engine must not repeat it.
        row['number'] = None
        r = desc.rect
        boxes.append({
            'label': _label_for(family, row),
            'box_xy': [int(r.x0 * zoom), int(r.y0 * zoom)],
            'box_wh': [int(r.width * zoom), int(r.height * zoom)],
            'button_xy': None,
            'no_chrome': True,
            'rows': [row],
        })
    vkb_title = None
    if not boxes:
        boxes, vkb_title = _vkb_boxes(page, zoom)
    if vkb_title and zoom == 1.0:
        # Small PDF point dimensions leave no usable room after renderer padding.
        # Rasterize these worksheets at 216 DPI, preserving relative geometry.
        doc.close()
        return extract_mapping_from_pdf(pdf_bytes, zoom=3.0)
    if not boxes:
        raise ValueError('No fillable description fields found in this PDF '
                         '(is it an AcroForm reference sheet?)')

    # Render the page WITH annotations so the manufacturer numbers (the _Name
    # values printed in the artwork badges) stay visible, but delete the
    # standalone placeholder fields first (e.g. 'Profile ... by ...'): value
    # blanking alone does not always refresh the appearance stream.
    for family, roles in fams.items():
        w = roles.get('Self')
        if w is not None and (w.field_value or '').strip():
            try:
                page.delete_widget(w)
            except Exception:
                pass
    # VKB number fields are blank by design. Do not bake user-entered actions
    # or guessed numbers into a reusable background. Printed credits remain.
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), annots=not bool(vkb_title))
    img = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=92)

    mapping = {
        'title': vkb_title or '',
        'image': None,           # set by the caller after saving the JPEG
        'device_ids': [],
        'styling': 'Group',
        'width': pix.width,
        'height': pix.height,
        'boxes': boxes,
    }
    if vkb_title:
        mapping['input_verification_required'] = True
        mapping['source_credit'] = 'Design by UntoldForce v1.0; distributed by VKB'
        mapping['import_format'] = 'vkb-stecs-worksheet'
        mapping['review_note'] = ('Physical positions imported; all game input codes require owner verification. '
                                  'Field names and row numbers are not Joy numbers.')
    doc.close()
    return mapping, buf.getvalue()
