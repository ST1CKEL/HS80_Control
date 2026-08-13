# Architektur

## Prozesse

```text
hs80-control ─┐
hs80ctl ──────┼─ D-Bus ─ hs80d ─ hidapi ─ /dev/hidraw (Interface 3)
              │             ├── amixer ─ ALSA USB controls
              │             └── systemd --user ─ HS80 Spatial PipeWire
              └──────────────────────────────────────────────────────
```

`hs80d` läuft in der Benutzersitzung. Dadurch kann der Dienst gleichzeitig auf
die durch `uaccess` freigegebene hidraw-Datei, die ALSA-Regler und die
PipeWire-Sitzung zugreifen. Ein Root- oder Systemdienst ist nicht notwendig.

## Geräteauswahl und Mehrgerätebetrieb

Der Daemon sucht ausschließlich HID-Interface 3 des Receivers `1b1c:0a6b` und
verwaltet pro Benutzersitzung genau einen Receiver. Sind mehrere passende
Receiver angeschlossen, wird derzeit der erste nach hidraw-Gerätenamen
sortierte Kontrollknoten verwendet; eine explizite Auswahl per Konfiguration,
D-Bus, CLI oder Oberfläche existiert nicht.

Soweit vorhanden, bindet die USB-Seriennummer die ALSA-Regler an den
ausgewählten Receiver. Die Spatial-Konfiguration bricht bei mehreren passenden
physischen HS80-Sinks bewusst ab. Für einen eindeutigen Betrieb sollte deshalb
nur ein kompatibler Receiver angeschlossen sein.

## HID-Serialisierung

Receiverkommandos, Headsetkommandos, RGB-Frames, Heartbeats und spontane
Ereignisse teilen sich dasselbe HID-Handle. Mehrere Leser würden Antworten
einander wegnehmen. Deshalb besitzt ausschließlich der Thread `hs80-io` das
Handle.

Der Thread führt folgende Aufgaben seriell aus:

1. USB-Hotplug und Berechtigungen prüfen
2. Receiver und gekoppeltes Headset initialisieren
3. Anforderungen aus einer threadsicheren Queue bearbeiten
4. alle zehn Sekunden beide Endpunkte per Heartbeat prüfen
5. Batterie-, Lade-, Mute- und Verbindungsereignisse verteilen
6. aktive RGB-Effekte mit maximal 25 Frames pro Sekunde schreiben
7. beim Beenden Headset und Receiver in den Hardwaremodus zurücksetzen

Jeder Schreibbefehl wartet auf genau eine Antwort. Dazwischen eintreffende
Report-ID-3-Ereignisse werden verarbeitet und nicht als Antwort verwendet.
Headsetantworten müssen zusätzlich den ersten Opcode spiegeln, damit eine
verspätete Antwort nach einem Timeout nicht den nächsten Befehl bestätigt.
Receiverantworten haben ein anderes Nutzdatenformat; nach einem Receiver-
Timeout wird deshalb die Verbindung verworfen und neu geöffnet. Paketlängen,
Endpunkte, Farben und Wertebereiche werden vor dem Schreiben begrenzt.

## D-Bus

- Busname: `io.github.hs80control.Daemon`
- Objekt: `/io/github/hs80control/Daemon`
- Interface: `io.github.hs80control.Daemon`

Wichtige Methoden:

- `Refresh()`
- `SetRgb(mode, brightness, logo, indicator, microphone)`
- `UpdateRgb(mode, brightness, logo, indicator, microphone)` für atomare
  Teiländerungen; leere Farben und negative Helligkeit bedeuten unverändert
- `SetSleepTimer(minutes)`
- `SetSidetone(enabled, level_db)`
- `SetMicrophoneGain(level_db)`
- `SetMicrophoneMuted(muted)`
- `ConfigureSpatial(sofa_file)`
- `SetSpatialEnabled(enabled)`
- `SetSpatialMakeDefault(enabled)`

Zustandsänderungen werden als standardkonformes
`org.freedesktop.DBus.Properties.PropertiesChanged` signalisiert.
HID/ALSA-Aufrufe und die langsameren Spatial-Aufrufe besitzen getrennte
Aufruf-Sperren. Eine PipeWire-Neukonfiguration blockiert dadurch keine
Headset- oder Mikrofonaktion.

## Persistenz

RGB-, Schlaf- und Spatial-Einstellungen liegen atomar geschrieben in
`~/.config/hs80-control/config.json`. Eine Einstellung wird beim nächsten
Verbinden nur automatisch angewendet, nachdem der Benutzer sie mindestens
einmal explizit gesetzt hat. Der erste Dienststart verändert daher keine
Beleuchtung und keinen Schlaf-Timer.

## Audio

Sidetone und Mikrofon-Gain sind standardisierte USB-Audio-Regler. Der Dienst
ermittelt die ALSA-Karte bei jeder Operation über `/proc/asound/card*/usbid`
und nicht über eine instabile Kartennummer.

Der Spatial-Graph läuft als eigener PipeWire-Client. Seine Stereoausgabe wird
über `target.object` fest an den physischen HS80-Sink gebunden. Damit kann der
Graph weder rekursiv in sich selbst routen noch bei getrenntem Headset auf
Lautsprecher ausweichen.

SOFA-Datei, generierter Graph und gespeicherte Einstellung werden gemeinsam
ausgetauscht. Scheitert ein Neustart oder Schreibvorgang, stellt der Manager
die vorherige funktionsfähige Konfiguration wieder her. Bei mehreren passenden
physischen HS80-Sinks bricht er eindeutig ab, statt zufällig den ersten zu
wählen. `SpatialEnabled` wird erst wahr, wenn Dienst und virtueller Sink bereit
sind.

## Sicherheitsgrenzen

- udev gewährt nur Interface 3 Zugriff.
- Interface 4 und alle Audiointerfaces bleiben bei den Kernelmodulen.
- keine USB-Interface-Claims und kein Detach von `snd-usb-audio`
- keine Pairing-, Bootloader- oder Firmware-Schreibbefehle
- keine Netzwerkports oder Telemetrie
- D-Bus ausschließlich in der lokalen Benutzersitzung
- PipeWire-Konfiguration akzeptiert nur vorhandene `.sofa`-Dateien
