#!/usr/bin/env python3
"""Genera una mini página por producto (p/CODIGO/index.html) con la foto, el nombre
y el precio del producto, para que WhatsApp, Facebook e Instagram muestren la vista
previa del producto al compartir su link. Cada página lleva al cliente al catálogo
con el producto abierto (/#CODIGO).

Uso: python3 scripts/fichas.py SALIDA [catalogo.json]
Sin catalogo.json, lee el catálogo publicado en Supabase (tabla catalog_public).
"""
import concurrent.futures
import hashlib
import html
import json
import os
import re
import shutil
import sys
import urllib.request

SITE = os.environ.get('SITE_URL', 'https://tienda.casatintin.cl').rstrip('/')
SUPA_URL = os.environ.get('SUPA_URL', 'https://sjaxdbeanubmrhjhyimz.supabase.co').rstrip('/')
SUPA_KEY = os.environ.get('SUPA_KEY', 'sb_publishable_cRbF9op8L389hDd7SI4bgQ_Ah09EC4W')
REPO_FILES = ['index.html', 'preview.jpg', '404.html', 'CNAME']


def slug(code):
    return re.sub(r'[^A-Za-z0-9_-]', '', str(code or ''))


def money(n):
    return '$' + f'{round(float(n or 0)):,}'.replace(',', '.')


def fetch_catalog():
    req = urllib.request.Request(
        f'{SUPA_URL}/rest/v1/catalog_public?id=eq.current&select=data',
        headers={'apikey': SUPA_KEY, 'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=60) as r:
        rows = json.load(r)
    data = rows[0]['data'] if rows else None
    if not data or not isinstance(data.get('products'), list):
        raise SystemExit('El catálogo publicado no tiene productos; no se genera nada.')
    return data


def url_ok(u):
    if not u.startswith('https://'):
        return False
    try:
        req = urllib.request.Request(u, method='HEAD')
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status == 200 and r.headers.get('Content-Type', '').startswith('image/')
    except Exception:
        return False


def candidates(p):
    """Fotos posibles en orden de preferencia. La miniatura (480 px, liviana) va primero
    porque WhatsApp no muestra fotos muy pesadas; si no existe, la foto completa."""
    out = []
    groups = [p] + list(p.get('variants') or [])
    for g in groups:
        th, im = list(g.get('th') or []), list(g.get('imgs') or [])
        if th:
            out.append(th[0])
        if im:
            out.append(im[0])
        if out:
            break
    return [u for u in out if isinstance(u, str) and u.startswith('https://')]


def pick_image(p):
    for u in candidates(p):
        if url_ok(u):
            return u
    return f'{SITE}/preview.jpg'


def price_of(p):
    vs = p.get('variants') or []
    if vs:
        return min(float(v.get('price') or 0) for v in vs), True
    return float(p.get('price') or 0), False


def describe(p, store):
    price, is_var = price_of(p)
    parts = [('Desde ' if is_var else '') + money(price) + ' IVA incluido']
    out = all(v.get('out') for v in p['variants']) if p.get('variants') else p.get('out')
    if p.get('od'):
        parts.append(f"Por encargo, entrega {p.get('lead') or '3-5'} días hábiles")
    elif out:
        parts.append('Agotado por ahora, consulta por reposición')
    parts.append('Paga con transferencia o tarjeta')
    text = ' · '.join(parts) + '.'
    d = re.sub(r'\s+', ' ', p.get('desc') or '').strip()
    if d:
        text += ' ' + (d[:150].rsplit(' ', 1)[0] + '…' if len(d) > 150 else d)
    return text


PAGE = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="{url}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="{store}">
<meta property="og:locale" content="es_CL">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{img}">
<meta property="og:image:secure_url" content="{img}">
<meta property="og:image:alt" content="{name}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{title}">
<meta name="twitter:description" content="{desc}">
<meta name="twitter:image" content="{img}">
<meta name="robots" content="noindex, follow">
<script>location.replace('/#' + encodeURIComponent({code_js}));</script>
<style>body{{margin:0;min-height:100vh;display:grid;place-items:center;font:16px/1.5 system-ui,sans-serif;background:#F6F1EA;color:#2E241E;text-align:center;padding:24px}}img{{width:180px;height:180px;object-fit:cover;border-radius:16px;margin:0 auto 12px;display:block}}a{{color:inherit;font-weight:600}}</style>
</head>
<body>
<main><img src="{img}" alt=""><p>Abriendo <a href="/#{code_href}">{name}</a> en el catálogo de {store}…</p></main>
</body>
</html>
"""


def build(out_dir, data):
    store = (data.get('storeName') or 'Casa Tintin').strip()
    prods = [p for p in data['products'] if slug(p.get('code'))]
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
        imgs = list(ex.map(pick_image, prods))
    seen = set()
    for p, img in zip(prods, imgs):
        s = slug(p['code'])
        if s in seen:
            continue
        seen.add(s)
        name = (p.get('name') or s).strip()
        price, is_var = price_of(p)
        title = f"{name} · {'Desde ' if is_var else ''}{money(price)}" if price > 0 else name
        e = lambda x: html.escape(x, quote=True)
        page = PAGE.format(
            title=e(title), desc=e(describe(p, store)), url=e(f'{SITE}/p/{s}/'), img=e(img),
            name=e(name), store=e(store), code_js=json.dumps(str(p['code'])).replace('<', '\\u003c'),
            code_href=e(urllib.request.quote(str(p['code']), safe='')))
        d = os.path.join(out_dir, 'p', s)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, 'index.html'), 'w', encoding='utf-8') as f:
            f.write(page)
    # Huella del contenido: el robot la compara con la publicada para no republicar si nada cambió
    h = hashlib.sha256()
    for root, _, files in sorted(os.walk(out_dir)):
        for fn in sorted(files):
            with open(os.path.join(root, fn), 'rb') as f:
                h.update(fn.encode() + f.read())
    with open(os.path.join(out_dir, 'p', 'version.txt'), 'w') as f:
        f.write(h.hexdigest())
    return len(seen)


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    out = sys.argv[1]
    data = json.load(open(sys.argv[2], encoding='utf-8')) if len(sys.argv) > 2 else fetch_catalog()
    if os.path.exists(out):
        shutil.rmtree(out)
    os.makedirs(out)
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for fn in REPO_FILES:
        src = os.path.join(here, fn)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(out, fn))
    n = build(out, data)
    print(f'{n} fichas de producto generadas en {out}/p/')


if __name__ == '__main__':
    main()
