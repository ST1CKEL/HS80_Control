# Architektur von HS80 Control

Dieses Dokument beschreibt den internen Aufbau, das Threading-Modell, die Zustandsverwaltung und die Sicherheitsgrenzen von **HS80 Control**.

---

## 1. Prozess- und Komponentenübersicht

```mermaid
flowchart TB
    subgraph UI_Layer["Präsentationsschicht"]
        GUI["🖥️ hs80-control (GTK4 / libadwaita)"]
        CLI["⌨️ hs80ctl (CLI-Werkzeug)"]
        ThirdParty["🌐 Externe D-Bus Clients (Waybar, Scripts)"]
    end

    subgraph IPC["D-Bus Session Bus (io.github.hs80control.Daemon)"]
        DBusIface["D-Bus Interface / Object Path\n/io/github/hs80control/Daemon"]
    end

    subgraph Daemon["Benutzerdienst (hs80d)"]
        Service["HS80Service (Asyncio D-Bus Bridge)"]
        Controller["DeviceController (Hauptsteuerung)"]
        State["StateStore (Thread-sicherer Zustand)"]
        Config["ConfigStore (Atomare JSON-Persistenz)"]
        Mixer["AlsaMixer (USB Audio Controls)"]
        Spatial["SpatialManager (PipeWire SOFA Graph)"]
        Queue["Thread-sichere Request-Queue"]
        Worker["Worker-Thread: hs80-io\n(Exklusiver HID-Handle-Besitzer)"]
    end

    subgraph OS_Hardware["Kernel & Hardware"]
        Sysfs["/sys/class/hidraw & /proc/asound"]
        Hidraw["/dev/hidrawX (Interface 3 - 0xff42)"]
        AlsaHW["snd-usb-audio (ALSA Simple Controls)"]
        PW["PipeWire Server & WirePlumber"]
        Dongle["USB Transceiver 1b1c:0a6b"]
        HeadsetDirect["Headset am Kabel 1b1c:0a69"]
    end

    GUI -->|Methoden & Signale| DBusIface
    CLI -->|Methoden & Properties| DBusIface
    ThirdParty -->|PropertiesChanged| DBusIface

    DBusIface <--> Service
    Service <--> Controller
    Controller <--> State
    Controller <--> Config
    Controller --> Mixer
    Controller --> Spatial
    Controller --> Queue
    Queue --> Worker

    Worker -->|Discovery & Serial| Sysfs
    Worker -->|hidapi write / read| Hidraw
    Mixer -->|amixer sset / sget| AlsaHW
    Spatial -->|systemctl --user & pw-dump| PW

    Hidraw --> Dongle
    Hidraw --> HeadsetDirect
```

`hs80d` läuft vollständig in der unprivilegierten Benutzersitzung (`systemd --user`). Dadurch kann der Dienst gleichzeitig auf:
- die durch `uaccess` freigegebene hidraw-Gerätedatei,
- die ALSA-Kartenregler des Benutzers und
- den PipeWire-Audio-Server der Benutzersitzung

zugreifen, ohne jemals Root-Rechte oder polkit-Eskalationen zu benötigen.

---

## 2. Threading-Modell & HID-Serialisierung

```mermaid
sequenceDiagram
    autonumber
    participant Client as D-Bus Client (GUI/CLI)
    participant Async as HS80Service (Asyncio Loop)
    participant Ctrl as DeviceController
    participant Queue as Request Queue
    participant Worker as Worker-Thread (hs80-io)
    participant Device as HID Device (/dev/hidrawX)

    Client->>Async: Call SetRgb("static", 80, ...)
    Async->>Ctrl: Submit Request via Future
    Ctrl->>Queue: Request(op, args, future)
    Note over Worker: Worker liest Queue seriell
    Queue->>Worker: Pop Request
    Worker->>Device: hid_write(0x02, target, cmd, payload)
    Device-->>Worker: hid_read_timeout(0x01, target, response)
    Worker->>Ctrl: StateStore.update(rgb_...)
    Ctrl->>Async: Future.set_result(True)
    Async->>Client: Return Success
    Async-->>Client: Emit PropertiesChanged
```

### Warum ein exklusiver Worker-Thread?

Im Corsair Bragi-Protokoll teilen sich Receiverkommandos, Headsetkommandos, RGB-Frames, Heartbeats und spontane Hardware-Ereignisse (wie Akku- oder Mute-Meldungen) **denselben gemeinsamen USB-HID-Handle**.

Würden mehrere Threads gleichzeitig auf dem Handle lesen oder schreiben:
1. Könnten Antworten auf Konfigurationskommandos von einem anderen Thread abgefangen werden.
2. Könnte ein periodischer Heartbeat eine RGB-Frame-Antwort überholen.
3. Würden Timeouts und Stream-Desynchronisationen auftreten.

Deshalb besitzt **ausschließlich der Thread `hs80-io`** das offene HID-Handle.

### Aufgaben des Worker-Threads

1. **USB-Hotplug & Discovery**: Überwachung von Sysfs nach dem Receiver `1b1c:0a6b` oder direkt angeschlossenem Headset `1b1c:0a69`.
2. **Initialisierung**: Umschaltung in den Softwaremodus (`01 03 00 02`) und Ermittlung gekoppelter Endpunkte.
3. **Queue-Abarbeitung**: Serielles Ausführen von Benutzerkommandos mit Bestätigung über `concurrent.futures.Future`.
4. **Heartbeat-Zyklus**: Periodische Abfrage alle 10 Sekunden zur Erkennung von Verbindungsabbrüchen.
5. **Event-Dispatching**: Verarbeitung spontaner Report-ID-`0x03`-Events (Akkustand, Ladezustand, Mikrofon-Arm-Schalter).
6. **RGB-Animationen**: Taktung von dynamischen Effekten (*Pulse*, *Rainbow*) mit bis zu 25 Frames pro Sekunde.
7. **Clean Teardown**: Sichere Rückversetzung von Headset und Dongle in den Hardwaremodus (`01 03 00 01`) beim Beenden des Dienstes.

---

## 3. D-Bus-Architektur & Unabhängige Lock-Domänen

Um zu verhindern, dass langwierige Operationen (wie das Starten von PipeWire-Diensten oder Laden großer SOFA-Dateien) die reaktionsschnelle Steuerung von Lautstärke, Mute oder RGB blockieren, trennt `HS80Service` die Aufrufe in getrennte Asyncio-Locks:

```mermaid
graph TD
    subgraph D-Bus Methods
        M_HID["Refresh, Reconnect, SetRgb, UpdateRgb, SetSleepTimer"]
        M_ALSA["SetSidetone, SetMicrophoneGain, SetMicrophoneMuted"]
        M_Spatial["ConfigureSpatial, SetSpatialEnabled, SetSpatialMakeDefault"]
    end

    subgraph Locks
        Lock_HW["🔒 _hardware_lock\n(HID & ALSA Operationen)"]
        Lock_Spatial["🔒 _spatial_lock\n(PipeWire & Systemd Operationen)"]
    end

    M_HID --> Lock_HW
    M_ALSA --> Lock_HW
    M_Spatial --> Lock_Spatial
```

- **Hardware-Lock**: Schnelle HID- und ALSA-Befehle werden unmittelbar an die Worker-Queue übergeben.
- **Spatial-Lock**: PipeWire-Konfigurationsänderungen, `systemctl --user`-Neustarts und Sink-Wartezyklen laufen isoliert im Spatial-Lock.

---

## 4. Persistenz & Konfigurationsintegrität

Die Konfiguration wird in `~/.config/hs80-control/config.json` verwaltet:

1. **Atomares Schreiben**: Konfigurationsdateien werden zunächst in eine temporäre Datei im selben Verzeichnis geschrieben, via `os.fsync()` synchronisiert und mittels `os.replace()` atomar ausgetauscht.
2. **Rechteabsicherung**: Das Verzeichnis `~/.config/hs80-control/` wird strikt mit Modus `0700` angelegt, Dateien mit `0600`.
3. **Rollback-Fähigkeit**: Schlägt das Aktivieren einer neuen SOFA-HRTF-Konfiguration fehl, stellt `SpatialManager` die vorherige funktionierende Konfiguration und die WirePlumber-Standardausgabe automatisch wieder her.

---

## 5. Sicherheitsgrenzen

- **Striktes udev-Scoping**: Die udev-Regel gewährt ausschließlich Zugriff auf Interface 3 (Vendor-Usage-Page `0xff42`).
- **Kernel-Treiber unberührt**: USB Audio Interfaces 0, 1, 2 und HID-Tasten Interface 4 verbleiben vollständig bei `snd-usb-audio` und `hid-generic`.
- **Keine invasiven Kommandos**: Der Quellcode enthält bewusst keinerlei Firmware-Flash- oder Neukoppelungs-(Pairing-)Befehle, um ein Bricken der Hardware auszuschließen.
- **Isolierter Socket**: Keine Netzwerk-Sockets, keine Telemetrie, D-Bus nur auf dem lokalen Benutzer-Session-Bus.
