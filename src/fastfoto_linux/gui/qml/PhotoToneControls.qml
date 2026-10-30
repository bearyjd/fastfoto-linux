import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2

ColumnLayout {
    id: root
    required property var editor

    component ToneControl: ColumnLayout {
        id: control
        required property var editor
        required property string field
        required property string label
        required property int minimum
        required property int maximum
        readonly property string controlName: "photoTone" + field.charAt(0).toUpperCase() + field.slice(1)
        Layout.fillWidth: true
        spacing: 0

        QQC2.Label {
            objectName: control.controlName + "Label"
            text: control.label
            textFormat: Text.PlainText
        }
        QQC2.Slider {
            objectName: control.controlName
            Layout.fillWidth: true
            from: control.minimum
            to: control.maximum
            stepSize: 1
            snapMode: QQC2.Slider.SnapAlways
            value: control.editor.color.tone[control.field]
            enabled: control.editor.canEdit
            Accessible.name: control.label
            onPressedChanged: {
                if (pressed) control.editor.beginGesture();
                else control.editor.endGesture();
            }
            onMoved: control.editor.color.setTone(control.field, Math.round(value))
        }
    }

    ToneControl {
        editor: root.editor
        field: "brightness"
        label: qsTr("Brightness")
        minimum: -50
        maximum: 50
    }
    ToneControl {
        editor: root.editor
        field: "contrast"
        label: qsTr("Contrast")
        minimum: -50
        maximum: 50
    }
    ToneControl {
        editor: root.editor
        field: "saturation"
        label: qsTr("Saturation")
        minimum: -100
        maximum: 100
    }
    ToneControl {
        editor: root.editor
        field: "strength"
        label: qsTr("Adjustment strength")
        minimum: 0
        maximum: 100
    }
    QQC2.Label {
        Layout.fillWidth: true
        text: qsTr("Adjustment strength affects brightness, contrast and saturation; eye strength is separate.")
        textFormat: Text.PlainText
        wrapMode: Text.WordWrap
    }
    QQC2.Button {
        objectName: "photoResetTone"
        text: qsTr("Reset adjustments")
        Accessible.name: qsTr("Reset adjustments")
        enabled: root.editor.canEdit
        onClicked: root.editor.color.resetTone()
    }
}
