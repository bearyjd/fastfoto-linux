import QtQuick
import QtQuick.Layouts
import QtQuick.Dialogs
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami

Kirigami.Page {
    id: page
    objectName: "photoEditPage"
    title: qsTr("Edit photo")
    background: Rectangle { color: Kirigami.Theme.backgroundColor }
    property var editor: bridge.photoEdit
    readonly property var selected: editor.candidates.find(eye => eye.id === editor.selectedId) || null
    onBackRequested: event => { event.accepted = true; editor.close(); }

    component GeometrySpinBox: QQC2.SpinBox {
        id: control
        editable: true
        live: false
        inputMethodHints: Qt.ImhFormattedNumbersOnly
        textFromValue: page.decimalText
        valueFromText: page.decimalValue
        validator: DoubleValidator {
            locale: control.locale.name
            bottom: control.from / 100
            top: control.to / 100
            decimals: 2
            notation: DoubleValidator.StandardNotation
        }
        // KDE's default input eagerly applies textEdited even when live is false.
        // Native SpinBox acceptance commits this input once on Return or focus loss.
        contentItem: QQC2.TextField {
            text: control.displayText
            readOnly: !control.editable
            validator: control.validator
            inputMethodHints: control.inputMethodHints
            selectByMouse: true
            font: control.font
            palette: control.palette
            padding: 0
            background: null
            verticalAlignment: TextInput.AlignVCenter
            Accessible.name: control.Accessible.name
            Accessible.description: control.Accessible.description
        }
    }

    function applyEllipse() {
        if (selected !== null) editor.replaceEllipse(editor.selectedId,
            centerX.value / 100, centerY.value / 100, radiusX.value / 100, radiusY.value / 100);
    }
    function decimalText(value, locale) { return Number(value / 100).toLocaleString(locale, 'f', 2); }
    function decimalValue(text, locale) { return Math.round(Number.fromLocaleString(locale, text) * 100); }

    ColumnLayout {
        anchors.fill: parent
        spacing: Kirigami.Units.smallSpacing
        QQC2.Label {
            Layout.fillWidth: true
            text: editor.sourceLabel
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
        }
        QQC2.Label {
            Layout.fillWidth: true
            visible: editor.warning !== ""
            text: editor.warning
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            color: Kirigami.Theme.neutralTextColor
        }
        QQC2.Label {
            objectName: "photoEditError"
            Layout.fillWidth: true
            visible: editor.error !== ""
            text: editor.error
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            color: Kirigami.Theme.negativeTextColor
        }
        RowLayout {
            Layout.fillWidth: true
            QQC2.Switch {
                id: compare
                objectName: "photoBeforeAfter"
                text: checked ? qsTr("After") : qsTr("Before")
                checked: true
                Accessible.name: qsTr("Compare before and after")
            }
            QQC2.Label {
                objectName: "photoReducedLabel"
                text: qsTr("Reduced preview · check the eye crop at 1:1")
                textFormat: Text.PlainText
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
            }
            QQC2.Button { text: qsTr("Zoom out"); Accessible.name: qsTr("Zoom out"); onClicked: canvas.zoom(0.8) }
            QQC2.Button { text: qsTr("Zoom in"); Accessible.name: qsTr("Zoom in"); onClicked: canvas.zoom(1.25) }
            QQC2.Button { text: qsTr("Fit"); Accessible.name: qsTr("Fit"); onClicked: canvas.fit() }
        }
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            PhotoEditCanvas {
                id: canvas
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumWidth: 120
                Layout.minimumHeight: 160
                // Framing an angled photo shows the straightened frame, whatever the compare switch says.
                readonly property bool framing: editor.geometryMode && !geometryControls.showResult
                readonly property bool angled: framing && editor.geometry.straightenTenths !== 0
                imageUrl: angled ? editor.straightenedUrl
                    : !compare.checked ? editor.beforeUrl
                    : (editor.geometryMode && geometryControls.showResult ? editor.afterUrl : editor.workingUrl)
                showEyes: !editor.geometryMode
                // No crop drags against a stale image: an angled frame waits for its own preview.
                cropMode: framing && (!angled || editor.previewCurrent)
                crop: editor.geometry.crop
                minCropWidth: editor.minCropWidth
                minCropHeight: editor.minCropHeight
                sourceWidth: angled ? editor.frameWidth : editor.sourceWidth
                sourceHeight: angled ? editor.frameHeight : editor.sourceHeight
                candidates: editor.candidates
                selectedId: editor.selectedId
                canEdit: editor.canEdit
                defaultRadius: editor.defaultRadius
                manualMode: manual.checked
                onEllipseRequested: (cx, cy, rx, ry) => editor.addEllipse(cx, cy, rx, ry)
                onEyeSelected: eyeId => editor.selectEye(eyeId)
                onCropRequested: (left, top, right, bottom) => editor.setCrop(left, top, right, bottom)
                onCropRejected: geometryControls.cropRejected = true
            }
            QQC2.ScrollView {
                Layout.preferredWidth: Kirigami.Units.gridUnit * 16
                Layout.fillHeight: true
                contentWidth: availableWidth
                ColumnLayout {
                    width: parent.width
                    spacing: Kirigami.Units.smallSpacing
                    PhotoGeometryControls {
                        id: geometryControls
                        Layout.fillWidth: true
                        editor: page.editor
                    }
                    PhotoToneControls {
                        Layout.fillWidth: true
                        editor: page.editor
                    }
                    Kirigami.Heading {
                        objectName: "photoRedEyeHeading"
                        text: qsTr("Red-eye correction")
                        level: 3
                    }
                    QQC2.Label {
                        objectName: "photoNoSuggestions"
                        Layout.fillWidth: true
                        visible: !editor.busy && editor.candidates.length === 0
                        text: qsTr("No suggestions; add an eye")
                        textFormat: Text.PlainText
                        wrapMode: Text.WordWrap
                    }
                    QQC2.ComboBox {
                        objectName: "photoEyeList"
                        Layout.fillWidth: true
                        model: editor.candidates
                        textRole: "id"
                        valueRole: "id"
                        currentIndex: editor.candidates.findIndex(eye => eye.id === editor.selectedId)
                        enabled: editor.canEditEyes && editor.candidates.length > 0
                        Accessible.name: qsTr("Select eye")
                        onActivated: editor.selectEye(currentValue)
                    }
                    RowLayout {
                        QQC2.Button {
                            objectName: "photoAccept"
                            text: qsTr("Accept")
                            Accessible.name: qsTr("Accept")
                            enabled: editor.canEditEyes && page.selected !== null
                            onClicked: editor.setAccepted(editor.selectedId, true)
                        }
                        QQC2.Button {
                            objectName: "photoReject"
                            text: qsTr("Reject")
                            Accessible.name: qsTr("Reject")
                            enabled: editor.canEditEyes && page.selected !== null
                            onClicked: editor.setAccepted(editor.selectedId, false)
                        }
                    }
                    QQC2.Label {
                        Layout.fillWidth: true
                        text: page.selected === null ? "" : (page.selected.accepted ? qsTr("Accepted") : qsTr("Rejected · no correction applied"))
                        textFormat: Text.PlainText
                        wrapMode: Text.WordWrap
                    }
                    QQC2.CheckBox {
                        id: manual
                        objectName: "photoManualEye"
                        text: qsTr("Add eye: click or draw ellipse")
                        enabled: editor.canEditEyes
                        Accessible.name: qsTr("Add eye: click or draw ellipse")
                    }
                    QQC2.Label { text: qsTr("Strength"); textFormat: Text.PlainText }
                    QQC2.Slider {
                        objectName: "photoStrength"
                        Layout.fillWidth: true
                        from: 0; to: 100; stepSize: 1
                        value: page.selected !== null ? page.selected.strength : 100
                        enabled: editor.canEditEyes && page.selected !== null
                        Accessible.name: qsTr("Eye correction strength")
                        onPressedChanged: { if (pressed) editor.beginGesture(); else editor.endGesture(); }
                        onMoved: editor.setStrength(editor.selectedId, Math.round(value))
                    }
                    QQC2.Label { text: qsTr("Ellipse in source pixels"); textFormat: Text.PlainText }
                    GridLayout {
                        columns: 2
                        enabled: editor.canEditEyes && page.selected !== null
                        QQC2.Label { text: qsTr("Center X"); textFormat: Text.PlainText }
                        GeometrySpinBox {
                            id: centerX
                            objectName: "photoCenterX"
                            from: 0; to: Math.max(0, editor.sourceWidth * 100 - 1)
                            value: page.selected !== null ? Math.round(page.selected.center[0] * 100) : 0
                            Accessible.name: qsTr("Eye center X in source pixels")
                            onValueModified: page.applyEllipse()
                        }
                        QQC2.Label { text: qsTr("Center Y"); textFormat: Text.PlainText }
                        GeometrySpinBox {
                            id: centerY
                            objectName: "photoCenterY"
                            from: 0; to: Math.max(0, editor.sourceHeight * 100 - 1)
                            value: page.selected !== null ? Math.round(page.selected.center[1] * 100) : 0
                            Accessible.name: qsTr("Eye center Y in source pixels")
                            onValueModified: page.applyEllipse()
                        }
                        QQC2.Label { text: qsTr("Radius X"); textFormat: Text.PlainText }
                        GeometrySpinBox {
                            id: radiusX
                            objectName: "photoRadiusX"
                            from: 1; to: Math.max(1, editor.sourceWidth * 100)
                            value: page.selected !== null ? Math.round(page.selected.radiusX * 100) : 100
                            Accessible.name: qsTr("Eye horizontal radius in source pixels")
                            onValueModified: page.applyEllipse()
                        }
                        QQC2.Label { text: qsTr("Radius Y"); textFormat: Text.PlainText }
                        GeometrySpinBox {
                            id: radiusY
                            objectName: "photoRadiusY"
                            from: 1; to: Math.max(1, editor.sourceHeight * 100)
                            value: page.selected !== null ? Math.round(page.selected.radiusY * 100) : 100
                            Accessible.name: qsTr("Eye vertical radius in source pixels")
                            onValueModified: page.applyEllipse()
                        }
                    }
                    QQC2.Button {
                        objectName: "photoRemoveEye"
                        text: qsTr("Remove eye")
                        Accessible.name: qsTr("Remove eye")
                        enabled: editor.canEditEyes && page.selected !== null
                        onClicked: editor.removeEye(editor.selectedId)
                    }
                    QQC2.Label {
                        objectName: "photoEyeRoiLabel"
                        text: qsTr("Selected eye · 1:1")
                        textFormat: Text.PlainText
                    }
                    QQC2.ScrollView {
                        objectName: "photoEyeRoi"
                        Layout.fillWidth: true
                        Layout.preferredHeight: Kirigami.Units.gridUnit * 7
                        contentWidth: roi.implicitWidth
                        contentHeight: roi.implicitHeight
                        Image {
                            id: roi
                            objectName: "photoEyeRoiImage"
                            source: compare.checked ? editor.roiAfterUrl : editor.roiBeforeUrl
                            fillMode: Image.Pad
                            cache: false
                            smooth: false
                        }
                    }
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            QQC2.Button {
                objectName: "photoUndo"
                text: qsTr("Undo")
                Accessible.name: qsTr("Undo")
                enabled: editor.canUndo
                onClicked: editor.undo()
            }
            QQC2.Button {
                objectName: "photoReset"
                text: qsTr("Reset")
                Accessible.name: qsTr("Reset")
                enabled: editor.canReset
                onClicked: editor.reset()
            }
            QQC2.BusyIndicator { running: editor.busy; visible: running }
            Item { Layout.fillWidth: true }
            QQC2.Button {
                objectName: "photoOpenSaved"
                text: qsTr("Open saved edit")
                Accessible.name: qsTr("Open saved edit")
                enabled: !editor.busy && !editor.dirty
                onClicked: savedDialog.open()
            }
            QQC2.Button {
                visible: editor.savedEditUrl !== ""
                text: qsTr("Reopen this edit")
                Accessible.name: qsTr("Reopen this edit")
                enabled: !editor.busy && !editor.dirty
                onClicked: editor.openSavedEdit(editor.savedEditUrl)
            }
            QQC2.Button {
                objectName: "photoSaveCopy"
                text: qsTr("Save new copy")
                Accessible.name: qsTr("Save new copy")
                enabled: editor.canSave
                onClicked: editor.save()
            }
            QQC2.Button {
                objectName: "photoEditBack"
                text: qsTr("Back")
                Accessible.name: qsTr("Back")
                onClicked: editor.close()
            }
        }
        QQC2.Label {
            Layout.fillWidth: true
            visible: editor.savedEditUrl !== ""
            text: qsTr("Saved a new JPEG and its replay recipe. Previous copies are kept.")
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
        }
    }
    FileDialog {
        id: savedDialog
        title: qsTr("Open saved photo edit")
        nameFilters: [qsTr("Photo edit recipes (*.json)")]
        fileMode: FileDialog.OpenFile
        onAccepted: editor.openSavedEdit(selectedFile)
    }
}
