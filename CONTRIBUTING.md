# Mitwirken

Beiträge sind willkommen – Fehlerberichte, Tests auf anderer Hardware oder Firmware und Code.

## Fehler melden

Bitte das Formular unter [Issues](https://github.com/ST1CKEL/HS80_Control/issues/new/choose) verwenden und die Ausgabe von `hs80ctl doctor` beilegen. Sicherheitsrelevantes bitte nach [SECURITY.md](SECURITY.md) melden.

## Entwicklung

```bash
git clone https://github.com/ST1CKEL/HS80_Control.git
cd HS80_Control
make check                 # Tests und alle Validierungen
PYTHONPATH=src python3 -m hs80_control.gui   # Oberfläche aus dem Quellbaum
```

Die Abhängigkeiten stehen im [README](README.md#systemanforderungen). Der Code kommt ohne Build-Schritt und ohne Pakete von PyPI aus.

## Regeln für Änderungen

- **Tests gehören dazu.** Jede Verhaltensänderung bekommt einen Test in `tests/`; `make check` muss durchlaufen.
- **Gerätekommandos einzeln verifizieren.** Ein unbekanntes Kommando wird allein gesendet und beim ersten Timeout abgebrochen. Das HS80 kann durch unbeantwortete Kommandos in einen Zustand geraten, den nur Aus- und Einschalten behebt. Verifizierte Kommandos kommen mit Firmwarestand in [docs/PROTOCOL.md](docs/PROTOCOL.md).
- **Keine Firmware- oder Pairing-Kommandos.** Sie sind bewusst nicht Teil des Projekts.
- **Ein Thema pro Pull Request**, mit einer Commit-Nachricht, die das Warum erklärt.
- **Versionen** stehen synchron in `src/hs80_control/__init__.py`, `packaging/hs80-control.spec` und der AppStream-Datei; `make check` prüft das.

## Lizenz

Beiträge werden unter [GPL-3.0-or-later](LICENSE) veröffentlicht.
