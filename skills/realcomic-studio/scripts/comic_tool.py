#!/usr/bin/env python3
"""Legacy compatibility only: validate and assemble historical supplied panels.
NOT for new comic page production, panel stitching, lettering, ratio correction,
or integrated-page PDF delivery. Use native whole-page generation for new pages.
No image generation or network access.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import re
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError


class ComicError(Exception):
    pass


def fail(message):
    raise ComicError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        fail(message)


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def box(value, label, integer=True):
    require(isinstance(value, list) and len(value) == 4, f"{label}: box must have four values")
    require(all((type(v) is int if integer else number(v)) for v in value), f"{label}: invalid box values")
    x, y, w, h = value
    require(x >= 0 and y >= 0 and w > 0 and h > 0, f"{label}: box must have positive size and origin")
    return x, y, w, h


def overlap(a, b):
    return a[0] < b[0]+b[2] and b[0] < a[0]+a[2] and a[1] < b[1]+b[3] and b[1] < a[1]+a[3]


def rgb(value, label):
    require(isinstance(value, str) and len(value) == 7 and value.startswith('#'), f"{label}: expected #RRGGBB")
    try:
        return tuple(int(value[i:i+2], 16) for i in (1, 3, 5))
    except ValueError:
        fail(f"{label}: expected #RRGGBB")


def safe_name(value, label):
    require(isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', value) is not None,
            f'{label}: use only ASCII letters, digits, underscore and hyphen, starting with a letter or digit')
    require(value.upper() not in {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))},
            f'{label}: reserved filename')
    return value


def read_project(path, for_render=False):
    try:
        project = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        fail(f"Cannot read JSON: {exc}")
    require(isinstance(project, dict), 'Root must be an object')
    require(type(project.get('schema_version')) is int and project['schema_version'] == 1, 'schema_version must be integer 1')
    require(isinstance(project.get('title'), str) and project['title'].strip(), 'title is required')
    safe_name(project.get('chapter_id'), 'chapter_id')
    require(project.get('text_mode') in ('overlay', 'integrated'), 'invalid text_mode')
    require(project.get('reading_order') in ('ltr', 'rtl', 'vertical'), 'invalid reading_order')
    cast = project.get('cast')
    require(isinstance(cast, list), 'cast must be a list')
    cast_ids = set()
    for c in cast:
        require(isinstance(c, dict) and isinstance(c.get('id'), str) and c['id'].strip() and isinstance(c.get('name'), str) and c['name'].strip(), 'invalid cast member')
        require(c['id'] not in cast_ids and c['id'] != 'narrator', f"duplicate or reserved cast id: {c['id']}")
        cast_ids.add(c['id'])
    pages = project.get('pages')
    require(isinstance(pages, list) and pages, 'pages must be a nonempty list')
    page_ids, panel_ids, orders = set(), set(), []
    next_order = 1
    for page in pages:
        require(isinstance(page, dict), 'page must be an object')
        pid = page.get('id')
        safe_name(pid, 'page id')
        require(pid not in page_ids, f'duplicate page id: {pid}')
        page_ids.add(pid)
        pw, ph = page.get('width'), page.get('height')
        require(type(pw) is int and type(ph) is int and pw > 0 and ph > 0, f'{pid}: positive integer width and height required')
        rgb(page.get('background'), f'{pid} background')
        panels = page.get('panels')
        require(isinstance(panels, list) and panels, f'{pid}: panels must be nonempty')
        seen_boxes = []
        page_orders = []
        for panel in panels:
            require(isinstance(panel, dict), f'{pid}: panel must be an object')
            qid = panel.get('id')
            require(isinstance(qid, str) and qid.strip() and qid not in panel_ids, f'invalid or duplicate panel id: {qid}')
            panel_ids.add(qid)
            order = panel.get('order')
            require(type(order) is int and order > 0, f'{qid}: order must be positive integer')
            orders.append(order)
            page_orders.append(order)
            pbox = box(panel.get('box'), qid)
            require(pbox[0]+pbox[2] <= pw and pbox[1]+pbox[3] <= ph, f'{qid}: panel exceeds page')
            require(not any(overlap(pbox, prior) for prior in seen_boxes), f'{qid}: panel overlaps another panel')
            seen_boxes.append(pbox)
            image = panel.get('image')
            require(image is None or (isinstance(image, str) and image.strip() and not Path(image).is_absolute()), f'{qid}: image must be relative path or null')
            require(panel.get('status') in ('planned', 'generated', 'approved'), f'{qid}: invalid status')
            require(panel.get('fit') in ('contain', 'cover'), f'{qid}: invalid fit')
            bubbles = panel.get('bubbles')
            require(isinstance(bubbles, list), f'{qid}: bubbles must be a list')
            require(project['text_mode'] != 'integrated' or not bubbles, f'{qid}: integrated text_mode forbids bubbles')
            for n, bubble in enumerate(bubbles, 1):
                label = f'{qid} bubble {n}'
                require(isinstance(bubble, dict), f'{label}: must be an object')
                require(bubble.get('type') in ('speech', 'thought', 'caption', 'sfx'), f'{label}: invalid type')
                speaker = bubble.get('speaker')
                require(isinstance(speaker, str) and speaker in cast_ids | {'narrator'}, f'{label}: unknown speaker')
                require(isinstance(bubble.get('text'), str) and bubble['text'].strip(), f'{label}: text required')
                bx, by, bw, bh = box(bubble.get('box'), label, integer=False)
                require(bx+bw <= 1+1e-9 and by+bh <= 1+1e-9, f'{label}: bubble exceeds panel')
                if 'tail' in bubble:
                    t = bubble['tail']
                    require(isinstance(t, list) and len(t) == 2 and all(number(v) and 0 <= v <= 1 for v in t), f'{label}: tail must be [x,y] inside panel')
            if for_render:
                require(panel['status'] == 'approved' and image is not None, f'{qid}: render needs approved panel with image')
                source = (path.parent / image).resolve()
                require(source.is_file(), f'{qid}: image missing: {source}')
                try:
                    with Image.open(source) as im:
                        im.verify()
                except (OSError, ValueError, UnidentifiedImageError) as exc:
                    fail(f'{qid}: unreadable image: {exc}')
        require(sorted(page_orders) == list(range(next_order, next_order+len(page_orders))),
                f'{pid}: panel orders must follow page sequence starting at {next_order}')
        next_order += len(page_orders)
    require(sorted(orders) == list(range(1, len(orders)+1)), 'panel orders must be unique and continuous across chapter')
    return project


def font_path(explicit, chinese):
    if explicit:
        candidate = Path(explicit).expanduser()
        require(candidate.is_absolute(), '--font must be an absolute path')
        p = candidate.resolve()
        require(p.is_file() and p.suffix.lower() in ('.ttf', '.otf', '.ttc'), f'font missing or unsupported: {p}')
        try:
            ImageFont.truetype(str(p), 20)
        except OSError as exc:
            fail(f'font unreadable: {exc}')
        return str(p)
    options = [Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / n for n in ('msyh.ttc', 'msyh.ttf', 'simhei.ttf')]
    options += [Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'), Path('/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc')]
    for p in options:
        if p.is_file():
            return str(p)
    if chinese:
        fail('Chinese text needs a CJK font; pass --font with an absolute TTF/OTF/TTC path')
    return None


def wrap_lines(draw, text, font, max_width):
    lines = []
    for paragraph in text.split('\n'):
        line = ''
        for char in paragraph:
            proposal = line + char
            if line and draw.textlength(proposal, font=font) > max_width:
                if char in '，。！？；：、）》」』】,.!?;:)]}' and len(line) > 1:
                    lines.append(line[:-1])
                    line = line[-1] + char
                else:
                    lines.append(line)
                    line = char
            else:
                line = proposal
        lines.append(line)
    return lines


def draw_text(draw, bubble, bounds, face, min_size):
    x0, y0, x1, y1 = bounds
    width, height = x1-x0, y1-y0
    pad = max(4, min(width, height)//10)
    avail_w, avail_h = width-2*pad, height-2*pad
    require(avail_w > 0 and avail_h > 0, f"bubble too small: {bubble['text'][:20]}")
    max_size = min(96, max(min_size, int(height*.45)))
    for size in range(max_size, min_size-1, -1):
        font = ImageFont.truetype(face, size) if face else ImageFont.load_default(size=size)
        lines = wrap_lines(draw, bubble['text'], font, avail_w)
        ink_boxes = [draw.textbbox((0,0), line or ' ', font=font) for line in lines]
        line_h = max(math.ceil(size*1.28), *(b[3]-b[1] for b in ink_boxes))
        if all(b[2]-b[0] <= avail_w for b in ink_boxes) and len(lines)*line_h <= avail_h:
            top = y0+pad+(avail_h-len(lines)*line_h)//2
            for line, ink in zip(lines, ink_boxes):
                ink_w = ink[2]-ink[0]
                draw.text((x0+(width-ink_w)/2-ink[0], top-ink[1]), line, font=font, fill=(10, 10, 10), stroke_width=0)
                top += line_h
            return size
    fail(f"text overflows bubble even at {min_size}px: {bubble['text'][:40]}")


def bubble_draw(draw, bubble, panel_box, face, min_size):
    px, py, pw, ph = panel_box
    rx, ry, rw, rh = bubble['box']
    x0, y0 = px+round(rx*pw), py+round(ry*ph)
    x1, y1 = px+round((rx+rw)*pw), py+round((ry+rh)*ph)
    require(x1 > x0 and y1 > y0, 'bubble pixel dimensions must be positive')
    bounds = (x0, y0, x1-1, y1-1)
    kind = bubble['type']
    fill = {'speech': (255,255,255), 'thought': (252,252,252), 'caption': (255,244,205), 'sfx': (255,237,89)}[kind]
    stroke = max(2, min(pw,ph)//260)
    if 'tail' in bubble and kind in ('speech', 'thought'):
        tx, ty = bubble['tail']
        tip = (px+round(tx*pw), py+round(ty*ph))
        base_x = max(x0+8, min(x1-8, tip[0]))
        base_y = y1-2 if tip[1] >= y1 else y0+2 if tip[1] <= y0 else (y0+y1)//2
        if kind == 'speech':
            draw.polygon([(base_x-9,base_y), (base_x+9,base_y), tip], fill=fill, outline=(0,0,0), width=stroke)
        else:
            draw.ellipse((tip[0]-5,tip[1]-5,tip[0]+5,tip[1]+5), fill=fill, outline=(0,0,0), width=stroke)
            mid = ((base_x+tip[0])//2, (base_y+tip[1])//2)
            draw.ellipse((mid[0]-7,mid[1]-7,mid[0]+7,mid[1]+7), fill=fill, outline=(0,0,0), width=stroke)
    if kind == 'caption':
        draw.rectangle(bounds, fill=fill, outline=(0,0,0), width=stroke)
    elif kind == 'sfx':
        draw.rounded_rectangle(bounds, radius=max(2,min(x1-x0,y1-y0)//7), fill=fill, outline=(0,0,0), width=stroke)
    else:
        draw.rounded_rectangle(bounds, radius=max(3,min(x1-x0,y1-y0)//4), fill=fill, outline=(0,0,0), width=stroke)
    return draw_text(draw, bubble, (x0,y0,x1,y1), face, min_size)


def fit_image(im, size, mode):
    w, h = size
    scale = min(w/im.width, h/im.height) if mode == 'contain' else max(w/im.width, h/im.height)
    nw, nh = max(1,round(im.width*scale)), max(1,round(im.height*scale))
    resized = im.resize((nw,nh), Image.Resampling.LANCZOS)
    if mode == 'contain':
        tile = Image.new('RGB', size, 'white')
        tile.paste(resized, ((w-nw)//2,(h-nh)//2))
        return tile
    return resized.crop(((nw-w)//2,(nh-h)//2,(nw-w)//2+w,(nh-h)//2+h))


def render(project, json_path, face, min_font_px):
    images, page_records = [], []
    for page in project['pages']:
        canvas = Image.new('RGB', (page['width'],page['height']), rgb(page['background'], 'background'))
        d = ImageDraw.Draw(canvas)
        records = []
        page_min_font = min_font_px or max(12, math.ceil(page['width']*0.02))
        for panel in sorted(page['panels'], key=lambda p:p['order']):
            x,y,w,h = panel['box']
            source = (json_path.parent / panel['image']).resolve()
            raw = source.read_bytes()
            with Image.open(io.BytesIO(raw)) as im:
                raw_size = list(im.size)
                oriented = ImageOps.exif_transpose(im)
                oriented_size = list(oriented.size)
                rgba = oriented.convert('RGBA')
                flattened = Image.alpha_composite(Image.new('RGBA', rgba.size, 'white'), rgba).convert('RGB')
                tile = fit_image(flattened, (w,h), panel['fit'])
            canvas.paste(tile,(x,y))
            d.rectangle((x,y,x+w-1,y+h-1), outline=(0,0,0), width=max(2,min(w,h)//250))
            bubbles = []
            for bubble in panel['bubbles']:
                size = bubble_draw(d, bubble, (x,y,w,h), face, page_min_font)
                bubbles.append({**bubble, 'rendered_font_px':size})
            records.append({'id':panel['id'],'order':panel['order'],'box':panel['box'],'source_path':str(source),'source_sha256':digest(raw),'source_dimensions_raw':raw_size,'source_dimensions_oriented':oriented_size,'fit':panel['fit'],'fit_note':'center crop after EXIF orientation' if panel['fit']=='cover' else 'uncropped after EXIF orientation; white letterbox','bubbles':bubbles})
        images.append(canvas)
        page_records.append({'id':page['id'],'width':canvas.width,'height':canvas.height,'panels':records})
    return images, page_records


def export(args, project, source):
    chinese = any(any('\u3400' <= ch <= '\u9fff' for ch in b['text']) for p in project['pages'] for q in p['panels'] for b in q['bubbles'])
    face = font_path(args.font, chinese)
    out = Path(args.out_dir).expanduser().resolve()
    require(args.dpi > 0, '--dpi must be positive')
    require(args.min_font_px is None or args.min_font_px >= 12, '--min-font-px must be at least 12')
    prefix = args.prefix or project['chapter_id']
    safe_name(prefix, 'output prefix')
    png_names = [f'{prefix}_{p["id"]}.png' for p in project['pages']]
    names = png_names + [f'{prefix}.pdf',f'{prefix}_manifest.json']
    require(all((out/n).resolve().parent == out for n in names), 'output target escapes --out-dir')
    protected = {source.resolve()}
    if face: protected.add(Path(face).resolve())
    protected.update((source.parent / q['image']).resolve() for p in project['pages'] for q in p['panels'])
    require(not any((out/n).resolve() in protected for n in names), 'output would overwrite an input file')
    require(not any((out/n).exists() for n in names), 'output already exists; choose a new --out-dir or --prefix')
    pages, records = render(project, source, face, args.min_font_px)
    payloads = {}
    for name, im in zip(png_names, pages):
        stream=io.BytesIO(); im.save(stream, format='PNG'); payloads[name]=stream.getvalue()
    stream=io.BytesIO(); pages[0].save(stream, format='PDF', save_all=True, append_images=pages[1:], resolution=args.dpi)
    pdf_name=f'{prefix}.pdf'; payloads[pdf_name]=stream.getvalue()
    manifest={'schema_version':1,'title':project['title'],'chapter_id':project['chapter_id'],'text_mode':project['text_mode'],'reading_order':project['reading_order'],'source_json':str(source),'source_json_sha256':digest(source.read_bytes()),'font':face,'min_font_px':args.min_font_px,'pdf_type':'raster','pdf_dpi':args.dpi,'pages':records,'exports':[{ 'file':name,'sha256':digest(data),'bytes':len(data)} for name,data in payloads.items()]}
    payloads[f'{prefix}_manifest.json']=json.dumps(manifest,ensure_ascii=False,indent=2).encode('utf-8')
    out.mkdir(parents=True,exist_ok=True)
    staged=[]; completed=[]
    try:
        for name,data in payloads.items():
            fd,tmp=tempfile.mkstemp(prefix='.comic-stage-',dir=out)
            staged.append(Path(tmp))
            with os.fdopen(fd,'wb') as f: f.write(data)
        for tmp,name in zip(staged,payloads):
            target=out/name
            require(not target.exists(), f'output appeared during render: {target}')
            tmp.rename(target); completed.append(target)
    except Exception:
        for p in staged+completed:
            p.unlink(missing_ok=True)
        raise
    return [str(out/n) for n in payloads]


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    sub=ap.add_subparsers(dest='command',required=True)
    for cmd in ('check','render'):
        sp=sub.add_parser(cmd)
        sp.add_argument('json',type=Path)
        if cmd=='render':
            sp.add_argument('--out-dir',type=Path,required=True)
            sp.add_argument('--prefix')
            sp.add_argument('--font',help='absolute TTF/OTF/TTC path')
            sp.add_argument('--min-font-px',type=int,help='minimum text size; default max(12, ceil(page width * 0.02))')
            sp.add_argument('--dpi',type=int,default=150)
    args=ap.parse_args()
    source=args.json.expanduser().resolve()
    try:
        project=read_project(source,args.command=='render')
        if args.command=='check':
            print(f'CHECK_OK: {len(project["pages"])} pages, {sum(len(p["panels"]) for p in project["pages"])} panels')
        else:
            for target in export(args,project,source): print(target)
    except (ComicError, OSError, ValueError) as exc:
        print(f'ERROR: {exc}',file=sys.stderr)
        return 1
    return 0


if __name__=='__main__':
    sys.exit(main())

