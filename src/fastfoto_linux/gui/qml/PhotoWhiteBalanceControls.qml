import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2

ColumnLayout {
    id: root
    required property var editor

    component BalanceControl: ColumnLayout {
        id: control
        required property var editor
        required property string field
        required property string label
        readonly property string controlName: "photoWhiteBalance" + field.charAt(0).toUpperCase() + field.slice(1)
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
            from: -100
            to: 100
            stepSize: 1
            snapMode: QQC2.Slider.SnapAlways
            value: control.editor.color.whiteBalance[control.field]
            enabled: control.editor.canEdit
            Accessible.name: control.label
            onPressedChanged: {
                if (pressed) control.editor.beginGesture();
                else control.editor.endGesture();
            }
            onMoved: control.editor.color.setWhiteBalance(control.field, Math.round(value))
        }
    }

    QQC2.Label {
        text: qsTr("Presets")
        textFormat: Text.PlainText
    }
    component PresetButton: QQC2.Button {
        required property string presetId
        readonly property string presetLabel: {
            for (const item of root.editor.color.presets)
                if (item.id === presetId) return item.label;
            return "";
        }
        objectName: "photoPreset" + presetId.charAt(0).toUpperCase() + presetId.slice(1)
        text: presetLabel
        checkable: false
        highlighted: root.editor.color.activePreset === presetId
        enabled: root.editor.canEdit
        Accessible.name: presetLabel
        onClicked: root.editor.color.applyPreset(presetId)
    }
    Flow {
        Layout.fillWidth: true
        spacing: 4
        // Keep these ids in step with PRESETS in gui/photoeditpresets.py.
        PresetButton { presetId: "warm" }
        PresetButton { presetId: "cool" }
        PresetButton { presetId: "faded" }
        PresetButton { presetId: "mono" }
    }
    BalanceControl {
        editor: root.editor
        field: "temperature"
        label: qsTr("Temperature")
    }
    BalanceControl {
        editor: root.editor
        field: "tint"
        label: qsTr("Tint")
    }
    QQC2.Label {
        objectName: "photoWhiteBalanceHint"
        Layout.fillWidth: true
        text: qsTr("Temperature: lower is cooler (blue), higher is warmer (yellow). Tint: lower is greener, higher is more magenta.")
        textFormat: Text.PlainText
        wrapMode: Text.WordWrap
    }
}
