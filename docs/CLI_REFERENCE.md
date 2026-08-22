# hs80ctl — Kommandozeilenreferenz & Skriptanleitung

`hs80ctl` ist das offizielle CLI-Werkzeug zur Steuerung und Automatisierung des Corsair HS80 RGB Wireless unter Linux. Es kommuniziert asynchron über D-Bus mit dem Hintergrunddienst `hs80d`.

---

## 1. Allgemeine Syntax

```bash
hs80ctl [GLOBALE_OPTIONEN] <BEFEHL> [BEFEHLS_OPTIONEN]
```

### Globale Optionen

- `--json`: Gibt die Programmausgabe als strukturiertes, maschinenlesbares JSON auf `stdout` aus. Fehler werden als JSON auf `stderr` ausgegeben. Kann vor oder nach dem Unterbefehl angegeben werden.
- `--version`: Gibt die Version von `hs80ctl` aus.
- `-h, --help`: Zeigt die Hilfe und verfügbare Unterbefehle an.

---

## 2. Befehlsreferenz

### `status`
Gibt den aktuellen Verbindungszustand, Akkustand, Firmware-Versionen, RGB-Modus, Sidetone- und Spatial-Status aus.

```bash
hs80ctl status
hs80ctl status --json
```

**JSON-Beispielausgabe:**
```json
{
  "AudioError": "",
  "BatteryPercent": 98,
  "Charging": 0,
  "ConnectionMode": "wireless",
  "Firmware": "5.8.48",
  "HeadsetConnected": true,
  "HidPath": "/dev/hidraw3",
  "LastError": "",
  "MicrophoneCaptureMuted": false,
  "MicrophoneGainDb": -6.0,
  "MicrophoneMuted": 0,
  "MixerAvailable": true,
  "ReceiverConnected": true,
  "ReceiverFirmware": "5.9.130",
  "ReceiverSerial": "1b1c0a6b...",
  "RgbBrightness": 50,
  "RgbIndicator": "#00bfff",
  "RgbLogo": "#00bfff",
  "RgbMicrophone": "#00ffff",
  "RgbMode": "static",
  "Serial": "0a69...",
  "SidetoneDb": -18.0,
  "SidetoneEnabled": true,
  "SleepMinutes": 15,
  "SpatialEnabled": false,
  "SpatialError": "",
  "SpatialMakeDefault": true,
  "SpatialSofaFile": "",
  "Version": "0.3.1",
  "WiredHeadsetPresent": false
}
```

---

### `reconnect`
Baut die USB-HID-Sitzung zum Transceiver neu auf und sucht sofort nach einem eingeschalteten Headset.

```bash
hs80ctl reconnect
```

---

### `refresh`
Erzwingt eine sofortige Aktualisierung der Akku-, Firmware- und ALSA-Mixer-Werte beim Headset.

```bash
hs80ctl refresh
```

---

### `doctor`
Überprüft das System auf vorhandene USB-Knoten, Berechtigungen, ALSA-Mixer-Regler, PipeWire-Sinks und SOFA-Bibliotheken.

```bash
hs80ctl doctor
```

---

### `rgb`
Konfiguriert den Beleuchtungsmodus, die Helligkeit und die Farben einzelner Zonen.

```bash
hs80ctl rgb <off | static | pulse | rainbow> [Optionen]
```

**Optionen:**
- `--brightness <0..100>`: Helligkeit in Prozent.
- `--logo <#RRGGBB>`: Farbe des beleuchteten Corsair-Logos auf den Ohrmuscheln.
- `--indicator <#RRGGBB>`: Farbe der Status-LED am Headset.
- `--microphone <#RRGGBB>`: Farbe des LED-Rings an der Mikrofonspitze.

**Beispiele:**
```bash
# Beleuchtung aus
hs80ctl rgb off

# Statisches Eisblau mit 40% Helligkeit
hs80ctl rgb static --brightness 40 --logo '#00bfff' --indicator '#00bfff' --microphone '#00bfff'

# Pulsieren in Lila
hs80ctl rgb pulse --brightness 80 --logo '#bf00ff'

# Regenbogen-Farbverlauf
hs80ctl rgb rainbow --brightness 100
```

---

### `sleep`
Stellt die Zeitspanne ein, nach der sich das Headset bei Nichtbenutzung automatisch abschaltet.

```bash
hs80ctl sleep <0..90>
```

- `0`: Deaktiviert den Sleep-Timer (Headset bleibt dauerhaft an).
- `1..90`: Automatische Abschaltung nach der angegebenen Minutenzahl.

---

### `sidetone`
Steuert den hardwarebasierten, latenzfreien Mikrofon-Mithörton (Sidetone) über ALSA.

```bash
hs80ctl sidetone <on | off> [--db <-42..4>]
```

**Beispiele:**
```bash
hs80ctl sidetone on --db -12.0
hs80ctl sidetone off
```

---

### `mic-gain`
Stellt die Hardware-Mikrofonverstärkung im Bereich von `-36 dB` bis `0 dB` ein.

```bash
hs80ctl mic-gain <-36..0>
```

---

### `mic-mute`
Schaltet die ALSA-Aufnahmestummschaltung des Mikrofons.

```bash
hs80ctl mic-mute on    # Stumm
hs80ctl mic-mute off   # Aktiv
```

---

### `spatial`
Verwaltet die binaurale 7.1 PipeWire-Surround-Konfiguration.

```bash
# SOFA-HRTF Datei importieren und zuweisen:
hs80ctl spatial configure /pfad/zur/hrtf.sofa

# Festlegen, ob Spatial bei Aktivierung zur Standard-Audioausgabe wird:
hs80ctl spatial default <on | off>

# Spatial 7.1 aktivieren / deaktivieren:
hs80ctl spatial on
hs80ctl spatial off
```

---

## 3. Shell-Skripte & Desktop-Integration

### Polybar / Waybar Akku-Modul

```bash
#!/usr/bin/env bash
# ~/.config/waybar/scripts/hs80-battery.sh

STATUS=$(hs80ctl status --json 2>/dev/null)
if [ $? -ne 0 ]; then
    echo '{"text": "Offline", "class": "disconnected"}'
    exit 0
fi

CONNECTED=$(echo "$STATUS" | jq -r '.HeadsetConnected')
BATTERY=$(echo "$STATUS" | jq -r '.BatteryPercent')
CHARGING=$(echo "$STATUS" | jq -r '.Charging')

if [ "$CONNECTED" = "true" ]; then
    if [ "$CHARGING" = "1" ]; then
        echo "{\"text\": \"⚡ ${BATTERY}%\", \"class\": \"charging\", \"percentage\": ${BATTERY}}"
    else
        echo "{\"text\": \"🎧 ${BATTERY}%\", \"class\": \"connected\", \"percentage\": ${BATTERY}}"
    fi
else
    echo '{"text": "🎧 Offline", "class": "offline"}'
fi
```
