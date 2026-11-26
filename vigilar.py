"""Vigila 2 cargadores de Iberdrola (IDs de la app) y avisa por Telegram
cuando se ocupan o quedan libres. Se lanza a mano (Run workflow) indicando
cuantas horas vigilar. Usa la sesion del usuario (secreto
IBERDROLA_REFRESH_TOKEN). Nunca imprime tokens."""
import json, os, time, requests
from datetime import datetime
from zoneinfo import ZoneInfo

CARGADORES = {145612: "Plaza Puertas de San José", 145613: "Paseo Alfonso XIII"}
TOKEN_TG = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
REFRESH = os.environ["IBERDROLA_REFRESH_TOKEN"].strip()
HASTA = float(os.environ["HASTA"])          # fin de la vigilancia (epoch)
PRIMERA = os.environ.get("PRIMERA") == "1"   # primera ejecucion de la cadena
INTERVALO = 30                               # segundos entre consultas
MAX_POR_EJECUCION = 340 * 60                 # GitHub corta los trabajos a las 6 h
ESTADO = "estado.json"
MADRID = ZoneInfo("Europe/Madrid")

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


def hora(ts=None):
    return datetime.fromtimestamp(ts or time.time(), MADRID).strftime("%H:%M")


def renovar():
    try:
        r = requests.post(URL_TOKEN, timeout=20, json={
            "grant_type": "refresh_token", "client_id": CLIENT_ID,
            "refresh_token": REFRESH})
        print(f"  renovacion de sesion: HTTP {r.status_code}")
        if r.status_code != 200:
            try:
                e = r.json()
                print("   motivo:", e.get("error"), "-", str(e.get("error_description"))[:120])
            except Exception:
                print("   respuesta no JSON:", r.headers.get("server"), r.text[:150].replace("\n", " "))
            return False
        d = r.json()
        sesion["token"] = d["access_token"]
        sesion["caduca"] = time.time() + int(d.get("expires_in", 3600)) - 300
        return True
    except Exception as ex:
        print("  renovacion ERROR", type(ex).__name__)
        return False


def consultar():
    if not sesion["token"] or time.time() > sesion["caduca"]:
        if not renovar():
            return None
    try:
        h = dict(HEADERS, authorization="Bearer " + sesion["token"])
        r = requests.post(URL_MAPA, json=BODY, headers=h, timeout=20)
        if r.status_code in (401, 403):
            print(f"  mapa: HTTP {r.status_code}")
            sesion["token"] = None
            return None
        r.raise_for_status()
        res = {x["cpId"]: (x.get("cpStatus") or {}).get("statusCode")
               for x in r.json() if x.get("cpId") in CARGADORES}
        print(" ", hora(), res)
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


def nombre_estado(libre):
    return "🟢 libre" if libre else "🔴 ocupado"


def main():
    try:
        st = json.load(open(ESTADO))
    except Exception:
        st = {}
    if PRIMERA:   # vigilancia nueva: se empieza de cero
        st = {}
    for k, v in (("anterior", {}), ("candidato", {}), ("repeticiones", {}),
                 ("fallos", 0), ("avisado_fallo", False)):
        st.setdefault(k, v)

    if HASTA <= time.time() + 60:   # se lanzo con 0 horas: solo parar
        telegram(f"⏹️ Vigilancia parada ({hora()}).")
        open("seguir", "w").write("no")
        return

    fin = min(HASTA, time.time() + MAX_POR_EJECUCION)
    if PRIMERA:
        estados = consultar()
        linea = ""
        if estados:
            linea = "\n" + "\n".join(f"{CARGADORES[c]}: {nombre_estado(e == 'AVAILABLE')}"
                                     for c, e in estados.items())
            for c, e in estados.items():
                st["anterior"][str(c)] = e == "AVAILABLE"
        telegram(f"▶️ Vigilando hasta las {hora(HASTA)}.{linea}")

    while time.time() < fin:
        estados = consultar()
        if estados is None:
            st["fallos"] += 1
            if st["fallos"] >= 20 and not st["avisado_fallo"]:
                telegram("⚠️ No consigo leer el estado de los cargadores. Puede que haya "
                         "caducado tu sesión de Iberdrola: habrá que capturar un token nuevo.")
                st["avisado_fallo"] = True
        else:
            if st["avisado_fallo"]:
                telegram("✅ Vuelvo a leer el estado de los cargadores.")
            st["fallos"], st["avisado_fallo"] = 0, False
            for cid, estado in estados.items():
                libre = estado == "AVAILABLE"
                k = str(cid)
                # Un cambio solo vale si se repite en 2 lecturas seguidas (~30 s)
                if st["candidato"].get(k) == libre:
                    st["repeticiones"][k] = st["repeticiones"].get(k, 0) + 1
                else:
                    st["candidato"][k] = libre
                    st["repeticiones"][k] = 1
                if st["repeticiones"][k] < 2:
                    continue
                previo = st["anterior"].get(k)
                if previo is not None and previo != libre:
                    if libre:
                        telegram(f"🟢 {CARGADORES[cid]}: LIBRE ({hora()})")
                    else:
                        telegram(f"🔴 {CARGADORES[cid]}: OCUPADO ({hora()}) [{estado}]")
                st["anterior"][k] = libre
        json.dump(st, open(ESTADO, "w"))
        time.sleep(INTERVALO)

    json.dump(st, open(ESTADO, "w"))
    if time.time() >= HASTA - 60:
        telegram(f"⏹️ Vigilancia terminada ({hora()}).")
        open("seguir", "w").write("no")
    else:
        open("seguir", "w").write("si")


if __name__ == "__main__":
    main()
