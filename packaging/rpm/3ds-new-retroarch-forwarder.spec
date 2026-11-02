# Built by packaging/build-rpm.sh from a staged tree; not a source RPM.
%global appid io.github.manu_romero_411.forwarder3ds
%global prefix /opt/3ds-new-retroarch-forwarder
# Python files live in /opt: skip Fedora's automatic Python handling, but keep
# the automatic library dependencies of the bundled makerom and bannertool.
%global __requires_exclude_from ^%{prefix}/lib/.*$
%global __provides_exclude_from ^%{prefix}/.*$
%global __brp_python_bytecompile %{nil}
%global __brp_mangle_shebangs %{nil}
%global debug_package %{nil}
# No /usr/lib/.build-id links: the tools are private to this package.
%global _build_id_links none

Name:           3ds-new-retroarch-forwarder
Version:        %{pkg_version}
Release:        %{pkg_release}%{?dist}
Summary:        Build 3DS forwarder CIAs that launch a game with RetroArch
License:        GPL-3.0-only AND MIT
URL:            https://github.com/manu-romero-411/3ds-new-retroarch-forwarder
Packager:       %{pkg_packager}

Requires:       python3 >= 3.11
Requires:       python3-requests
Requires:       python3-pillow
Requires:       python3-pyside6
Recommends:     (ffmpeg-free or ffmpeg)
Recommends:     qt6-qtwayland

%description
Creates one installable CIA per game for a 3DS running Luma3DS. Each
forwarder shows its own icon, banner and jingle on the HOME menu and
launches the game with the matching RetroArch core, without bundling a
whole RetroArch. Artwork comes from SteamGridDB.

Includes a Qt graphical interface (3ds-forwarder-gui), a command line tool
(3ds-forwarder) and the makerom and bannertool programs it needs.

%install
cp -a %{stage_dir}/. %{buildroot}/
install -Dm0644 %{license_file} %{buildroot}%{_datadir}/licenses/%{name}/LICENSE

%post
python3 -m compileall -q %{prefix}/lib > /dev/null 2>&1 || :

%preun
if [ "$1" -eq 0 ]; then
    find %{prefix}/lib -type d -name __pycache__ -prune -exec rm -rf {} + 2> /dev/null || :
fi

%files
%{prefix}
%{_bindir}/3ds-forwarder
%{_bindir}/3ds-forwarder-gui
%{_datadir}/applications/%{appid}.desktop
%{_datadir}/metainfo/%{appid}.metainfo.xml
%{_datadir}/icons/hicolor/*/apps/%{appid}.*
%{_datadir}/licenses/%{name}/LICENSE
