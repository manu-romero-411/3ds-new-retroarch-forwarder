#!/usr/bin/env bash
# Trims a PySide6 install down to what the program loads. Sourced by
# packaging/ci/build-package.sh and packaging/appimage/build-appimage.sh,
# which provide log() and die().

# Libraries that some file under $1 needs and the loader cannot find.
missing_libraries() {
    find "$1" -name '*.so*' -type f -exec ldd {} + 2> /dev/null \
        | sed -n 's/^[[:space:]]*\([^ ]*\) => not found$/\1/p' | sort -u
}

# Drop what the program never loads (QML/Quick, Designer, developer tools,
# stubs). The wheel already has plugins needing libraries it does not ship
# (Pdf, VirtualKeyboard...), so the check afterwards only fails on libraries
# that the pruning itself made go missing.
prune_pyside6() {
    local pyside="$1" qt="$1/Qt" name before after
    before="$(missing_libraries "${pyside}")"
    rm -rf "${pyside}"/{assistant,designer,linguist,lrelease,lupdate,qmlformat,qmllint,qmlls} \
        "${pyside}"/{svgtoqml,include,typesystems,glue,doc,scripts} "${pyside}"/*.pyi
    for name in Designer Help LabsStyleKit Qml QmlFeatures Quick QuickControls2 QuickTest \
        QuickWidgets Sql Test UiTools Xml Concurrent OpenGLWidgets; do
        rm -f "${pyside}/Qt${name}.abi3.so"
    done
    rm -f "${pyside}"/libpyside6qml.*
    rm -rf "${qt}"/{qml,metatypes,libexec} \
        "${qt}"/plugins/{designer,qmltooling,sqldrivers,vectorimageformats} \
        "${qt}"/plugins/wayland-graphics-integration-server \
        "${qt}"/plugins/platforminputcontexts/libqtvirtualkeyboardplugin.so
    find "${qt}/translations" -type f ! -name 'qtbase_*' -delete
    for name in Designer DesignerComponents Help Labs Lottie Qml Quick Sql Test UiTools \
        WaylandCompositor WaylandEglCompositor; do
        rm -f "${qt}/lib/libQt6${name}"*
    done
    after="$(missing_libraries "${pyside}")"
    name="$(comm -13 <(printf '%s\n' "${before}") <(printf '%s\n' "${after}"))"
    [[ -z "${name}" ]] || die "Pruning PySide6 broke these libraries:"$'\n'"${name}"
    log "[INFO]" "Bundled PySide6: $(du -sh "${pyside}" | cut -f1)"
}
