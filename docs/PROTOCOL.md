# HS80-Protokollnotizen

Zielgerät: Corsair HS80 RGB Wireless Receiver `1b1c:0a6b`.

## USB-Aufteilung

| Interface | Klasse | Aufgabe |
| --- | --- | --- |
| 0 | USB Audio Control | Mute, Gain, Sidetone und Ausgangslautstärke |
| 1 | USB Audio Streaming | Mono-Mikrofon, Endpoint `0x83 IN` |
| 2 | USB Audio Streaming | Stereoausgabe, Endpoint `0x03 OUT` |
| 3 | HID | Corsair-Steuerprotokoll, `0x81 IN` / `0x01 OUT` |
| 4 | HID | Rad- und Eingabeereignisse, `0x82 IN` / `0x02 OUT` |

Interface 3 enthält unter anderem Usage Page `0xff42`. Output-Report-ID `0x02`
und Input-Report-IDs `0x01` beziehungsweise `0x03` sind jeweils insgesamt 64
Byte lang.

## hidapi-Framing

Bei `hid_write()` ist das erste Byte des Puffers die Report-ID. Der lokale
HID-Deskriptor deklariert für Output-Report-ID `0x02` genau 63 Datenbytes;
deshalb schreibt der Dienst insgesamt 64 Byte. Ein zusätzliches Nullbyte ist
nur für Geräte ohne nummerierte Reports vorgesehen und darf hier nicht vor
`0x02` stehen:

```text
02 TT CC CC ... PP PP ... 00
│  │  │         │
│  │  │         └─ optionale Nutzdaten
│  │  └─────────── Kommando
│  └────────────── Zielendpunkt
└───────────────── HID-Report-ID
```

`TT=08` adressiert den Receiver. Der Headsetendpunkt wird aus der gekoppelten
Geräteliste ermittelt und ist bei einem einzelnen Gerät üblicherweise `09`.

## Initialisierung

1. Receiver-Firmware mit `02 13` lesen
2. Receiver mit `01 03 00 02` in Softwaremodus setzen
3. Ressource `24` öffnen und gekoppelte Geräte lesen
4. ein gekoppeltes HS80 mit Produkt-ID `0a69` oder `0a71` auswählen
5. Headset-Heartbeat `12`
6. Headset-Firmware, Akku und Mikrofonstatus lesen
7. Headset in Softwaremodus setzen und RGB-Endpunkt öffnen

Der gekoppelte Endpoint wird nicht hart codiert.

## Verwendete Kommandos

| Ziel | Zweck | Kommando |
| --- | --- | --- |
| beide | Softwaremodus | `01 03 00 02` |
| beide | Hardwaremodus | `01 03 00 01` |
| beide | Firmware | `02 13` |
| beide | Heartbeat | `12` |
| Headset | Akku | `02 0f` |
| Headset | Mikrofonstatus | `02 a6` |
| Headset | RGB öffnen | `0d 00 01` |
| Headset | RGB schreiben | `06 00` |
| Headset | Sleep-Endpunkt | `01 0d 00` |
| Headset | Sleep-Dauer | `01 0e 00` |

Receiverressourcen verwenden `05 01 01` zum Schließen, `0d 01` zum Öffnen,
`09 01` zum Initiieren und `08 01` zum Lesen.

## RGB

Die neun Farbbytes sind planar angeordnet:

```text
R_logo R_indicator R_mic G_logo G_indicator G_mic B_logo B_indicator B_mic
```

Vor den Daten stehen Länge als Little Endian und zwei reservierte Nullbytes:

```text
09 00 00 00 <neun Farbbytes>
```

Bei physisch hochgeklapptem Mikrofon wird die Mikrofonzone rot dargestellt,
sofern der Mute-Indikator aktiviert ist.

## Statuswerte

- Akkuantwort: Little-Endian-Zehntelprozent in Bytes 4 und 5
- Mikrofonantwort: Byte 4, `0=aktiv`, `1=stumm`
- Firmware des Headsets: Bytes 4 bis 6
- Sleep-Dauer: Millisekunden als Little-Endian-`uint32`

Bekannte Report-ID-3-Ereignisse:

- Event `0x0f`: Akku, Zehntelprozent in Bytes 5 und 6
- Event `0x10`: Ladestatus in Byte 5
- Event `0x36`: Verbindungsstatus in Byte 5
- Event `0x8e` oder `0xa6`: Mikrofonstatus in Byte 5

Der Ladestatus ist weniger umfassend auf verschiedenen Firmwareständen
validiert und bleibt deshalb als unbekannt (`-1`), bis ein Ereignis eintrifft.

## ALSA statt HID

Das HS80 exponiert folgende Standardregler:

- `Sidetone Playback Switch`
- `Sidetone Playback Volume`, `-42` bis `+4 dB`
- `Mic Capture Switch`
- `Mic Capture Volume`, `-36` bis `0 dB`
- `Headset Playback Switch/Volume`

Sidetone und Mikrofon-Gain werden deshalb nicht über proprietäre HID-Befehle
gesteuert.

## Quellen und Abgleich

Die Protokollfakten wurden gegen folgende öffentlich verfügbare Arbeiten und
gegen die lokalen USB-/HID-Deskriptoren abgeglichen:

- OpenLinkHub: <https://github.com/jurkovic-nikola/OpenLinkHub>
- HeadsetControl HS80-Analyse: <https://github.com/Sapd/HeadsetControl/issues/178>
- ckb-next-Geräteanfrage: <https://github.com/ckb-next/ckb-next/issues/964>
