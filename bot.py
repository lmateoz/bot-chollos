# ============================================================
#  BOT DE CHOLLOS AMAZON -> TELEGRAM  (versión GitHub Actions)
#  Se ejecuta una vez por llamada; GitHub lo lanza cada 10 min.
#  El token y el chat ID se leen de los "Secrets" del repositorio.
# ============================================================
 
import re
import json
import time
import html
import os
import unicodedata
 
import requests
import feedparser
 
# ------------------------------------------------------------
# CONFIGURACIÓN
# ------------------------------------------------------------
TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
 
FEEDS = [
    "https://www.chollometro.com/rss/hot",
]
 
MAX_ALERTAS_POR_CICLO = 5
PRECIO_MAXIMO = None            # ej. 500.0 para ignorar lo que cueste más
ARCHIVO_VISTOS = "vistos.json"  # se guarda en el propio repositorio
 
PALABRAS_CLAVE = [
    "portatil", "ssd", "nvme", "monitor", "tarjeta grafica", "grafica", "gpu",
    "procesador", "ryzen", "intel", "amd", "ram", "ddr4", "ddr5", "placa base",
    "fuente de alimentacion", "ps5", "playstation", "xbox", "nintendo", "switch",
    "iphone", "ipad", "macbook", "airpods", "samsung", "galaxy", "pixel", "xiaomi",
    "smart tv", "televisor", "oled", "auriculares", "movil", "smartphone",
    "tablet", "router", "disco duro", "monitor", "msi", "pro", "teclado", "raton", "viaje",
    "escapada"
]
 
PALABRAS_EXCLUIDAS = [
    "funda", "carcasa", "protector", "cristal templado", "cable", "adaptador",
    "pegatina", "soporte", "correa", "reacondicionado",
]
 
PALABRAS_ERROR_PRECIO = ["error de precio", "fallo de precio", "bug", "precio erroneo", "corre"]
 
 
# ------------------------------------------------------------
# UTILIDADES
# ------------------------------------------------------------
def normalizar(texto):
    texto = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in texto if unicodedata.category(c) != "Mn")
 
 
def compilar(palabras):
    patron = r"\b(" + "|".join(re.escape(normalizar(p)) for p in palabras) + r")\b"
    return re.compile(patron)
 
 
RE_CLAVE = compilar(PALABRAS_CLAVE)
RE_EXCLUIR = compilar(PALABRAS_EXCLUIDAS)
RE_ERROR = compilar(PALABRAS_ERROR_PRECIO)
 
 
def cargar_vistos():
    if os.path.exists(ARCHIVO_VISTOS):
        with open(ARCHIVO_VISTOS, "r", encoding="utf-8") as f:
            return json.load(f)
    return None
 
 
def guardar_vistos(vistos):
    with open(ARCHIVO_VISTOS, "w", encoding="utf-8") as f:
        json.dump(vistos[-2000:], f, ensure_ascii=False, indent=0)
 
 
def id_entrada(e):
    return e.get("id") or e.get("guid") or e.get("link")
 
 
def datos_tienda(e):
    m = e.get("pepper_merchant")
    if isinstance(m, dict):
        return m.get("name", ""), m.get("price", "")
    return "", ""
 
 
def es_amazon(e):
    tienda, _ = datos_tienda(e)
    if tienda:
        return "amazon" in tienda.lower()
    texto = (e.get("title", "") + " " + e.get("summary", "")).lower()
    return "amazon.es" in texto or "amazon" in e.get("title", "").lower()
 
 
def precio_a_float(precio):
    try:
        limpio = re.sub(r"[^\d,\.]", "", precio).replace(".", "").replace(",", ".")
        return float(limpio)
    except ValueError:
        return None
 
 
# ------------------------------------------------------------
# TELEGRAM
# ------------------------------------------------------------
def enviar_alerta(mensaje):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": mensaje, "parse_mode": "HTML"}
    for _ in range(3):
        r = requests.post(url, json=payload, timeout=15)
        if r.status_code == 200:
            return True
        if r.status_code == 429:
            time.sleep(r.json().get("parameters", {}).get("retry_after", 5))
            continue
        print(f"Error Telegram {r.status_code}: {r.text}")
        return False
    return False
 
 
def formatear(e, precio, es_error):
    titulo = html.escape(e.get("title", "Sin título"))
    enlace = html.escape(e.get("link", ""), quote=True)
    tienda = datos_tienda(e)[0] or "oferta"
    cabecera = "⚠️ <b>POSIBLE ERROR DE PRECIO</b>" if es_error else f"🔥 <b>Chollo: {html.escape(tienda)}</b>"
    linea_precio = f"\n💶 {html.escape(precio)}" if precio else ""
    return f'{cabecera}\n\n📌 <b>{titulo}</b>{linea_precio}\n\n🔗 <a href="{enlace}">Ver oferta</a>'
 
 
# ------------------------------------------------------------
# LÓGICA
# ------------------------------------------------------------
def leer_entradas():
    entradas = []
    cabeceras = {"User-Agent": "Mozilla/5.0 (bot de chollos personal)"}
    for url in FEEDS:
        try:
            r = requests.get(url, headers=cabeceras, timeout=20)
            r.raise_for_status()
            feed = feedparser.parse(r.content)
            if not feed.entries:
                print(f"Aviso: feed vacío o no válido: {url}")
            entradas.extend(feed.entries)
        except Exception as ex:
            print(f"Error leyendo {url}: {ex}")
    return entradas
 
 
def pasa_filtros(e):
    titulo = normalizar(e.get("title", ""))
    if RE_EXCLUIR.search(titulo):
        return False
    es_error = bool(RE_ERROR.search(titulo))
    if not (RE_CLAVE.search(titulo) or es_error):
        return False
    if PRECIO_MAXIMO is not None:
        _, precio = datos_tienda(e)
        valor = precio_a_float(precio) if precio else None
        if valor is not None and valor > PRECIO_MAXIMO:
            return False
    return True
 
 
def main():
    entradas = leer_entradas()
    vistos = cargar_vistos()
 
    if vistos is None:
        # Primera ejecución: marcar todo como visto sin enviar nada
        vistos = [id_entrada(e) for e in entradas]
        guardar_vistos(vistos)
        print(f"Primera ejecución: {len(vistos)} ofertas existentes ignoradas.")
        return
 
    conjunto = set(vistos)
    enviadas = 0
    for e in entradas:
        ident = id_entrada(e)
        if ident in conjunto:
            continue
        conjunto.add(ident)
        vistos.append(ident)
        if enviadas >= MAX_ALERTAS_POR_CICLO or not pasa_filtros(e):
            continue
        _, precio = datos_tienda(e)
        es_error = bool(RE_ERROR.search(normalizar(e.get("title", ""))))
        if enviar_alerta(formatear(e, precio, es_error)):
            enviadas += 1
            print(f"Enviada: {e.get('title')}")
            time.sleep(1)
 
    guardar_vistos(vistos)
    print(f"{enviadas} alertas enviadas.")
 
 
if __name__ == "__main__":
    main()
