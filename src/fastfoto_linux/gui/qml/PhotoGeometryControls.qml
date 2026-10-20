import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2

ColumnLayout {
    id: root
    required property var editor
    property alias showResult: result.checked
    readonly property bool inMode: root.editor.geometryMode
    // Set by the canvas when a drag is below the minimum crop; cleared by the next geometry change.
    property bool cropRejected: false
    property string seenGeometry: ""

    component CropBox: QQC2.SpinBox {
        required property int edge
        required property string label
        editable: true
        live: false
        from: 0
        to: edge % 2 === 0 ? root.editor.frameWidth : root.editor.frameHeight
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
        function onChanged() {
            // A rejected angle leaves the draft as it was, so the bindings would not run:
            // put the widgets back on the draft's angle.
            angleSlider.value = Qt.binding(() => root.editor.geometry.straightenTenths);
            angleBox.value = Qt.binding(() => root.editor.geometry.straightenTenths);
            if (!root.editor.geometryMode) {
                result.checked = false;
                root.cropRejected = false;
            }
            const now = JSON.stringify(root.editor.geometry);
            if (now !== root.seenGeometry) {
                root.seenGeometry = now;
                root.cropRejected = false;
            }
        }
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
    QQC2.Label { visible: root.inMode; text: qsTr("Straighten"); textFormat: Text.PlainText }
    RowLayout {
        visible: root.inMode
        Layout.fillWidth: true
        QQC2.Slider {
            id: angleSlider
            objectName: "photoStraightenSlider"
            Layout.fillWidth: true
            from: -150
            to: 150
            stepSize: 1
            snapMode: QQC2.Slider.SnapAlways
            value: root.editor.geometry.straightenTenths
            enabled: root.editor.canStraighten
            Accessible.name: qsTr("Straighten angle")
            onPressedChanged: pressed ? root.editor.beginGesture() : root.editor.endGesture()
            onMoved: root.editor.setStraighten(Math.round(value))
        }
        QQC2.SpinBox {
            id: angleBox
            objectName: "photoStraightenAngle"
            from: -150
            to: 150
            stepSize: 1
            editable: true
            live: false
            value: root.editor.geometry.straightenTenths
            enabled: root.editor.canStraighten
            Accessible.name: qsTr("Straighten angle in degrees")
            validator: RegularExpressionValidator {
                regularExpression: /^\s*[-+]?\d{0,2}[.,]?\d?\s*°?\s*$/
            }
            textFromValue: (v, locale) => (v / 10).toFixed(1) + " °"
            valueFromText: (text, locale) => {
                const parsed = parseFloat(text.replace(",", "."));
                return isNaN(parsed) ? value : Math.round(parsed * 10);
            }
            onValueModified: root.editor.setStraighten(value)
            // KDE's default input applies every keystroke even when live is false; this one
            // commits once, on Return or focus loss (same approach as the eye spin boxes).
            contentItem: QQC2.TextField {
                text: angleBox.displayText
                readOnly: !angleBox.editable
                validator: angleBox.validator
                inputMethodHints: Qt.ImhFormattedNumbersOnly
                selectByMouse: true
                font: angleBox.font
                palette: angleBox.palette
                padding: 0
                background: null
                verticalAlignment: TextInput.AlignVCenter
                Accessible.name: angleBox.Accessible.name
            }
        }
    }
    QQC2.Button {
        objectName: "photoResetStraighten"
        visible: root.inMode
        text: qsTr("Reset straighten")
        Accessible.name: qsTr("Reset straighten")
        enabled: root.editor.canStraighten && root.editor.geometry.straightenTenths !== 0
        onClicked: root.editor.resetStraighten()
    }
    QQC2.Label {
        objectName: "photoStraightenHint"
        Layout.fillWidth: true
        visible: root.inMode
        text: root.editor.canEdit && !root.editor.canStraighten
            ? qsTr("Straighten needs equal horizontal and vertical resolution.")
            : qsTr("Changing the angle clears the crop.")
        textFormat: Text.PlainText
        wrapMode: Text.WordWrap
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
    QQC2.Label {
        objectName: "photoCropHint"
        Layout.fillWidth: true
        visible: root.inMode && root.cropRejected
        text: qsTr("That selection is smaller than the minimum crop size.")
        textFormat: Text.PlainText
        wrapMode: Text.WordWrap
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
