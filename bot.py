"""Avisa por Telegram cuando hay stock a PVP de Pokémon Celebración 30.º Aniversario en tiendas de España."""
import argparse
import html
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
UA = "Mozilla/5.0 (compatible; stock-check-personal/0.1)"
RE_COLECCION = re.compile(
    r"\b30\s*[.\-]?\s*(o|th)?\s*(aniversario|anniversary|celebration|celebracion)"
    r"|celebracion\s+(del\s+)?30"
)
RE_RESERVA = re.compile(r"reserva|pre.?order")


def normalizar(texto):
    t = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in t if not unicodedata.combining(c)).lower()


def es_coleccion(titulo):
    return bool(RE_COLECCION.search(normalizar(titulo)))


def clasificar(titulo, cfg):
    """Devuelve (regla, tope) o None si no es un producto sellado con PVP en la tabla."""
    t = normalizar(titulo)
    if any(x in t for x in cfg["excluir"]):
        return None
    for regla in cfg["reglas"]:
        if re.search(regla["patron"], t):
            return regla, round(regla["pvp"] * (1 + cfg["margen"]), 2)
    return None


def http_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "es-ES,es;q=0.9"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read().decode("utf-8", "replace")


def leer_shopify(tienda, cfg, get=http_get):
    base = tienda["base"].rstrip("/")
    ruta = f"/collections/{tienda['coleccion']}/products.json" if tienda.get("coleccion") else "/products.json"
    items = []
    for pagina in range(1, cfg["max_paginas"] + 1):
        productos = json.loads(get(f"{base}{ruta}?limit=250&page={pagina}"))["products"]
        if not productos:
            break
        for p in productos:
            contexto = normalizar(f"{p['title']} {p.get('vendor')} {p.get('product_type')} {p.get('tags')}")
            if not es_coleccion(p["title"]) or (not tienda.get("coleccion") and "pok" not in contexto):
                continue
            for v in p["variants"]:
                sufijo = "" if v.get("title") in (None, "Default Title") else f" ({v['title']})"
                items.append({
                    "id": f"{tienda['nombre']}|{v['id']}",
                    "tienda": tienda["nombre"],
                    "titulo": p["title"] + sufijo,
                    "precio": float(v["price"]),
                    "disponible": bool(v.get("available")),
                    "stock_seguro": True,
                    "url": f"{base}/products/{p['handle']}",
                })
        if len(productos) < 250:
            break
        time.sleep(cfg["pausa_segundos"])
    return items


def _productos_ld(obj, salida):
    if isinstance(obj, dict):
        if obj.get("@type") == "Product":
            salida.append(obj)
        for v in obj.values():
            _productos_ld(v, salida)
    elif isinstance(obj, list):
        for v in obj:
            _productos_ld(v, salida)


def leer_ldjson(tienda, cfg, get=http_get):
    """Lee los datos estructurados schema.org de una página de búsqueda."""
    pagina = get(tienda["url"])
    productos = []
    for bloque in re.findall(r"<script[^>]*application/ld\+json[^>]*>(.*?)</script>", pagina, re.S):
        try:
            _productos_ld(json.loads(bloque), productos)
        except ValueError:
            continue
    items = []
    for p in productos:
        nombre = html.unescape(str(p.get("name", "")))
        if not es_coleccion(nombre) or "pok" not in normalizar(nombre):
            continue
        oferta = p.get("offers") or {}
        oferta = (oferta[0] if oferta else {}) if isinstance(oferta, list) else oferta
        estado = str(oferta.get("availability") or "")
        precio = oferta.get("price") or oferta.get("lowPrice")
        if precio is None:
            continue
        url = str(p.get("url") or tienda["url"])
        items.append({
            "id": f"{tienda['nombre']}|{url}",
            "tienda": tienda["nombre"],
            "titulo": nombre,
            "precio": float(precio),
            "disponible": not estado or estado.endswith("InStock") or estado.endswith("PreOrder"),
            "stock_seguro": bool(estado),
            "url": url,
        })
    return items


def leer_fichas(tienda, cfg, get=http_get):
    """Lee fichas directas de producto con los patrones de precio y stock definidos en la tienda."""
    items = []
    for i, url in enumerate(tienda["urls"]):
        if i:
            time.sleep(cfg["pausa_segundos"])
        pagina = get(url)
        nombre = re.search(tienda["patron_nombre"], pagina)
        precio = re.search(tienda["patron_precio"], pagina)
        stock = re.search(tienda["patron_stock"], pagina)
        if not (nombre and precio and stock):  # si cambia la web, debe contar como fallo y no como agotado
            raise ValueError(f"ficha no reconocida: {url}")
        items.append({
            "id": f"{tienda['nombre']}|{url}",
            "tienda": tienda["nombre"],
            "titulo": html.unescape(nombre.group(1)),
            "precio": float(precio.group(1)),
            "disponible": stock.group(1) == tienda["valor_en_stock"],
            "stock_seguro": True,
            "url": url,
        })
    return items


def filtrar(items, cfg):
    """Se queda con lo disponible, conocido y a PVP (con margen)."""
    salida = {}
    for it in items:
        c = clasificar(it["titulo"], cfg)
        if not it["disponible"] or c is None or it["precio"] > c[1]:
            continue
        regla, tope = c
        salida[it["id"]] = {**it, "producto": regla["producto"], "tope": tope,
                            "reserva": bool(RE_RESERVA.search(normalizar(it["titulo"])))}
    return salida


def texto_aviso(it):
    e = html.escape
    cabecera = "🕓 RESERVA disponible" if it["reserva"] else "🟢 STOCK disponible"
    lineas = [f"<b>{cabecera}</b>", e(it["titulo"]),
              f"💶 {it['precio']:.2f} € (tope {it['tope']:.2f} €)", f"🏬 {e(it['tienda'])}"]
    if not it["stock_seguro"]:
        lineas.append("⚠️ Esta tienda no publica el stock: compruébalo en la ficha")
    lineas.append(f'<a href="{e(it["url"], quote=True)}">Abrir producto</a>')
    return "\n".join(lineas)


def enviar_telegram(texto, token, chat_id):
    datos = urllib.parse.urlencode({"chat_id": chat_id, "text": texto, "parse_mode": "HTML"}).encode()
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for intento in range(2):
        try:
            with urllib.request.urlopen(url, data=datos, timeout=20):
                return True
        except urllib.error.HTTPError as e:
            if e.code == 429 and intento == 0:
                time.sleep(int(e.headers.get("Retry-After", "5")) + 1)
                continue
            print(f"Telegram rechazó el envío: HTTP {e.code}", file=sys.stderr)
            return False
        except urllib.error.URLError as e:
            print(f"Telegram no responde: {e.reason}", file=sys.stderr)
            return False
    return False


def procesar(estado, elegibles, tiendas_ok, enviar):
    """Avisa de lo que entra en stock. Lo que sale se olvida, para volver a avisar si regresa."""
    activos = estado.setdefault("activos", {})
    for clave, it in elegibles.items():
        if clave not in activos and enviar(texto_aviso(it)):
            activos[clave] = it["precio"]
    for clave in list(activos):
        if clave not in elegibles and clave.split("|", 1)[0] in tiendas_ok:
            del activos[clave]


def vigilar_fallos(estado, tienda, error, cfg, enviar):
    """Avisa una sola vez si una tienda deja de leerse: un bot mudo no debe parecer sin stock."""
    fallos = estado.setdefault("fallos", {})
    if error is None:
        fallos.pop(tienda, None)
        return
    fallos[tienda] = fallos.get(tienda, 0) + 1
    if fallos[tienda] == cfg["fallos_para_avisar"]:
        enviar(f"⚠️ No consigo leer {html.escape(tienda)} desde hace {fallos[tienda]} pasadas ({html.escape(error)}). "
               "Mientras dure, esa tienda no está vigilada.")


def ejecutar(cfg, estado, enviar, lectores=None):
    lectores = lectores or {"shopify": leer_shopify, "ldjson": leer_ldjson, "fichas": leer_fichas}
    elegibles, tiendas_ok = {}, set()
    for i, tienda in enumerate(t for t in cfg["tiendas"] if not t.get("pausada")):
        if i:
            time.sleep(cfg["pausa_segundos"])
        nombre, error = tienda["nombre"], None
        try:
            items = lectores[tienda.get("tipo", "shopify")](tienda, cfg)
            if not items and not tienda.get("puede_vacio"):
                error = "sin productos de la colección"
        except Exception as e:  # una tienda caída no debe parar a las demás
            items, error = [], f"{type(e).__name__}: {e}"[:120]
        print(f"{nombre}: {len(items)} productos" + (f" [FALLO: {error}]" if error else ""))
        vigilar_fallos(estado, nombre, error, cfg, enviar)
        if error is None:
            tiendas_ok.add(nombre)
            elegibles.update(filtrar(items, cfg))
    procesar(estado, elegibles, tiendas_ok, enviar)
    ejecutar_canales(cfg, estado, enviar)
    return elegibles


def leer_canal(canal, get=http_get):
    """Devuelve [(id, texto)] de la vista pública de un canal de Telegram, del más antiguo al más nuevo."""
    pagina = get(f"https://t.me/s/{canal}")
    posts = []
    for bloque in pagina.split('data-post="')[1:]:
        ident = re.match(rf"{re.escape(canal)}/(\d+)\"", bloque, re.I)
        texto = re.search(r'tgme_widget_message_text[^>]*>(.*?)</div>', bloque, re.S)
        if ident and texto:
            limpio = re.sub(r"<br\s*/?>", "\n", texto.group(1))
            limpio = html.unescape(re.sub(r"<[^>]+>", " ", limpio))
            posts.append((int(ident.group(1)), re.sub(r"[ \t]+", " ", limpio).strip()))
    if "tgme_channel_info" not in pagina and "tgme_widget_message" not in pagina:
        raise ValueError("canal no reconocido")
    return sorted(posts)


RE_AVISO = re.compile(
    r"(RESTOCK|NEW)\s*·\s*(?P<serie>[^·\n]+?)\s*·\s*(?P<tipo>[^\[\n]+?)\s*\[(?P<idioma>\w+)\]\s*\n"
    r"\s*(?P<tienda>[^\n]+?)\s*—\s*(?P<precio>[\d.,]+)\s*EUR\s*\n\s*(?P<titulo>[^\n]+)"
)


def textos_canal(canal, ident, texto, cfg):
    """Mensajes a reenviar: con formato tienda-precio aplica colección y PVP; si no, filtra por el texto."""
    enlace = f"https://t.me/{canal}/{ident}"
    cabecera = f"📣 <b>Aviso en @{html.escape(canal)}</b>"
    avisos = list(RE_AVISO.finditer(texto))
    if not avisos:
        return [f"{cabecera} (precio y stock sin comprobar)\n{html.escape(texto[:900])}\n{enlace}"] if es_coleccion(texto) else []
    salida = []
    for a in avisos:
        if not es_coleccion(f"{a['serie']} {a['titulo']}"):
            continue
        precio = float(a["precio"].replace(",", "."))
        clase = clasificar(f"{a['tipo']} {a['titulo']}", cfg)
        if clase and precio > clase[1]:
            continue
        tope = f"tope {clase[1]:.2f} €" if clase else "sin PVP en la tabla"
        salida.append(f"{cabecera}\n{html.escape(a['titulo'])} [{html.escape(a['idioma'])}]\n"
                      f"💶 {precio:.2f} € ({tope})\n🏬 {html.escape(a['tienda'])}\n{enlace}")
    return salida


def procesar_canal(estado, canal, posts, enviar, cfg):
    """Reenvía los mensajes nuevos que hablen de la colección. La primera vez solo marca el punto de partida."""
    vistos = estado.setdefault("canales", {})
    ultimo = vistos.get(canal)
    if ultimo is None:
        if posts:
            vistos[canal] = posts[-1][0]
        return
    for ident, texto in posts:
        if ident <= ultimo:
            continue
        if not all(enviar(t) for t in textos_canal(canal, ident, texto, cfg)):
            return  # se reintenta en la siguiente pasada
        vistos[canal] = ident


def ejecutar_canales(cfg, estado, enviar, lector=leer_canal):
    for canal in cfg.get("canales", []):
        error = None
        try:
            posts = lector(canal)
            print(f"@{canal}: {len(posts)} mensajes")
            procesar_canal(estado, canal, posts, enviar, cfg)
        except Exception as e:  # un canal caído no debe parar el resto
            error = f"{type(e).__name__}: {e}"[:120]
            print(f"@{canal}: [FALLO: {error}]")
        vigilar_fallos(estado, f"@{canal}", error, cfg, enviar)


def mostrar_chat_id(token):
    datos = json.loads(http_get(f"https://api.telegram.org/bot{token}/getUpdates"))
    ids = {u["message"]["chat"]["id"] for u in datos.get("result", []) if "message" in u}
    print(ids or "Escribe /start a tu bot en Telegram y repite este comando.")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="enseña lo que avisaría; no envía ni guarda nada")
    ap.add_argument("--chat-id", action="store_true", help="muestra tu chat id")
    args = ap.parse_args()
    token, chat_id = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if args.chat_id:
        return mostrar_chat_id(token)
    cfg = json.loads((RAIZ / "config.json").read_text(encoding="utf-8"))
    ruta = RAIZ / "state.json"
    estado = json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else {}
    if args.dry_run:
        ejecutar(cfg, estado, lambda t: print("\n" + t + "\n") or False)
        return
    if not token or not chat_id:
        sys.exit("Faltan TELEGRAM_TOKEN o TELEGRAM_CHAT_ID")
    estado["latido"] = time.strftime("%Y-%m")  # un commit al mes mantiene activa la tarea de GitHub
    ejecutar(cfg, estado, lambda t: enviar_telegram(t, token, chat_id))
    tmp = ruta.with_suffix(".tmp")
    tmp.write_text(json.dumps(estado, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(ruta)


if __name__ == "__main__":
    main()
