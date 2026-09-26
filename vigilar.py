"""Vigila 2 cargadores de Iberdrola y avisa por Telegram cuando quedan libres.
Pensado para GitHub Actions: cada ejecución vigila ~55 min (1 consulta/min)."""
import json, os, time, requests

CARGADORES = {145612: "Bastarreche", 145613: "Casa de la Juventud"}
TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
DURACION_MIN = int(os.environ.get("DURACION_MIN", "55"))
ESTADO = "estado.json"

URL = "https://www.iberdrola.es/o/webclipb/iberdrola/puntosrecargacontroller/getDatosPuntoRecarga"
HEADERS = {"Content-Type": "application/json", "Accept": "application/json",
           "User-Agent": "Mozilla/5.0",
           "Referer": "https://www.iberdrola.es/movilidad-electrica/puntos-de-recarga"}
LIBRE = {"AVAILABLE", "DISPONIBLE", "LIBRE"}


def estados(obj, out):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.lower() in ("statuscode", "estado", "status") and isinstance(v, str):
                out.append(v.upper())
            else:
                estados(v, out)
    elif isinstance(obj, list):
        for i in obj:
            estados(i, out)
    return out


def consultar(cid):
    try:
        r = requests.post(URL, json={"dto": {"cuprId": [cid]}, "language": "es"},
                          headers=HEADERS, timeout=20)
        r.raise_for_status()
        e = estados(r.json(), [])
        print(f"  {cid}: HTTP {r.status_code}, estados={e}")
        if not e:
            print("  Respuesta:", r.text[:500])
            return None
        return any(s in LIBRE for s in e)
    except Exception as ex:
        print(f"  {cid}: ERROR {ex}")
        return None


def telegram(texto):
    try:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                      json={"chat_id": CHAT_ID, "text": texto}, timeout=15)
    except Exception as ex:
        print("Telegram falló:", ex)


def main():
    try:
        st = json.load(open(ESTADO))
    except Exception:
        st = {"anterior": {}, "fallos": 0, "avisado_fallo": False, "primera": True}
    if st.get("primera"):
        telegram("✅ Vigilante en la nube activo: Bastarreche y Casa de la Juventud.")
        st["primera"] = False

    fin = time.time() + DURACION_MIN * 60
    while time.time() < fin:
        print(time.strftime("%H:%M UTC"))
        for cid, nombre in CARGADORES.items():
            libre = consultar(cid)
            if libre is None:
                st["fallos"] += 1
                if st["fallos"] >= 10 and not st["avisado_fallo"]:
                    telegram("⚠️ No consigo leer el estado de los cargadores en la web de "
                             "Iberdrola. Revisa el registro en GitHub Actions.")
                    st["avisado_fallo"] = True
                continue
            st["fallos"], st["avisado_fallo"] = 0, False
            if st["anterior"].get(str(cid)) is False and libre:
                telegram(f"⚡ {nombre} acaba de quedar LIBRE.")
            st["anterior"][str(cid)] = libre
        json.dump(st, open(ESTADO, "w"))
        time.sleep(60)


if __name__ == "__main__":
    main()
