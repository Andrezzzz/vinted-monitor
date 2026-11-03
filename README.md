# Monitor Vinted con notifiche Telegram

Uno script che controlla Vinted per te, a intervalli regolari, e manda una
notifica Telegram (con foto, prezzo e link) appena compare un annuncio nuovo
che corrisponde a quello che cerchi.

## Come funziona

- Ogni ~60 secondi (configurabile) rifà le ricerche che hai impostato,
  ordinate per "più recenti".
- Al primo giro memorizza gli annunci già esistenti e non avvisa: da lì in poi
  avvisa solo per annunci pubblicati **dopo** l'avvio.
- Quando un annuncio nuovo passa i tuoi filtri (testo, prezzo, taglia,
  condizioni) ricevi il messaggio Telegram con il link diretto.

## Configurazione (una volta sola, ~5 minuti)

### 1. Crea il bot Telegram

1. Apri Telegram, cerca **@BotFather** e premi Avvia.
2. Manda il comando `/newbot`.
3. Scegli un nome (es. "Il mio monitor Vinted") e uno username che finisce
   con `bot` (es. `monitor_andrea_bot`).
4. BotFather ti dà un **token** tipo `123456789:AAE3x...`: copialo.
5. Apri il file `config.json` e incollalo in `telegram_bot_token`
   (tra le virgolette).

### 2. Collega la tua chat

Il campo `telegram_chat_id` lo puoi lasciare vuoto: lo script lo scopre da
solo. Ti basta, **dopo** aver salvato il token:

1. Cerca su Telegram il bot che hai appena creato (per nome) e aprilo.
2. Premigli "Avvia" o mandagli un messaggio qualsiasi (es. `/start`).
3. Avvia lo script (vedi sotto): troverà il tuo chat_id da solo e lo
   salverà in `config.json`.

### 3. Imposta cosa cercare

In `config.json`, dentro la lista `ricerche`, ogni ricerca ha questi campi:

| Campo               | Significato                                                                              | Esempio                  |
|---------------------|------------------------------------------------------------------------------------------|--------------------------|
| `nome`              | Nome che vedi tu nei messaggi                                                            | `"Console Wii U"`        |
| `testo`             | Parole cercate su Vinted (come nella barra di ricerca del sito)                           | `"wii u"`                |
| `catalogo_id`       | Categoria Vinted: esclude giochi/accessori già a monte. `3025` = Console. `null` = tutte   | `3025`                   |
| `prezzo_min`        | Prezzo minimo in euro, oppure `null` per nessun limite                                    | `20`                     |
| `prezzo_max`        | Prezzo massimo in euro, oppure `null`                                                    | `50`                     |
| `parole_alternative`| Nel titolo deve esserci **almeno una** di queste parole (ideale per grafie diverse)       | `["wii u", "wiiu"]`      |
| `parole_chiave`     | Parole che **devono esserci tutte** nel titolo dell'annuncio (una in meno = scartato)     | `["air max", "90"]`      |
| `escludi`           | Parole che, se presenti nel titolo, scartano l'annuncio                                   | `["gamepad", "kids"]`    |
| `taglie`            | Taglie accettate, qualunque corrispondenza basta                                          | `["42", "42.5"]`         |
| `condizioni`        | Condizioni accettate (corrispondenza parziale)                                            | `["nuovo", "ottime"]`    |

Nota: la ricerca di Vinted (`testo`) cerca già anche dentro marche ecc.;
i filtri `parole_alternative` / `parole_chiave` / `escludi` agiscono sul
**titolo** dell'annuncio, perché nei risultati di ricerca la descrizione
completa non è inclusa.

Come trovare altri `catalogo_id`: naviga le categorie del sito (es.
"Videogiochi e console" → "Console") e guarda l'indirizzo della pagina:
`vinted.it/catalog/3025-consoles` → l'ID è il numero dopo `/catalog/`.
Alcuni utili: 3025 = Console, 3026 = Giochi, 3002 = Videogiochi e console
(categoria intera).

Puoi mettere più di una ricerca: duplica il blocco `{ ... }` separandolo
con una virgola.

Esempio completo:

```json
"ricerche": [
  {
    "nome": "Console Wii U",
    "testo": "wii u",
    "catalogo_id": 3025,
    "prezzo_min": 20,
    "prezzo_max": 50,
    "parole_alternative": ["wii u", "wiiu", "wii-u"],
    "parole_chiave": [],
    "escludi": ["gamepad", "controller", "manette", "boîte vide"],
    "taglie": [],
    "condizioni": []
  },
  {
    "nome": "Air Max 90",
    "testo": "nike air max 90",
    "catalogo_id": null,
    "prezzo_min": 30,
    "prezzo_max": 80,
    "parole_alternative": [],
    "parole_chiave": ["air max"],
    "escludi": ["kids", "junior", "scuola"],
    "taglie": ["42", "42.5"],
    "condizioni": ["ottime", "nuovo"]
  }
]
```

Altre impostazioni in cima al file:

- `intervallo_secondi`: ogni quanto ripetere il controllo (minimo 30;
  60 è un buon compromesso tra rapidità e gentilezza verso il sito).
- `risultati_per_ricerca`: quanti annunci scaricare per ogni ricerca
  (max 96; 30 basta per ricerche normali).

## Avvio

Doppio clic su **`avvia.bat`**. Lascia la finestra aperta: finché è aperta,
il monitor lavora.

Per verificare i filtri senza aspettare e senza mandare notifiche:

```
.venv\Scripts\python.exe monitor.py prova
```

fa un solo giro e stampa per ogni annuncio trovato se passa o no i filtri.

Per fermare: chiudi la finestra o `Ctrl+C`.

## Usarlo su un altro PC

La cartella e' autosufficiente: puoi spostarla dove vuoi con una chiavetta
USB, una cartella condivisa o un zip. Il PC nuovo ha bisogno solo di
**Python installato** (da python.org, spuntando "Add python.exe to PATH").

Procedura: chiudi il monitor sul PC attuale, copia la cartella `vinted-monitor`
intiera (anche `.venv`: se non funziona viene ricostruito da solo), apri la
copia sul PC nuovo e fai doppio clic su `avvia.bat`. Al primo avvio prepara
l'ambiente da solo in circa un minuto.

Due note:

- **Porta dietro anche `visti.json`**: e' la memoria degli annunci gia' visti.
  Se lo copi, il monitor sul PC nuovo riprende esattamente da dove era rimasto
  e non ti perdi gli annunci pubblicati nel frattempo. Senza, il nuovo PC parte
  con una nuova memorizzazione di partenza.
- **Un PC alla volta**: se lo lasci acceso su due PC insieme riceverai due
  notifiche per lo stesso annuncio. Nessun danno, solo doppioni.

## File del progetto

```
vinted-monitor/
├── avvia.bat          avvio con doppio clic
├── config.json        le tue ricerche e le impostazioni Telegram
├── monitor.py        lo script
├── requirements.txt  dipendenze (già installate in .venv)
├── visti.json         (creato da solo) annunci già visti
├── monitor.log        (creato da solo) registro dell'attività
└── .venv/            ambiente Python (già pronto)
```

## Avvertenze oneste

- Vinted non offre un'API pubblica: lo script usa la stessa API del sito
  tramite la libreria open-source `vinted-scraper`. Se Vinted la cambia,
  di solito la libreria si aggiorna (`pip install --upgrade vinted-scraper`
  nell'ambiente `.venv`).
- L'accesso automatizzato è scoraggiato dal regolamento di Vinted: tieni
  l'intervallo a 60 secondi o più, usa poche ricerche, non lasciarlo
  girare 24/7 per giorni interi. Un impiego smodato può portare a blocchi
  temporanei del tuo indirizzo IP.
- Il computer dev'essere accesso e la finestra aperta perché il monitor
  funzioni. Per farlo girare di notte valuta di usare l'opzione
  "impedisci spegnimento" delle opzioni risparmio energia.
- I primi avvisi arrivano solo per gli articoli pubblicati **dopo** l'avvio.
