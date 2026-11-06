import json
import unittest
from pathlib import Path

import bot

CFG = json.loads((Path(__file__).parent / "config.json").read_text(encoding="utf-8"))
CFG = {**CFG, "pausa_segundos": 0}


def item(tienda="T", id_="1", titulo="ETB Celebración 30 Aniversario - Español", precio=60.0, disp=True):
    return {"id": f"{tienda}|{id_}", "tienda": tienda, "titulo": titulo, "precio": precio,
            "disponible": disp, "stock_seguro": True, "url": "https://x/p"}


class Filtro(unittest.TestCase):
    def test_coleccion_cualquier_idioma(self):
        for t in ["Lata 30.º Aniversario", "30th Celebration Mini Tin", "Caja 30th Anniversary Celebration M6a - Coreano",
                  "Celebración 30 Aniversario ETB"]:
            self.assertTrue(bot.es_coleccion(t), t)
        for t in ["Álbum 30 hojas", "Celebrations Elite Trainer Box"]:
            self.assertFalse(bot.es_coleccion(t), t)

    def test_pvp(self):
        self.assertEqual(len(bot.filtrar([item(precio=68.9)], CFG)), 1)
        self.assertEqual(len(bot.filtrar([item(precio=69.95)], CFG)), 0)  # reventa
        self.assertEqual(len(bot.filtrar([item(disp=False)], CFG)), 0)

    def test_chino_solo_con_rebaja(self):
        chino = "Caja Greninja EX Set 30th Celebration - Chino"
        self.assertEqual(bot.filtrar([item(titulo=chino, precio=25.0)], CFG), {})
        rebajado = bot.filtrar([{**item(titulo=chino, precio=25.0), "antes": 29.95}], CFG)
        self.assertEqual(len(rebajado), 1)
        self.assertIn("antes 29.95", bot.texto_aviso(next(iter(rebajado.values()))))

    def test_clasifica_tipos(self):
        casos = {"Minilatas Celebración 30 Aniversario": "Minilata", "Lata Sylveon ex 30 Aniversario": "Lata ex",
                 "Colección Greninja ex 30.º Aniversario": "Colección ex (Sylveon/Greninja)",
                 "Booster Bundle 30 Aniversario": "Booster Bundle", "Blister con Moneda 30 Aniversario": "Blíster con moneda"}
        for titulo, esperado in casos.items():
            self.assertEqual(bot.clasificar(titulo, CFG)[0]["producto"], esperado)

    def test_excluye(self):
        self.assertIsNone(bot.clasificar("[ DAÑADA ] ETB Celebración 30 Aniversario", CFG))
        self.assertIsNone(bot.clasificar("Mew VMAX - 30th Celebration (Ultra Rare)", CFG))


class Avisos(unittest.TestCase):
    def pasada(self, estado, items, ok=("T",), resultado=True):
        enviados = []

        def enviar(t):
            enviados.append(t)
            return resultado

        bot.procesar(estado, bot.filtrar(items, CFG), set(ok), enviar)
        return enviados

    def test_cada_vez_que_vuelve(self):
        e = {}
        self.assertEqual(len(self.pasada(e, [item()])), 1)
        self.assertEqual(len(self.pasada(e, [item()])), 0)  # sigue en stock: no repite
        self.assertEqual(len(self.pasada(e, [item(disp=False)])), 0)
        self.assertEqual(len(self.pasada(e, [item()])), 1)  # repuesto: avisa otra vez

    def test_tienda_caida_no_reavisa(self):
        e = {}
        self.pasada(e, [item()])
        self.assertEqual(len(self.pasada(e, [], ok=())), 0)
        self.assertEqual(len(self.pasada(e, [item()])), 0)

    def test_envio_fallido_se_reintenta(self):
        e = {}
        self.assertEqual(len(self.pasada(e, [item()], resultado=False)), 1)
        self.assertEqual(len(self.pasada(e, [item()])), 1)

    def test_escapa_html(self):
        self.assertIn("A &amp; B", bot.texto_aviso({**item(titulo="A & B"), "tope": 69, "reserva": False}))


class Lectores(unittest.TestCase):
    def test_shopify_variantes(self):
        p = {"title": "ETB 30 Aniversario", "handle": "etb", "vendor": "Pokémon", "variants": [
            {"id": 1, "title": "Español", "price": "59.95", "available": True},
            {"id": 2, "title": "Inglés", "price": "99.00", "available": True}]}
        otro = {"title": "ETB 30 Aniversario", "handle": "m", "vendor": "Magic", "variants": []}
        items = bot.leer_shopify({"nombre": "S", "base": "https://s"}, CFG, lambda u: json.dumps({"products": [p, otro]}))
        self.assertEqual([i["titulo"] for i in items], ["ETB 30 Aniversario (Español)", "ETB 30 Aniversario (Inglés)"])
        self.assertEqual(len(bot.filtrar(items, CFG)), 1)

    def test_ldjson(self):
        ld = {"@type": "ItemList", "itemListElement": [{"item": {
            "@type": "Product", "name": "Pokémon Lata 30 Aniversario", "url": "https://p/1",
            "offers": {"price": 24.9, "availability": "https://schema.org/OutOfStock"}}}]}
        pag = f'<script type="application/ld+json">{json.dumps(ld)}</script>'
        items = bot.leer_ldjson({"nombre": "P", "url": "https://p"}, CFG, lambda u: pag)
        self.assertEqual((len(items), items[0]["disponible"]), (1, False))


class Fichas(unittest.TestCase):
    TIENDA = next(t for t in CFG["tiendas"] if t.get("tipo") == "fichas")
    PAGINA = """data-name="Pokémon 30º Aniversario - Caja de Entrenador Élite (Español)"
        <meta itemprop="price" content="64.99"/> 'dimension6': '{}',"""

    def leer(self, pagina):
        tienda = {**self.TIENDA, "urls": ["https://x/p"]}
        return bot.leer_fichas(tienda, CFG, lambda u: pagina)

    def test_stock(self):
        self.assertFalse(self.leer(self.PAGINA.format("outOfStock"))[0]["disponible"])
        it = self.leer(self.PAGINA.format("inStock"))[0]
        self.assertTrue(it["disponible"])
        self.assertEqual(it["precio"], 64.99)
        self.assertEqual(len(bot.filtrar([it], CFG)), 1)

    def test_web_cambiada_es_fallo(self):
        with self.assertRaises(ValueError):
            self.leer("<html></html>")


class Canales(unittest.TestCase):
    def test_lee_vista_publica(self):
        pagina = ('<div class="tgme_widget_message" data-post="canal/7"><div class="tgme_widget_message_text x">'
                  'Lata 30 Aniversario<br/>en <a href="https://c">Carrefour</a> &amp; más</div></div>')
        self.assertEqual(bot.leer_canal("canal", lambda u: pagina), [(7, "Lata 30 Aniversario\nen Carrefour & más")])

    def test_arranca_sin_inundar_y_filtra(self):
        e, enviados = {}, []
        def enviar(t):
            enviados.append(t)
            return True
        bot.procesar_canal(e, "c", [(1, "ETB 30 Aniversario")], enviar, CFG)
        self.assertEqual(enviados, [])  # los antiguos no se reenvían
        posts = [(1, "ETB 30 Aniversario"), (2, "Dominio Delta"), (3, "Lata 30 Aniversario")]
        bot.procesar_canal(e, "c", posts, enviar, CFG)
        self.assertEqual(len(enviados), 1)
        self.assertEqual(e["canales"]["c"], 3)

    def test_envio_fallido_se_reintenta(self):
        e = {"canales": {"c": 1}}
        bot.procesar_canal(e, "c", [(2, "Lata 30 Aniversario")], lambda t: False, CFG)
        self.assertEqual(e["canales"]["c"], 1)

    def aviso(self, serie, tipo, tienda, precio, titulo):
        return f"PokeTracker · 1 novedad(es)\n\n 🟢 RESTOCK · {serie} · {tipo} [es]\n{tienda} — {precio}EUR\n {titulo}"

    def test_aviso_con_precio_aplica_pvp(self):
        ok = self.aviso("30th Celebration", "ETB", "El Corte Inglés", "59.99", "Juego de cartas Elite Trainer Box")
        caro = self.aviso("30th Celebration", "ETB", "Otra", "120.00", "Elite Trainer Box")
        otra_serie = self.aviso("Ascended Heroes", "ETB", "El Corte Inglés", "59.99", "Elite Trainer Box")
        textos = bot.textos_canal("c", 1, ok, CFG)
        self.assertEqual(len(textos), 1)
        self.assertIn("El Corte Inglés", textos[0])
        self.assertIn("tope 68.99", textos[0])
        self.assertEqual(bot.textos_canal("c", 1, caro, CFG), [])
        self.assertEqual(bot.textos_canal("c", 1, otra_serie, CFG), [])

    def test_chino_en_canal_no_se_reenvia(self):
        zh = self.aviso("30th Celebration", "ETB", "Otra", "50.00", "ETB").replace("[es]", "[zh]")
        self.assertEqual(bot.textos_canal("c", 1, zh, CFG), [])
        self.assertEqual(bot.textos_canal("c", 1, "Caja 30 Aniversario en chino", CFG), [])

    def test_varias_novedades_en_un_mensaje(self):
        uno = self.aviso("30th Celebration", "Mini Tin", "Carrefour", "16.99", "Mini Lata")
        dos = self.aviso("30th Celebration", "ETB", "Fnac", "59.99", "ETB")
        self.assertEqual(len(bot.textos_canal("c", 1, uno + " \n\n" + dos, CFG)), 2)

    def test_canal_caido_cuenta_como_fallo(self):
        e = {}
        def falla(c):
            raise OSError("403")
        bot.ejecutar_canales({**CFG, "canales": ["c"]}, e, lambda t: True, falla)
        self.assertEqual(e["fallos"], {"@c": 1})


class Fallos(unittest.TestCase):
    def test_avisa_una_vez_y_se_recupera(self):
        e, envios = {}, []
        for _ in range(CFG["fallos_para_avisar"] + 3):
            bot.vigilar_fallos(e, "T", "403", CFG, envios.append)
        self.assertEqual(len(envios), 1)
        bot.vigilar_fallos(e, "T", None, CFG, envios.append)
        self.assertEqual(e["fallos"], {})

    def test_una_tienda_caida_no_para_el_resto(self):
        cfg = {**CFG, "tiendas": [{"nombre": "Mala"}, {"nombre": "T", "tipo": "x"}]}

        def mala(t, c):
            raise OSError("403")

        e = {}
        eleg = bot.ejecutar(cfg, e, lambda t: True, {"shopify": mala, "x": lambda t, c: [item()]})
        self.assertEqual(len(eleg), 1)
        self.assertEqual(e["fallos"], {"Mala": 1})


if __name__ == "__main__":
    unittest.main()
