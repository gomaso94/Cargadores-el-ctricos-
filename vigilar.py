"""Vigila 2 cargadores de Iberdrola (IDs de la app) y avisa por Telegram
cuando pasan de OCUPADO a LIBRE. Pensado para GitHub Actions:
cada ejecución vigila ~55 min (1 consulta/min)."""
import json, os, time, requests

CARGADORES = {145612: "Plaza Puertas de San José", 145613: "Paseo Alfonso XIII"}
TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
DURACION_MIN = int(os.environ.get("DURACION_MIN", "55"))
ESTADO = "estado.json"

URL = "https://eva.iberdrola.com/veappapi/map/getMapChargePoints"
HEADERS = {
    "content-type": "application/json",
    "accept": "application/json",
    "versionapp": "IOS-4.42.0",
    "plataforma": "iOS",
    "societyid": "1",
    "accept-language": "es-ES",
    "numlat": "37.6085",
    "numlon": "-0.9911",
    "user-agent": "azkarga/4.42.0 (es.iberdrola.recargaverde; build:4420002; iOS 26.7.0) Alamofire/4.9.1",
}
BODY = {
    "longitudeMin": -1.0342467203736305, "longitudeMax": -0.9479868784546853,
    "latitudeMin": 37.5477723059228, "latitudeMax": 37.66353817049806,
    "connectorTypeCodes": [], "placeTypes": [], "loadSpeedCodes": [],
    "iberdrola": False, "autocharge": False, "advantageous": False,
}


def consultar():
    """Devuelve {cpId: statusCode} de mis cargadores, o None si falla."""
    try:
        r = requests.post(URL, json=BODY, headers=HEADERS, timeout=20)
        print(f"  HTTP {r.status_code}")
        r.raise_for_status()
        datos = r.json()
        lista = datos if isinstance(datos, list) else next(
            v for v in datos.values() if isinstance(v, list))
        res = {x["cpId"]: (x.get("cpStatus") or {}).get("statusCode")
               for x in lista if x.get("cpId") in CARGADORES}
        print("  ", res)
        return res or None
    except Exception as ex:
        print("  ERROR", ex)
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
        st = {}
    st.setdefault("anterior", {})
    st.setdefault("fallos", 0)
    st.setdefault("avisado_fallo", False)
    if not st.get("v2"):
        telegram("✅ Vigilante activo: Puertas de San José y Paseo Alfonso XIII.")
        st["v2"] = True

    fin = time.time() + DURACION_MIN * 60
    while time.time() < fin:
        print(time.strftime("%H:%M UTC"))
        estados = consultar()
        if estados is None:
            st["fallos"] += 1
            if st["fallos"] >= 10 and not st["avisado_fallo"]:
                telegram("⚠️ No consigo leer el estado de los cargadores. "
                         "Revisa el registro en GitHub Actions.")
                st["avisado_fallo"] = True
        else:
            if st["avisado_fallo"]:
                telegram("✅ Vuelvo a leer el estado de los cargadores.")
            st["fallos"], st["avisado_fallo"] = 0, False
            for cid, estado in estados.items():
                libre = estado == "AVAILABLE"
                previo = st["anterior"].get(str(cid))
                if previo is False and libre:
                    telegram(f"⚡ {CARGADORES[cid]} acaba de quedar LIBRE.")
                st["anterior"][str(cid)] = libre
        json.dump(st, open(ESTADO, "w"))
        time.sleep(60)


if __name__ == "__main__":
    main()
