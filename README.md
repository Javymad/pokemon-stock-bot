# Bot de stock Pokémon 30.º Aniversario

Revisa tiendas de España cada 10 minutos (GitHub Actions) y avisa por Telegram cuando un producto sellado
de la colección entra en stock a PVP, en cualquier idioma. Avisa cada vez que entra: si sigue en stock no
repite, y si se agota y vuelve, avisa otra vez.

## Puesta en marcha

1. En Telegram, habla con @BotFather, usa `/newbot` y guarda el token. Escribe `/start` a tu bot.
2. Crea un repositorio **público** en tu GitHub personal (minutos de Actions ilimitados) y sube esta carpeta.
   El token nunca va en el código.
3. En el repositorio: Settings > Secrets and variables > Actions, crea `TELEGRAM_TOKEN` y `TELEGRAM_CHAT_ID`.
   El chat id te lo dice @userinfobot en Telegram (campo Id).
4. En Actions, lanza "Vigilar stock" a mano. La primera pasada avisa de todo lo que ya esté disponible.

## Ajustes

Todo está en `config.json`:

- `reglas`: PVP por producto. **Son estimaciones**, no hay PVP oficial publicado para España. Corrígelos si conoces el real.
- `margen`: 0.15 = se avisa hasta PVP + 15 %.
- `tiendas`: tiendas vigiladas. `excluir`: palabras que descartan un producto.

## Comprobar

    python -m unittest test_bot
    python bot.py --dry-run

Si una tienda no se puede leer durante 12 pasadas seguidas (unas 2 horas), el bot avisa una vez por Telegram.

## Sin cubrir

Carrefour, Fnac, GAME y Xtralife rechazan consultas automáticas (403). lamafiadelsobre.com también.
El Corte Inglés y Toys R Us las prohíben en `robots.txt`, y Amazon en sus condiciones de uso.
No se esquivan esos bloqueos: para esas tiendas usa sus avisos propios ("Avísame") o un servicio de alertas.
