Name:           hs80-control
Version:        0.1.3
Release:        1%{?dist}
Summary:        Corsair HS80 RGB Wireless control service
License:        GPL-3.0-or-later AND CC0-1.0
URL:            https://github.com/ST1CKEL/HS80_Control
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch

BuildRequires:  make
BuildRequires:  python3
BuildRequires:  python3-dbus-next
BuildRequires:  desktop-file-utils
BuildRequires:  appstream
BuildRequires:  libxml2
BuildRequires:  systemd
BuildRequires:  systemd-udev
BuildRequires:  systemd-rpm-macros
BuildRequires:  pipewire
BuildRequires:  pipewire-utils
BuildRequires:  wireplumber
Requires:       python3 >= 3.11
Requires:       python3-dbus-next
Requires:       python3-gobject
Requires:       gtk4
Requires:       libadwaita >= 1.7
Requires:       hidapi
Requires:       alsa-utils
Requires:       systemd
Requires:       pipewire
Requires:       pipewire-utils
Requires:       wireplumber
Requires(post): systemd-udev
Requires(postun): systemd-udev
Recommends:     easyeffects
Recommends:     pipewire-module-filter-chain-sofa

%description
A user-session daemon, command-line client and GTK4 application for the
Corsair HS80 RGB Wireless receiver (USB ID 1b1c:0a6b). It controls RGB,
battery queries, sleep timeout, ALSA sidetone and microphone gain, and can
create a PipeWire SOFA/HRTF virtual surround sink.

%prep
%autosetup

%build

%install
%make_install PREFIX=%{_prefix}

%check
make check

%post
%systemd_user_post hs80d.service hs80-spatial.service
udevadm control --reload-rules >/dev/null 2>&1 || :

%preun
%systemd_user_preun hs80d.service hs80-spatial.service

%postun
%systemd_user_postun_with_restart hs80d.service hs80-spatial.service
udevadm control --reload-rules >/dev/null 2>&1 || :

%files
%license LICENSE LICENSE.CC0
%doc NOTICE README.md docs/ARCHITECTURE.md docs/PROTOCOL.md
%{_bindir}/hs80-control
%{_bindir}/hs80ctl
%{_libexecdir}/hs80d
%{_prefix}/lib/hs80-control/
%{_udevrulesdir}/70-hs80-control.rules
%{_userunitdir}/hs80d.service
%{_userunitdir}/hs80-spatial.service
%{_datadir}/dbus-1/services/io.github.hs80control.Daemon.service
%{_datadir}/applications/io.github.hs80control.App.desktop
%{_datadir}/metainfo/io.github.hs80control.App.metainfo.xml
%{_datadir}/icons/hicolor/scalable/apps/io.github.hs80control.App.svg

%changelog
* Sat Aug 15 2026 ST1CKEL - 0.1.3-1
- Show a banner and toast when muted microphone suppresses lighting
- Document firmware lighting suppression while the mic arm is up
* Thu Aug 13 2026 ST1CKEL - 0.1.2-1
- Fix RGB apply in the GTK interface on Fedora
- Restore controls when an RGB profile cannot be serialized

* Thu Aug 13 2026 ST1CKEL - 0.1.1-1
- Fix HS80 response matching and active headset endpoint discovery
- Make user-unit validation work in clean build containers

* Mon Aug 10 2026 ST1CKEL - 0.1.0-1
- Initial Fedora package
