"""Vigila 2 cargadores de Iberdrola (IDs de la app) y avisa por Telegram
cuando pasan de OCUPADO a LIBRE. Usa la sesion del usuario (token de
renovacion en el secreto IBERDROLA_REFRESH_TOKEN). Nunca imprime tokens.
Pensado para GitHub Actions: cada ejecucion vigila ~55 min (1 consulta/min)."""
import json, os, time, requests

CARGADORES = {145612: "Plaza Puertas de San José", 145613: "Paseo Alfonso XIII"}
TOKEN_TG = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
REFRESH = os.environ["IBERDROLA_REFRESH_TOKEN"].strip()
DURACION_MIN = int(os.environ.get("DURACION_MIN", "55"))
ESTADO = "estado.json"

URL_TOKEN = "https://login-rp.iberdrola.com/oauth/token"
CLIENT_ID = "6K4rRPc6x0LmBO7FLWKxrqhBewNEYbuU"
URL_MAPA = "https://eva.iberdrola.com/veappapi/map/getMapChargePoints"
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

sesion = {"token": None, "caduca": 0}


def renovar():
    """Pide un token de acceso nuevo. Devuelve True si lo consigue."""
    try:
        r = requests.post(URL_TOKEN, timeout=20, json={
            "grant_type": "refresh_token", "client_id": CLIENT_ID,
            "refresh_token": REFRESH})
        print(f"  renovacion de sesion: HTTP {r.status_code}")
        if r.status_code != 200:
            return False
        d = r.json()
        sesion["token"] = d["access_token"]
        sesion["caduca"] = time.time() + int(d.get("expires_in", 3600)) - 300
        return True
    except Exception as ex:
        print("  renovacion ERROR", type(ex).__name__)
        return False


def consultar():
    """Devuelve {cpId: statusCode} de mis cargadores, o None si falla."""
    if not sesion["token"] or time.time() > sesion["caduca"]:
        if not renovar():
            return None
    try:
        h = dict(HEADERS, authorization="Bearer " + sesion["token"])
        r = requests.post(URL_MAPA, json=BODY, headers=h, timeout=20)
        print(f"  mapa: HTTP {r.status_code}")
        if r.status_code in (401, 403):
            sesion["token"] = None
            return None
        r.raise_for_status()
        res = {x["cpId"]: (x.get("cpStatus") or {}).get("statusCode")
               for x in r.json() if x.get("cpId") in CARGADORES}
        print("  ", res)
        return res or None
    except Exception as ex:
        print("  mapa ERROR", type(ex).__name__)
        return None


def telegram(texto):
    try:
        requests.post(f"https://api.telegram.org/bot{TOKEN_TG}/sendMessage",
                      json={"chat_id": CHAT_ID, "text": texto}, timeout=15)
    except Exception:
        print("Telegram fallo")


def main():
    try:
        st = json.load(open(ESTADO))
    except Exception:
        st = {}
    st.setdefault("anterior", {})
    st.setdefault("fallos", 0)
    st.setdefault("avisado_fallo", False)
    if not st.get("v3"):
        telegram("✅ Vigilante activo (con tu sesión): Puertas de San José y Paseo Alfonso XIII.")
        st["v3"] = True

    fin = time.time() + DURACION_MIN * 60
    while time.time() < fin:
        print(time.strftime("%H:%M UTC"))
        estados = consultar()
        if estados is None:
            st["fallos"] += 1
            if st["fallos"] >= 10 and not st["avisado_fallo"]:
                telegram("⚠️ No consigo leer el estado de los cargadores. Puede que haya "
                         "caducado tu sesión de Iberdrola: habrá que capturar un token nuevo.")
                st["avisado_fallo"] = True
        else:
            if st["avisado_fallo"]:
                telegram("✅ Vuelvo a leer el estado de los cargadores.")
            st["fallos"], st["avisado_fallo"] = 0, False
            for cid, estado in estados.items():
                libre = estado == "AVAILABLE"
                if st["anterior"].get(str(cid)) is False and libre:
                    telegram(f"⚡ {CARGADORES[cid]} acaba de quedar LIBRE.")
                st["anterior"][str(cid)] = libre
        json.dump(st, open(ESTADO, "w"))
        time.sleep(60)


if __name__ == "__main__":
    main()
