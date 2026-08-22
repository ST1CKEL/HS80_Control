# Corsair HS80 RGB Wireless — Protokollspezifikation & Reverse-Engineering

Dieses Dokument dokumentiert die durch Protokollanalyse, USB-Sniffing und Reverse-Engineering ermittelten Kommunikationsstrukturen des **Corsair HS80 RGB Wireless**.

---

## 1. Hardware-Kennungen & USB-Deskriptoren

### USB-Identifikatoren

| Gerät / Modus | Vendor ID | Product ID | Interfaces | Audio-Klasse | Steuerprotokoll |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Wireless Transceiver (Dongle)** | `0x1b1c` | `0x0a6b` | 5 (0..4) | Ja (0, 1, 2) | Ja (Interface 3) |
| **Headset am USB-Kabel (eingeschaltet)** | `0x1b1c` | `0x0a69` | 4 (0..3) | Ja (0, 1, 2) | Ja (Interface 3) |
| **Headset am Ladekabel (ausgeschaltet)** | `0x1b1c` | `0x0a6a` | 1 (0) | Nein | Nein (nur Vendor-Page `0xff58` / Update) |
| **Interne Headset-PID (Funkbetrieb)** | `0x1b1c` | `0x0a69` / `0x0a71` | — | — | Adressiert über Endpoint `0x09`..`0x0f` |

### USB-Interface-Aufteilung (Transceiver `1b1c:0a6b`)

```text
Interface 0: USB Audio Control    -> Lautstärke, Mute, Sidetone & Mic-Gain (Kernel snd-usb-audio)
Interface 1: USB Audio Streaming  -> Mono-Mikrofon In (Endpoint 0x83 IN)
Interface 2: USB Audio Streaming  -> Stereo-Kopfhörerausgabe Out (Endpoint 0x03 OUT)
Interface 3: HID Vendor Control   -> Corsair Bragi Protokoll (Usage Page 0xff42, 0x81 IN / 0x01 OUT)
Interface 4: HID Consumer Control -> Lautstärkerad & Multimediatasten (0x82 IN / 0x02 OUT)
```

---

## 2. HID-Report-Framing (Interface 3)

Die Kommunikation auf Interface 3 erfolgt über 64 Byte lange HID-Reports.

### Output-Report (Host -> Headset / Transceiver)

```text
Byte:   00       01       02       03       04 .. 63
      +--------+--------+--------+--------+-------------------------+
      |  0x02  | Target | Cmd[0] | Cmd[1] | Optional Payload / Pad  |
      +--------+--------+--------+--------+-------------------------+
       ReportID  Ziel     Kommando-Opcode  Nutzdaten & Nullen bis 64B
```

- **Byte 0 (`0x02`)**: HID Output Report ID.
- **Byte 1 (`Target`)**:
  - `0x08`: Adressiert den USB-Receiver (oder das Headset direkt im Kabelmodus).
  - `0x09` .. `0x0F`: Adressiert das gekoppelte Funk-Headset über den jeweiligen Funkkanal.
- **Bytes 2..3 (`Command`)**: 1- bis 2-Byte Opcode.
- **Bytes 4..63**: Befehlsspezifische Parameter, mit Nullen auf 64 Byte aufgefüllt.

---

### Input-Report (Antwort auf Befehle: Gerät -> Host)

```text
Byte:   00       01       02       03       04 .. 63
      +--------+--------+--------+--------+-------------------------+
      |  0x01  | Ch-Idx | EchoCmd| Status | Antwortdaten ...        |
      +--------+--------+--------+--------+-------------------------+
       ReportID  Kanal    Opcode   00=OK    Nutzdaten (z.B. Akku, FW)
```

- **Byte 0 (`0x01`)**: HID Input Report ID für synchrone Antworten.
- **Byte 1 (`Channel Index`)**: Zero-based Zielkanal (`0x00` = Target `0x08`, `0x01` = Target `0x09`).
- **Byte 2 (`EchoCmd`)**: Spiegelt das erste Byte des gesendeten Kommandos wider.
- **Byte 3 (`Status`)**:
  - `0x00`: Erfolg.
  - `> 0x00` (z. B. `0x02`, `0x06`): Fehler / Ablehnung durch die Firmware.

---

### Spontane Event-Reports (Report ID `0x03`)

Das Headset sendet Statusänderungen asynchron ohne vorherige Anfrage über Report ID `0x03`:

```text
Byte:   00       01       02       03       04       05       06 .. 63
      +--------+--------+--------+--------+--------+--------+----------------+
      |  0x03  | Target | 0x01   | EvType | 0x00   | Value1 | Value2 / Pad   |
      +--------+--------+--------+--------+--------+--------+----------------+
```

| Event Type (Byte 3) | Bedeutung | Datenformat |
| :--- | :--- | :--- |
| `0x0F` | **Akku-Update** | Bytes 5..6: Zehntelprozent als Little-Endian `uint16` (z. B. `0x03ca` = 970 = 97.0 %) |
| `0x10` | **Ladestatus** | Byte 5: `0x00` = Batteriebetrieb, `0x01` = Headset wird geladen |
| `0x36` | **Verbindungsstatus** | Byte 5: Funkkanal-Statusbitfield |
| `0x8E` / `0xA6` | **Mikrofon-Arm-Schalter** | Byte 5: `0x00` = Arm unten (Aktiv), `0x01` = Arm oben (Stumm) |

---

## 3. Kommandotabelle

| Zweck | Ziel | Opcode | Payload | Bemerkung |
| :--- | :---: | :--- | :--- | :--- |
| **Softwaremodus aktivieren** | Beide | `01 03 00 02` | — | Erforderlich für Software-RGB & Abfragen |
| **Hardwaremodus aktivieren** | Beide | `01 03 00 01` | — | Setzt Gerät in Standalone-Modus zurück |
| **Firmware-Version lesen** | Beide | `02 13` | — | Liefert Major, Minor, Patch |
| **Heartbeat / Keepalive** | Beide | `12` | — | *Achtung:* Im USB-Direktkabelbetrieb nicht senden! |
| **Akkustand abfragen** | Headset | `02 0F` | — | Zehntelprozent (0..1000) |
| **Mikrofonstatus abfragen** | Headset | `02 A6` | — | `0` = Aktiv, `1` = Stumm |
| **RGB-Ressource öffnen** | Headset | `0D 00 01` | — | Öffnet Beleuchtungskanal 0 |
| **RGB-Ressource schließen** | Headset | `05 01 00` | — | Schließt Beleuchtungskanal 0 |
| **RGB-Farben schreiben** | Headset | `06 00` | `09 00 00 00 <9 Bytes>` | Planare RRR-GGG-BBB Farbdaten |
| **Sleep-Timer Endpunkt** | Headset | `01 0D 00` | `01` (an) / `00` (aus) | Aktiviert Sleep-Timeout |
| **Sleep-Timer Dauer** | Headset | `01 0E 00` | Millisekunden (`uint32` LE) | z. B. 15 min = `00 eb 0d 00` |

---

## 4. Planare RGB-Farbkodierung

Die RGB-Daten für die drei getrennten Zonen (*Logo*, *Statusanzeige*, *Mikrofon-LED*) werden in einem planaren Blockformat übertragen:

```text
Payload-Header: 09 00 00 00 (Länge 9 Bytes Little-Endian + 2 Nullbytes)
Farbdaten:
  Byte 0: Rot-Kanal Logo
  Byte 1: Rot-Kanal Statusanzeige
  Byte 2: Rot-Kanal Mikrofon-LED
  Byte 3: Grün-Kanal Logo
  Byte 4: Grün-Kanal Statusanzeige
  Byte 5: Grün-Kanal Mikrofon-LED
  Byte 6: Blau-Kanal Logo
  Byte 7: Blau-Kanal Statusanzeige
  Byte 8: Blau-Kanal Mikrofon-LED
```

---

## 5. Firmware-Eigenheiten & Workarounds

### 1. Mute-Suppression der Firmware
Bei Firmware-Stand 5.8.48 unterdrückt das Headset jegliche Software-RGB-Updates, solange der Mikrofonarm hochgeklappt (stummgeschaltet) ist. Schreibzugriffe werden zwar bestätigt, aber hardwareseitig nicht sichtbar dargestellt.
- **Workaround im Daemon**: Bei Eintreffen des Mikrofon-Herunterklapp-Events (`0x8e`/`0xa6` mit Wert `0`) wird das gespeicherte RGB-Profil automatisch erneut an das Headset übertragen.

### 2. Heartbeat im Direktkabelbetrieb
Wird das Headset per USB-Kabel angeschlossen (`1b1c:0a69`), führt das Senden des drahtlosen Heartbeats `12` zu keiner Antwort und führt bei Wiederholung zum internen USB-Reset des Headsets.
- **Workaround im Daemon**: Im Kabelmodus wird kein Heartbeat `12` gesendet; als periodische Liveness-Prüfung dient das Auslesen der Akkudaten (`02 0f`).
