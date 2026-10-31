import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami

ColumnLayout {
    id: root
    required property var editor

    component DetailControl: ColumnLayout {
        id: control
        required property var editor
        required property string field
        required property string controlName
        required property string label
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
            from: 0
            to: 100
            stepSize: 1
            snapMode: QQC2.Slider.SnapAlways
            value: control.editor.color.detail[control.field]
            enabled: control.editor.canEdit
            Accessible.name: control.label
            onPressedChanged: {
                if (pressed) control.editor.beginGesture();
                else control.editor.endGesture();
            }
            onMoved: control.editor.color.setDetail(control.field, Math.round(value))
        }
    }

    Kirigami.Heading {
        objectName: "photoDetailHeading"
        text: qsTr("Detail")
        textFormat: Text.PlainText
        level: 3
    }
    DetailControl {
        editor: root.editor
        field: "denoise_luma"
        controlName: "photoDetailDenoiseLuma"
        label: qsTr("Noise reduction")
    }
    DetailControl {
        editor: root.editor
        field: "denoise_chroma"
        controlName: "photoDetailDenoiseChroma"
        label: qsTr("Colour noise")
    }
    DetailControl {
        editor: root.editor
        field: "sharpen"
        controlName: "photoDetailSharpen"
        label: qsTr("Sharpen")
    }
    QQC2.Label {
        objectName: "photoDetailHint"
        Layout.fillWidth: true
        text: qsTr("Optional and off by default. Computed at full resolution, so large scans can be slow to preview. The fitted preview shows sharpening only faintly.")
        textFormat: Text.PlainText
        wrapMode: Text.WordWrap
    }
}
