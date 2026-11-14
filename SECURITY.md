# Sicherheit

## Unterstützte Versionen

Sicherheitskorrekturen gibt es für die jeweils neueste Version.

## Schwachstelle melden

Bitte **kein öffentliches Issue** anlegen, sondern eine vertrauliche Meldung über
[Security → Report a vulnerability](https://github.com/ST1CKEL/HS80_Control/security/advisories/new) senden.

Hilfreich sind betroffene Version, Schritte zum Nachstellen und eine Einschätzung der Auswirkung.

## Angriffsfläche

- Der Daemon läuft ohne Root-Rechte in der Benutzersitzung und öffnet keine Netzwerk-Sockets.
- Die udev-Regel gibt nur das Vendor-Interface 3 von Receiver und Headset für den aktiven Desktop-Benutzer frei.
- Die D-Bus-Schnittstelle liegt ausschließlich auf dem Session-Bus des Benutzers.
