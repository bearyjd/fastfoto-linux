import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2

ColumnLayout {
    id: root
    required property var editor
    property alias showResult: result.checked
    readonly property bool inMode: root.editor.geometryMode

    component CropBox: QQC2.SpinBox {
        required property int edge
        required property string label
        editable: true
        live: false
        from: 0
        to: edge % 2 === 0 ? root.editor.sourceWidth : root.editor.sourceHeight
        value: root.editor.geometry.crop[edge]
        enabled: root.editor.canEdit
        Accessible.name: label
        onValueModified: {
            const box = root.editor.geometry.crop.slice();
            box[edge] = value;
            root.editor.setCrop(box[0], box[1], box[2], box[3]);
        }
    }

    Connections {
        target: root.editor
        function onChanged() { if (!root.editor.geometryMode) result.checked = false; }
    }

    QQC2.Button {
        objectName: "photoGeometryMode"
        Layout.fillWidth: true
        text: qsTr("Crop and rotate")
        checkable: true
        checked: root.editor.geometryMode
        enabled: root.editor.canEdit
        Accessible.name: qsTr("Crop and rotate")
        onToggled: root.editor.setGeometryMode(checked)
    }
    RowLayout {
        visible: root.inMode
        QQC2.Button {
            objectName: "photoRotateLeft"
            text: qsTr("Rotate left")
            Accessible.name: qsTr("Rotate left")
            enabled: root.editor.canEdit
            onClicked: root.editor.rotateCounterclockwise()
        }
        QQC2.Button {
            objectName: "photoRotateRight"
            text: qsTr("Rotate right")
            Accessible.name: qsTr("Rotate right")
            enabled: root.editor.canEdit
            onClicked: root.editor.rotateClockwise()
        }
    }
    GridLayout {
        visible: root.inMode
        columns: 4
        QQC2.Label { text: qsTr("Left"); textFormat: Text.PlainText }
        CropBox { objectName: "photoCropLeft"; edge: 0; label: qsTr("Crop left edge in source pixels") }
        QQC2.Label { text: qsTr("Top"); textFormat: Text.PlainText }
        CropBox { objectName: "photoCropTop"; edge: 1; label: qsTr("Crop top edge in source pixels") }
        QQC2.Label { text: qsTr("Right"); textFormat: Text.PlainText }
        CropBox { objectName: "photoCropRight"; edge: 2; label: qsTr("Crop right edge in source pixels") }
        QQC2.Label { text: qsTr("Bottom"); textFormat: Text.PlainText }
        CropBox { objectName: "photoCropBottom"; edge: 3; label: qsTr("Crop bottom edge in source pixels") }
    }
    RowLayout {
        visible: root.inMode
        QQC2.Button {
            objectName: "photoClearCrop"
            text: qsTr("Clear crop")
            Accessible.name: qsTr("Clear crop")
            enabled: root.editor.canEdit && root.editor.geometry.cropped
            onClicked: root.editor.clearCrop()
        }
        QQC2.Button {
            objectName: "photoResetGeometry"
            text: qsTr("Reset geometry")
            Accessible.name: qsTr("Reset geometry")
            enabled: root.editor.canEdit && !root.editor.geometryNeutral
            onClicked: root.editor.resetGeometry()
        }
    }
    QQC2.Switch {
        id: result
        objectName: "photoGeometryResult"
        visible: root.inMode
        text: qsTr("Show result")
        Accessible.name: qsTr("Show result")
    }
    QQC2.Label {
        objectName: "photoOutputSize"
        Layout.fillWidth: true
        text: qsTr("Saved size %1 × %2 px").arg(root.editor.outputWidth).arg(root.editor.outputHeight)
        textFormat: Text.PlainText
        wrapMode: Text.WordWrap
    }
    QQC2.Label {
        objectName: "photoGeometryNote"
        Layout.fillWidth: true
        visible: !root.inMode && !root.editor.geometryNeutral
        text: qsTr("Red-eye view shows the whole original; use Crop and rotate › Show result to check the saved framing.")
        textFormat: Text.PlainText
        wrapMode: Text.WordWrap
    }
}
