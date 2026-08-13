# HS80 Control

Linux-Steuerung für den **Corsair HS80 RGB Wireless Receiver** mit der USB-ID
`1b1c:0a6b`. Das Projekt besteht aus einem Benutzerdienst, einer D-Bus-API,
einem Kommandozeilenprogramm und einer GTK4/libadwaita-Oberfläche, die unter
KDE Plasma und Wayland läuft.

## Funktionen

- Akku, Verbindung, Firmware und physischer Mikrofonstatus
- RGB aus, statisch, pulsierend oder Regenbogen
- getrennte Farben für Logo, Statusanzeige und Mikrofon-LED
- automatische Abschaltung von 0 bis 90 Minuten
- Hardware-Sidetone über ALSA, `-42` bis `+4 dB`
- Mikrofonverstärkung über ALSA, `-36` bis `0 dB`
- ALSA-Aufnahmestummschaltung
- optionales binaurales PipeWire-7.1 mit einer SOFA-HRTF
- sichere Hotplug-, Standby- und Wiederverbindungsbehandlung

Audio und Mikrofon bleiben beim Kernelmodul `snd-usb-audio`. Der Dienst öffnet
nur HID-Interface 3 und trennt keine USB- oder Audio-Treiber.

Nicht implementiert sind Pairing und Firmware-Updates. Diese Befehle werden
absichtlich nicht angeboten.

## Voraussetzungen

Die benötigten Laufzeitpakete sind auf Fedora 44 normalerweise bereits
vorhanden:

```bash
sudo dnf install python3 python3-dbus-next python3-gobject gtk4 libadwaita \
  hidapi alsa-utils pipewire pipewire-utils wireplumber
```

Für Spatial Audio zusätzlich:

```bash
sudo dnf install pipewire-module-filter-chain-sofa
```

EasyEffects ist optional und wird für RNNoise, Gate und Kompressor des
Mikrofons empfohlen.

## Prüfen

```bash
make check
./bin/hs80ctl doctor
```

`doctor` prüft USB-Gerät, hidraw-Berechtigungen, ALSA-Regler, PipeWire-Sink und
das SOFA-Modul. Vor der Installation meldet `/dev/hidraw*` erwartungsgemäß
fehlende Rechte.

## Benutzerinstallation

Die Anwendung und die systemd-User-Dienste benötigen keine Root-Rechte:

```bash
make install-user
```

Eine Benutzerinstallation wird mit `make uninstall-user` wieder entfernt. Die
persönliche Konfiguration und ausgewählte SOFA-Dateien bleiben dabei erhalten.
Die separat systemweit installierte udev-Regel wird absichtlich nicht durch
dieses Benutzerziel verändert.

Nur die eng begrenzte udev-Regel muss systemweit installiert werden:

```bash
sudo install -Dm0644 data/udev/70-hs80-control.rules \
  /usr/lib/udev/rules.d/70-hs80-control.rules
sudo udevadm control --reload-rules
```

Danach den Receiver einmal abziehen und wieder einstecken. Anschließend:

```bash
systemctl --user restart hs80d.service
hs80ctl status
hs80-control
```

`~/.local/bin` muss im `PATH` liegen. Unter Fedora ist dies nach einer normalen
Anmeldung üblicherweise der Fall.

## Systeminstallation

Alternativ kann das Projekt systemweit installiert werden:

```bash
sudo make install
sudo udevadm control --reload-rules
systemctl --user daemon-reload
```

D-Bus startet `hs80d` bei Bedarf automatisch. Ein dauerhaft aktivierter Dienst
ist daher optional:

```bash
systemctl --user enable --now hs80d.service
```

Der systemweite Installationspfad ist bewusst auf `/usr` festgelegt, weil die
Starter, D-Bus-Aktivierung und systemd-Units gemeinsam darauf verweisen. Für
Paket-Builds kann weiterhin ohne Host-Änderungen gestaged werden, zum Beispiel
mit `make install DESTDIR="$PWD/stage"`. Ein abweichendes `PREFIX` wird mit einer
erklärenden Fehlermeldung abgewiesen.

## Direkt aus dem Quellverzeichnis

```bash
./bin/hs80d
./bin/hs80-control
```

In einem zweiten Terminal können Befehle ausgeführt werden:

```bash
./bin/hs80ctl status
./bin/hs80ctl rgb off
./bin/hs80ctl rgb static --brightness 35 --logo '#00bfff'
./bin/hs80ctl sidetone on --db -20
./bin/hs80ctl mic-gain -6
./bin/hs80ctl mic-mute off
./bin/hs80ctl sleep 15
```

Für Skripte liefert `hs80ctl status --json` den vollständigen D-Bus-Zustand.
Auch Antworten anderer Befehle und Fehler werden mit `--json`
maschinenlesbar ausgegeben; die Option funktioniert vor oder nach dem
Unterbefehl.

## Spatial Audio

Das Headset ist physisch ein Stereo-Gerät. HS80 Control erzeugt ein virtuelles
7.1-Gerät und faltet dessen acht Kanäle mit einer SOFA-HRTF auf Stereo. Eine
SOFA-Datei wird wegen unterschiedlicher Datensatzlizenzen nicht mitgeliefert.

```bash
hs80ctl spatial configure ~/HRTF/meine-hrtf.sofa
hs80ctl spatial default on
hs80ctl spatial on
```

Danach erscheint `HS80 Spatial 7.1` in Plasma. Das Programm setzt es auf Wunsch
als Standardausgabe. Mit `hs80ctl spatial default off` bleibt dagegen die
bisherige Ausgabe ausgewählt. Diese Voreinstellung gilt bei der nächsten
Aktivierung; ein laufender Spatial-Dienst kann dafür kurz mit `spatial off` und
`spatial on` neu aktiviert werden. Spiele müssen 5.1 oder 7.1 PCM ausgeben;
Stereo wird nicht künstlich hochgemischt. Diese Funktion ist generisches
HRTF-Audio und kein Dolby-Atmos-Decoder.

## Mikrofonbearbeitung

Hardware-Gain, Mute und Sidetone sind direkt integriert. Für Softwareeffekte
öffnet die Oberfläche EasyEffects. Eine sinnvolle Startreihenfolge ist:

1. Hochpass bei 70 bis 100 Hz
2. RNNoise mit moderater Sprachaktivitätserkennung
3. sanfter Expander statt hartem Gate
4. Kompressor mit ungefähr 2:1 bis 3:1
5. Limiter bei ungefähr -1 dBFS

Rauschunterdrückung und automatische Verstärkung sollten nicht gleichzeitig
noch einmal in Discord oder einer anderen Sprachsoftware aktiviert werden.

## Konflikte

Nur ein Programm darf das Corsair-HID-Kontrollinterface besitzen. OpenLinkHub,
OpenRGB, ckb-next oder iCUE in einer VM müssen für dieses Gerät beendet sein,
bevor `hs80d` gestartet wird. Der normale Kernelzugriff auf Audio, Lautstärke
und Tasten bleibt davon unberührt.

## Dateien

- Konfiguration: `~/.config/hs80-control/config.json`
- generierter PipeWire-Graph: `~/.config/hs80-control/pipewire.conf`
- User-Dienst: `hs80d.service`
- Spatial-Dienst: `hs80-spatial.service`
- D-Bus: `io.github.hs80control.Daemon`

Technische Details stehen in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) und
[docs/PROTOCOL.md](docs/PROTOCOL.md).

## Release und Paketbau

Die kanonische Version steht in `src/hs80_control/__init__.py`. `make check`
vergleicht sie mit RPM-Spec und neuestem AppStream-Release. Ein reproduzierbares
Quellarchiv mit normalisierten Zeitstempeln, Besitzern, Rechten, Reihenfolge und
gzip-Header entsteht so:

```bash
make dist
mkdir -p build/rpmbuild/{BUILD,BUILDROOT,RPMS,SOURCES,SPECS,SRPMS,tmp}
rpmbuild -ba packaging/hs80-control.spec \
  --define "_topdir $PWD/build/rpmbuild" \
  --define "_tmppath $PWD/build/rpmbuild/tmp" \
  --define "_sourcedir $PWD/dist"
```

Für die lokalen Prüfungen werden zusätzlich `make`, `desktop-file-utils`,
`appstream`, `libxml2`, `systemd`, `systemd-udev`, `pipewire-utils` und
`python3-dbus-next` benötigt; Archiv und RPM-Bau verwenden außerdem `tar`,
`gzip` und `rpm-build`. Das RPM-Spec deklariert seine Build- und
Prüfabhängigkeiten und führt in `%check` ebenfalls `make check` aus.

Quellcode und Releases liegen unter
[github.com/ST1CKEL/HS80_Control](https://github.com/ST1CKEL/HS80_Control);
Fehlerberichte gehören in den dortigen
[Issue-Tracker](https://github.com/ST1CKEL/HS80_Control/issues). Die bestehende
App-ID `io.github.hs80control.App` bleibt vorerst absichtlich unverändert:
AppStream meldet wegen des großen `A` einen rein pedantischen Hinweis. Eine
Umstellung auf Kleinbuchstaben muss koordiniert in Programmcode, Desktop-Datei,
Metainfo, Iconnamen und bestehenden Benutzerinstallationen erfolgen.

## Lizenz

HS80 Control steht unter `GPL-3.0-or-later`. Der vollständige Lizenztext liegt
in [LICENSE](LICENSE). Nur die AppStream-Metadaten sind, wie dort
vorgeschrieben, separat unter `CC0-1.0` freigegeben; der vollständige Text liegt
in [LICENSE.CC0](LICENSE.CC0). Projektspezifische Hinweise und Drittnamen stehen
in [NOTICE](NOTICE).

## Sicherheit und Haftung

Das Protokoll wurde unabhängig durch Analyse öffentlich dokumentierter
Implementierungen rekonstruiert. Die Software ist nicht mit Corsair verbunden.
Sie enthält keine Firmware- oder Pairing-Kommandos. Nutzung erfolgt ohne
Gewährleistung und auf eigenes Risiko.
