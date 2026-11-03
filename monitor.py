# -*- coding: utf-8 -*-
"""
Monitor Vinted con avvisi su Telegram.

Controlla periodicamente le ricerche definite in config.json e, quando compare
un annuncio NUOVO che rispetta i filtri (testo, prezzo, taglia, condizioni),
manda una notifica Telegram con foto, prezzo e link dell'annuncio.

Uso:
    python monitor.py            avvia il monitor (notifiche attive)
    python monitor.py prova      un solo giro di controllo, stampa i risultati
                                 in console senza mandare notifiche
    python monitor.py durata N   come il primo, ma si ferma da solo dopo N
                                 secondi (usato da GitHub Actions)

Token e chat_id possono arrivare anche dalle variabili d'ambiente
TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID (hanno la precedenza su config.json).

Si appoggia alla libreria vinted_scraper, che gestisce da sola la sessione
anonima con Vinted (token, cookie e rinnovo automatico).
"""

import json
import logging
import os
import random
import re
import sys
import time
from pathlib import Path

import httpx
from vinted_scraper import VintedWrapper

CARTELLA = Path(__file__).resolve().parent
FILE_CONFIG = CARTELLA / "config.json"
FILE_VISTI = CARTELLA / "visti.json"
FILE_LOG = CARTELLA / "monitor.log"
BASE_URL = "https://www.vinted.it"
API_TELEGRAM = "https://api.telegram.org/bot{token}/{metodo}"
MAX_ID_SALVATI = 800       # quanti ID di annuncio ricordare per ogni ricerca
MIN_INTERVALLO = 30        # secondi, per non stressing il sito
CAMPO_TESTO_DEFAULT = "inserisci qui le parole da cercare su Vinted"

log = logging.getLogger("vinted-monitor")


# --------------------------------------------------------------------------
# Configurazione
# --------------------------------------------------------------------------

def carica_config(percorso=FILE_CONFIG):
    if not percorso.exists():
        interrompi(f"Manca il file {percorso.name}: copialo da config.json "
                   "se l'hai cancellato, poi riavvia.")
    try:
        cfg = json.loads(percorso.read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        interrompi(f"Errore in {percorso.name} (JSON non valido): {err}")
    ricerche = cfg.get("ricerche") or []
    if not isinstance(cfg.get("ricerche"), list) or not ricerche:
        interrompi(f"In {percorso.name} la lista 'ricerche' e' vuota: "
                   "aggiungi almeno una ricerca.")
    for i, ric in enumerate(ricerche, start=1):
        if not isinstance(ric, dict) or not (ric.get("testo") or "").strip():
            interrompi(f"La ricerca numero {i} in {percorso.name} non ha il "
                       "campo 'testo'.")
        if ric["testo"].strip() == CAMPO_TESTO_DEFAULT:
            interrompi(f"La ricerca '{ric.get('nome', i)}' ha ancora il testo "
                       "di esempio: apri config.json e scrivi cosa cercare.")
    return cfg


def salva_config(cfg):
    FILE_CONFIG.write_text(
        json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------
# Stato degli annunci gia' visti
# --------------------------------------------------------------------------

def carica_visti():
    if FILE_VISTI.exists():
        try:
            return json.loads(FILE_VISTI.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            log.warning("File %s danneggiato: lo ricreo da zero.", FILE_VISTI.name)
    return {}


def salva_visti(visti):
    for nome in visti:
        visti[nome] = sorted(set(visti[nome]))[-MAX_ID_SALVATI:]
    tmp = FILE_VISTI.with_suffix(".tmp")
    tmp.write_text(json.dumps(visti), encoding="utf-8")
    tmp.replace(FILE_VISTI)


# --------------------------------------------------------------------------
# Filtri sui risultati
# --------------------------------------------------------------------------

def minuscolo(testo):
    return (testo or "").lower()


def estrai_taglia(second_line):
    """Da '43 · Buone' ricava '43'; da 'S · Ottime' ricava 'S'."""
    parte = (second_line or "").split("·")[0]
    return parte.strip()


def normalizza_taglia(taglia):
    t = minuscolo(taglia).replace(",", ".").strip()
    t = re.sub(r"^(eu|taglia|size)\s*", "", t).strip()
    return t


def taglia_corrisponde(taglie_cercate, taglia_annuncio, titolo):
    for t in taglie_cercate:
        nt = normalizza_taglia(t)
        if nt and nt == normalizza_taglia(taglia_annuncio):
            return True
        if nt and re.search(r"(?<![\d.,])" + re.escape(nt) + r"(?![\d.,])", titolo):
            return True
    return False


def annuncio_corrisponde(ann, ric):
    """Ritorna True se l'annuncio passa tutti i filtri della ricerca."""
    titolo = minuscolo(ann.get("title"))
    box = ann.get("item_box") or {}
    second_line = box.get("second_line") or ""

    for parola in ric.get("parole_chiave") or []:
        if minuscolo(parola).strip() not in titolo:
            return False
    for parola in ric.get("escludi") or []:
        if minuscolo(parola).strip() in titolo:
            return False

    # 'parole_alternative': basta che UNA delle parole sia nel titolo
    # (serve per le grafie diverse, es. "wii u" / "wiiu" / "wii-u")
    alternative = [p for p in (ric.get("parole_alternative") or [])
                   if str(p).strip()]
    if alternative and not any(minuscolo(p).strip() in titolo for p in alternative):
        return False

    taglie = [t for t in (ric.get("taglie") or []) if str(t).strip()]
    if taglie and not taglia_corrisponde(
            taglie, estrai_taglia(second_line), titolo):
        return False

    condizioni = ric.get("condizioni") or []
    if condizioni:
        parte_condizioni = second_line.split("·", 1)[1] if "·" in second_line else ""
        if not any(minuscolo(c) in minuscolo(parte_condizioni) for c in condizioni):
            return False

    prezzo = prezzo_annuncio(ann)
    if prezzo is not None:
        minimo = ric.get("prezzo_min")
        massimo = ric.get("prezzo_max")
        if minimo is not None and prezzo < float(minimo):
            return False
        if massimo is not None and prezzo > float(massimo):
            return False
    return True


# --------------------------------------------------------------------------
# Lettura annunci
# --------------------------------------------------------------------------

def prezzo_annuncio(ann):
    prezzo = ann.get("price") or {}
    try:
        return float(prezzo.get("amount"))
    except (TypeError, ValueError):
        return None


def crea_wrapper(tentativi=3, esci=True):
    """Crea il client Vinted ritentando: a volte il primo colpo fallisce.

    Con esci=True (avvio) interrompe lo script dopo i tentativi falliti;
    con esci=False (giro di controllo) ritorna None e si riprovera' al
    giro successivo, senza fermare il monitor.
    """
    ultimo_errore = None
    for tentativo in range(1, tentativi + 1):
        try:
            wrapper = VintedWrapper(BASE_URL)
            log.info("Sessione Vinted avviata (tentativo %d).", tentativo)
            return wrapper
        except Exception as err:  # noqa: BLE001 - errore di rete/sessione qualunque
            ultimo_errore = err
            log.warning("Avvio sessione Vinted fallito (%d/%d): %s",
                        tentativo, tentativi, err)
            time.sleep(15 * tentativo)
    if esci:
        interrompi(f"Impossibile collegarsi a Vinted dopo {tentativi} tentativi "
                   f"({ultimo_errore}). Attendi qualche minuto e riprova: "
                   "il sito a volte rifiuta temporaneamente le richieste.")
    log.error("Sessione Vinted non ripartita: riprovera' al prossimo giro.")
    return None


def cerca_annunci(wrapper, ric, per_page):
    parametri = {
        "search_text": ric["testo"],
        "order": "newest_first",
        "per_page": per_page,
    }
    if ric.get("prezzo_min") is not None:
        parametri["price_from"] = ric["prezzo_min"]
    if ric.get("prezzo_max") is not None:
        parametri["price_to"] = ric["prezzo_max"]
    if ric.get("catalogo_id"):
        # Categoria Vinted (es. 3025 = Console): esclude giochi, controller
        # e accessori gia' a monte, quando il venditore li ha categorizzati bene.
        parametri["attribute_ids[catalog]"] = str(ric["catalogo_id"])
    risposta = wrapper.search(parametri)
    return risposta.get("items") or []


# --------------------------------------------------------------------------
# Telegram
# --------------------------------------------------------------------------

def trova_chat_id(token):
    """Ricava il tuo chat_id dagli ultimi messaggi mandati al bot."""
    try:
        r = httpx.post(API_TELEGRAM.format(token=token, metodo="getUpdates"),
                       timeout=15)
        dati = r.json()
    except (httpx.HTTPError, ValueError):
        return None
    if not dati.get("ok"):
        return None
    for aggiornamento in reversed(dati.get("result") or []):
        messaggio = aggiornamento.get("message") or aggiornamento.get(
            "channel_post") or {}
        chat = messaggio.get("chat") or {}
        if chat.get("type") == "private" and chat.get("id"):
            return str(chat["id"])
    return None


def prepara_token_e_chat(cfg):
    """Verifica token e chat_id; se manca il chat_id prova a scoprirlo."""
    token = (os.environ.get("TELEGRAM_BOT_TOKEN")
             or cfg.get("telegram_bot_token") or "").strip()
    if not token or "INCOLLA" in token:
        interrompi(
            "Manca il token del bot Telegram in config.json.\n"
            "Come si ottiene:\n"
            "  1. Apri Telegram e cerca @BotFather\n"
            "  2. Manda il comando /newbot e segui le indicazioni\n"
            "  3. Copia il token (tipo 123456789:AAE3...) nel campo\n"
            "     'telegram_bot_token' di config.json\n"
            "Poi riavvia lo script.")
    chat_id = (os.environ.get("TELEGRAM_CHAT_ID")
               or cfg.get("telegram_chat_id") or "").strip()
    if not chat_id:
        log.info("Campo 'telegram_chat_id' vuoto: cerco messaggi recenti "
                 "mandati al bot...")
        chat_id = trova_chat_id(token)
        if chat_id:
            cfg["telegram_chat_id"] = chat_id
            salva_config(cfg)
            log.info("Chat_id trovato e salvato in config.json: %s", chat_id)
        else:
            interrompi(
                "Non riesco a scoprire il tuo chat_id.\n"
                "Apri Telegram, cerca il tuo bot per nome, mandagli un "
                "messaggio qualsiasi (es. /start) e riavvia lo script: "
                "lo scoprirà da solo.")
    return token, chat_id


def formatta_prezzo(prezzo):
    if not prezzo:
        return ""
    valuta = "€" if (prezzo.get("currency_code") or "EUR") == "EUR" \
        else prezzo.get("currency_code", "")
    importo = (prezzo.get("amount") or "?").replace(".", ",")
    return f"{importo} {valuta}".strip()


def testo_messaggio(ann, ric):
    titolo = ann.get("title") or "(senza titolo)"
    second_line = (ann.get("item_box") or {}).get("second_line") or ""
    url = ann.get("url") or ""
    if url and not url.startswith("http"):
        url = BASE_URL + url
    righe = [
        f"Nuovo annuncio: {ric.get('nome') or ric['testo']}",
        "",
        titolo,
        f"Prezzo: {formatta_prezzo(ann.get('price'))}",
    ]
    totale = formatta_prezzo(ann.get("total_item_price"))
    if totale and totale != formatta_prezzo(ann.get("price")):
        righe.append(f"Totale con spese: {totale}")
    if second_line:
        righe.append(f"Taglia/condizioni: {second_line}")
    if url:
        righe.append("")
        righe.append(url)
    return "\n".join(righe)


def invia_notifica(token, chat_id, ann, ric):
    """Manda la notifica: foto dell'annuncio con didascalia, o solo testo."""
    testo = testo_messaggio(ann, ric)
    foto = (ann.get("photo") or {}).get("full_size_url")

    tentativi = []
    if foto:
        tentativi.append(("sendPhoto", {"photo": foto, "caption": testo[:1000]}))
    tentativi.append(("sendMessage", {"text": testo[:4000]}))

    for metodo, extra in tentativi:
        payload = {"chat_id": chat_id, **extra}
        try:
            r = httpx.post(API_TELEGRAM.format(token=token, metodo=metodo),
                           data=payload, timeout=20)
            dati = r.json()
        except (httpx.HTTPError, ValueError) as err:
            log.error("Invio Telegram (%s) fallito: %s", metodo, err)
            return
        if dati.get("ok"):
            return
        descrizione = dati.get("description", "?")
        log.error("Telegram ha risposto con errore (%s): %s", metodo, descrizione)
        if "chat" in descrizione.lower():
            log.error("Suggerimento: apri Telegram, manda un messaggio al "
                      "tuo bot e riavvia, oppure controlla telegram_chat_id.")
            return


# --------------------------------------------------------------------------
# Ciclo principale
# --------------------------------------------------------------------------

def interrompi(messaggio):
    print(f"\n{messaggio}\n", file=sys.stderr)
    sys.exit(1)


def elabora_ricerca(wrapper, ric, visti, per_page):
    """Un giro di controllo per una ricerca.

    Ritorna (wrapper, annunci nuovi che passano i filtri). Se la sessione
    va in crisi prova a rinnovarla, o a ricrearla senza fermare il monitor.
    """
    nome = ric.get("nome") or ric["testo"]
    try:
        annunci = cerca_annunci(wrapper, ric, per_page)
    except Exception as err:  # noqa: BLE001 - errore di rete/sessione qualunque
        log.warning("Ricerca '%s' fallita (%s): rinnovo la sessione.", nome, err)
        try:
            wrapper.refresh_session()
        except Exception:  # noqa: BLE001
            log.warning("Rinnovo fallito: ricreo la sessione da zero.")
            wrapper = crea_wrapper(esci=False)
        return wrapper, []

    ids = [ann.get("id") for ann in annunci]
    gia_visti = set(visti.get(nome, []))

    if nome not in visti:
        # Primo giro: memorizza gli annunci esistenti senza avvisare.
        visti[nome] = ids
        log.info("Primo giro per '%s': %d annunci esistenti memorizzati, "
                 "nessun avviso. Da ora avviso solo le novita'.", nome, len(ids))
        return wrapper, []

    nuovi = [ann for ann in annunci if ann.get("id") not in gia_visti]
    corrispondono = [ann for ann in nuovi if annuncio_corrisponde(ann, ric)]
    for ann in nuovi:
        gia_visti.add(ann.get("id"))
    visti[nome] = list(gia_visti)

    if nuovi:
        log.info("'%s': %d annunci nuovi, %d passano i filtri.",
                 nome, len(nuovi), len(corrispondono))
    return wrapper, corrispondono


def main():
    solo_prova = len(sys.argv) > 1 and sys.argv[1].lower() in ("prova", "test")
    durata_max = None
    if len(sys.argv) > 2 and sys.argv[1].lower() == "durata":
        durata_max = int(sys.argv[2])
    inizio = time.monotonic()

    # Log su console e su file (il file vecchio viene ruotato se cresce troppo)
    if FILE_LOG.exists() and FILE_LOG.stat().st_size > 5_000_000:
        FILE_LOG.replace(CARTELLA / "monitor.log.vecchio")
    log.setLevel(logging.INFO)
    formato = logging.Formatter("%(asctime)s %(levelname)s %(message)s",
                                datefmt="%d/%m %H:%M:%S")
    console = logging.StreamHandler()
    console.setFormatter(formato)
    log.addHandler(console)
    file_log = logging.FileHandler(FILE_LOG, encoding="utf-8")
    file_log.setFormatter(formato)
    log.addHandler(file_log)

    cfg = carica_config()
    intervallo = max(MIN_INTERVALLO, int(cfg.get("intervallo_secondi", 60)))
    per_page = min(96, max(1, int(cfg.get("risultati_per_ricerca", 30))))
    ricerche = cfg["ricerche"]

    if solo_prova:
        log.info("MODALITA' PROVA: un solo giro, nessuna notifica, "
                 "nessuno stato salvato.")
        wrapper = crea_wrapper()
        for ric in ricerche:
            nome = ric.get("nome") or ric["testo"]
            try:
                annunci = cerca_annunci(wrapper, ric, per_page)
            except Exception as err:  # noqa: BLE001
                log.error("Ricerca '%s' fallita: %s", nome, err)
                continue
            log.info("Ricerca '%s': %d annunci trovati.", nome, len(annunci))
            for ann in annunci:
                spunta = "SI'" if annuncio_corrisponde(ann, ric) else "no"
                titolo = (ann.get("title") or "")[:60]
                prezzo = formatta_prezzo(ann.get("price"))
                taglia = estrai_taglia((ann.get("item_box") or {})
                                       .get("second_line") or "")
                log.info("  [filtri: %s] %s | %s | taglia %s",
                         spunta, titolo, prezzo, taglia or "-")
        log.info("Prova terminata.")
        return

    token, chat_id = prepara_token_e_chat(cfg)
    wrapper = crea_wrapper()
    visti = carica_visti()
    log.info("Monitor avviato: %d ricerca/e, controllo ogni ~%d secondi.",
             len(ricerche), intervallo)
    log.info("Per fermare: Ctrl+C nella finestra.")

    while True:
        if durata_max is not None and time.monotonic() - inizio >= durata_max:
            log.info("Durata massima raggiunta (%d s): mi fermo.", durata_max)
            return
        for ric in ricerche:
            wrapper, nuovi = elabora_ricerca(wrapper, ric, visti, per_page)
            for ann in nuovi:
                invia_notifica(token, chat_id, ann, ric)
                time.sleep(1.5)  # piccola pausa tra messaggi Telegram
            salva_visti(visti)
            if len(ricerche) > 1:
                time.sleep(random.uniform(3, 6))
        # leggera variabilita' per non sembrare un robot a orologio
        time.sleep(intervallo * random.uniform(0.9, 1.15))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nMonitor fermato.")
        sys.exit(0)
