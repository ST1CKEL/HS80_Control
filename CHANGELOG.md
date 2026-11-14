# Änderungsprotokoll

Alle nennenswerten Änderungen an HS80 Control. Das Format folgt
[Keep a Changelog](https://keepachangelog.com/de/1.1.0/), die Versionen folgen
[Semantic Versioning](https://semver.org/lang/de/).

## [0.7.1] – 2026-11-14

### Geändert
- „Über HS80 Control" nennt Stickelbroeck Labs als Entwickler, mit Logo und Link zu stickelbroeck.com. Auch die AppStream-Metadaten und das README führen den Entwickler auf.

## [0.7.0] – 2026-11-14

### Neu
- RGB-Modus „Farbwechsel" (`cycle`): alle Zonen wandern weich durch die drei eigenen Farben.
- Einstellbares Tempo (1–5) für Pulsieren, Regenbogen und Farbwechsel.
- Stummanzeige in der Oberfläche schaltbar, mit frei wählbarer Farbe.
- Beleuchtung bei niedrigem Akkustand wahlweise dimmen oder ausschalten.
- Sofortvorschau: Änderungen auf der RGB-Seite wirken ohne „Anwenden".
- RGB-Profile speichern, laden und löschen.
- `hs80ctl rgb` mit `--speed`, `--mute-indicator`, `--mute-color` und `--battery-saver`; D-Bus-Methode `UpdateRgbOptions` und die Eigenschaften `RgbSpeed`, `RgbMuteIndicator`, `RgbMuteColor`, `RgbBatterySaver`.

### Geändert
- Effekte senden 10 statt 25 Bilder pro Sekunde (bei Tempo 4 und 5 bis zu 20), und unveränderte Bilder werden nicht erneut gesendet. Das spart Funkverkehr und Akku.
- `hs80ctl` meldet verständlich, wenn der laufende Daemon älter ist als das Kommando.

## [0.6.0] – 2026-11-14

### Neu
- Symbol im Infobereich der Taskleiste (StatusNotifierItem) mit Akkustand im Tooltip; Klick blendet das Fenster ein oder aus, das Kontextmenü bietet „Öffnen" und „Beenden".
- Schließen des Fensters minimiert in den Infobereich, statt das Programm zu beenden.
- Autostart beim Anmelden, minimiert im Infobereich (`hs80-control --background`).
- Schalter für beides im Abschnitt „Programmstart" der Übersicht. Beides ist standardmäßig aktiv.
- GNOME: Das RPM empfiehlt die AppIndicator-Erweiterung, das Symbol nutzt dort ein symbolisches Icon, und die Übersicht weist darauf hin, wenn kein Infobereich vorhanden ist. Ohne Infobereich beendet sich ein versteckter Autostart nach 20 Sekunden wieder, statt unsichtbar weiterzulaufen.
- „Beenden" im Hauptmenü (Strg+Q).

## [0.5.0] – 2026-11-14

### Neu
- Schalter „Warnung bei niedrigem Akkustand" in der Übersicht; wirkt sofort, ohne Neustart des Daemons.
- `hs80ctl battery-warning on|off`, D-Bus-Eigenschaft `BatteryNotify` und Methode `SetBatteryNotify`.

Die Warnung ist standardmäßig aktiv, mit den Schwellen 20 % (niedrig) und 10 % (dringlich).

## [0.4.0] – 2026-11-14

### Neu
- Desktop-Benachrichtigung bei niedrigem Akkustand (ab 20 %) und dringlich bei fast leerem Akku (ab 10 %); Schwellen in `config.json` unter `battery`.
- GUI und `hs80ctl status` weisen auf einen niedrigen Akkustand hin.
- CI prüft zusätzlich Fedora 45.

### Behoben
- Mit aktivem Linger blieb das Headset nach dem Login bis zu einer Minute offline, weil fehlender Gerätezugriff vor dem Login als nicht antwortendes Gerät gezählt wurde.

## [0.3.1] – 2026-08-16

### Behoben
- Ein nicht antwortendes Gerät wird mit wachsendem Abstand statt alle zwei Sekunden angesprochen.

## [0.3.0] – 2026-08-16

### Neu
- Direktbetrieb am USB-Kabel ohne Receiver: Akku, Firmware, Mikrofonstatus, Beleuchtung, Sidetone und Mikrofonverstärkung.

### Behoben
- Im Kabelbetrieb wird der Funk-Heartbeat `0x12` nicht mehr gesendet; er setzte das Gerät zurück.

## [0.2.3] – 2026-08-16

### Neu
- Ein Headset am Ladekabel wird erkannt und der Zustand erklärt.

## [0.2.2] – 2026-08-16

### Neu
- Aktion „Neu verbinden" in GUI und CLI.

### Behoben
- Ein fehlendes Headset wird begründet statt mit leerer Fehlermeldung angezeigt.
- hidapi-Fehler nennen die tatsächliche Ursache.

## [0.2.1] – 2026-08-15

### Behoben
- Umschaltleiste in schmalen Fenstern unter libadwaita 1.9.
- Farbermittlung des Akkurings bei fehlenden Themenfarben.

## [0.2.0] – 2026-08-15

### Geändert
- Oberfläche als native GNOME-App neu gestaltet; folgt Farbschema und Akzentfarbe des Systems.

## [0.1.3] – 2026-08-15

### Neu
- Hinweis, wenn das hochgeklappte Mikrofon die Beleuchtung unterdrückt.

## [0.1.2] – 2026-08-13

### Behoben
- Anwenden von RGB-Profilen in der GTK-Oberfläche.

## [0.1.1] – 2026-08-13

### Behoben
- Zuordnung von HS80-Antworten und Erkennung des aktiven Headset-Endpunkts.

## [0.1.0] – 2026-08-10

- Erste Veröffentlichung.

[0.7.1]: https://github.com/ST1CKEL/HS80_Control/releases/tag/v0.7.1
[0.7.0]: https://github.com/ST1CKEL/HS80_Control/releases/tag/v0.7.0
[0.6.0]: https://github.com/ST1CKEL/HS80_Control/releases/tag/v0.6.0
[0.5.0]: https://github.com/ST1CKEL/HS80_Control/releases/tag/v0.5.0
[0.4.0]: https://github.com/ST1CKEL/HS80_Control/releases/tag/v0.4.0
