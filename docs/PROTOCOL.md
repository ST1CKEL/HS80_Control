# HS80-Protokollnotizen

## Geltungsbereich

Bestätigte Zielhardware ist der Corsair HS80 RGB Wireless Receiver mit der
USB-ID `1b1c:0a6b` und einem gekoppelten Headset mit interner Produkt-ID
`0a69`. Die Produkt-ID `0a71` wird von der Implementierung akzeptiert, ist
aber noch nicht an echter Hardware verifiziert und gilt daher als
experimentell.

Diese Protokollnotizen gelten nicht für HS80 MAX, HS80 RGB USB/Wired,
Xbox- oder Bluetooth-Varianten oder für Receiver mit anderen USB-IDs.

## Headset am Ladekabel (`1b1c:0a6a`)

Hängt das Headset an seinem USB-C-Kabel, meldet es sich als eigenes Gerät.
An echter Hardware gemessen (Firmware-Stand des Receivers 5.9.130):

| Eigenschaft | Wert |
| --- | --- |
| `bNumConfigurations` | 1 |
| `bNumInterfaces` | 1 |
| `bInterfaceClass` | `03` HID |
| `MaxPower` | 150 mA |

Der Report-Deskriptor dieser Schnittstelle enthält Vendor-Page `0xff58`
(Report `0x58`, 64 Byte, Firmware-Update) sowie eine Consumer-Control-
Collection für die Lautstärketasten. Die Steuerseite `0xff42` fehlt, ebenso
jede Audio-Class-Schnittstelle; entsprechend entsteht keine ALSA-Karte.

Über das Kabel sind daher weder Akku, RGB, Sidetone noch Mikrofonstatus
adressierbar. Der Dienst erkennt das Gerät ausschließlich über sysfs, um den
Zustand erklären zu können, und öffnet den zugehörigen hidraw-Knoten nie.
Die Messung entstand bei kritisch leerem Akku; ob ein geladenes Headset
denselben Deskriptorsatz meldet, ist nicht verifiziert.

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
4. falls diese Legacy-Liste leer ist, aktive Funkkanäle über Eigenschaft `02 36`
   ermitteln und Vendor-/Produkt-ID mit `02 11`/`02 12` direkt abfragen
5. ein Corsair-HS80 mit Produkt-ID `0a69` (bestätigt) oder `0a71`
   (experimentell) auswählen
6. Headset-Heartbeat `12`
7. Headset-Firmware, Akku und Mikrofonstatus lesen
8. Headset in Softwaremodus setzen und RGB-Endpunkt öffnen

Der gekoppelte Endpoint wird nicht hart codiert.
Vor dem Öffnen der RGB-Ressource schließt der Daemon den idempotenten Handle 0,
damit ein nach einem unvollständigen Client-Abbruch verbliebener Handle nicht
als erfolgreicher Start missverstanden wird.

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

### Stumm-Suppression der Firmware

Bei Firmware 5.8.48 (bestätigt) unterdrückt das Headset die komplette
Software-Beleuchtung, solange der Mikrofonarm hochgeklappt (stumm) ist.
Farbwrites werden dann zwar mit Status `00` bestätigt, haben aber keine
sichtbare Wirkung; der Mute-Indikator kann in diesem Zustand ebenfalls nicht
erscheinen. Der Daemon wendet das gespeicherte Profil daher über das
Mikrofon-Ereignis (`0x8e`/`0xa6`) erneut an, sobald der Arm heruntergeklappt
wird.

## Statuswerte

- Antworten verwenden `01 <TT-08> <erstes Kommandobyte> <Status> <Payload...>`.
  Eine echte Receiver-Firmwareantwort auf `02 08 02 13 ...` war
  `01 00 02 00 05 09 82 00 ...` und ergibt Firmware `5.9.130`.
- Ein Statusbyte ungleich null ist eine Geräteablehnung und kein gültiger
  Payload. Beim Legacy-Ressourcen-Read wurde auf diesem Receiver Status `02`
  beobachtet; die Endpoint-Erkennung fällt dann auf Eigenschaft `02 36` zurück.
- Receiver-Firmware: Major/Minor in Bytes 4 und 5, Patch als Little-Endian in
  Bytes 6 und 7
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
