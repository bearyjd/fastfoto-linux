import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import QtQuick.Dialogs
import org.kde.kirigami as Kirigami

QQC2.ScrollView {
    id: panel

    // The settings can be changed again once the scan is over.
    readonly property bool editable: !bridge.busy

    function error(field) {
        const message = bridge.errors[field];
        return message === undefined ? "" : String(message);
    }

    contentWidth: availableWidth

    Kirigami.FormLayout {
        width: panel.availableWidth

        RowLayout {
            Kirigami.FormData.label: qsTr("Save photos in:")
            Layout.fillWidth: true

            QQC2.TextField {
                objectName: "folderField"
                Layout.fillWidth: true
                implicitWidth: Kirigami.Units.gridUnit * 10
                text: bridge.form.output_folder
                placeholderText: qsTr("Choose a folder")
                enabled: panel.editable
                Accessible.name: qsTr("Output folder")
                onTextEdited: bridge.setField("output_folder", text)
            }

            QQC2.Button {
                objectName: "chooseFolderButton"
                icon.name: "folder-open"
                text: qsTr("Choose…")
                enabled: panel.editable
                Accessible.name: qsTr("Choose the output folder")
                onClicked: folderDialog.open()
            }
        }

        QQC2.Label {
            objectName: "folderError"
            Layout.fillWidth: true
            visible: bridge.form.output_folder !== "" && panel.error("output_folder") !== ""
            text: panel.error("output_folder")
            wrapMode: Text.WordWrap
            color: Kirigami.Theme.negativeTextColor
        }

        QQC2.TextField {
            objectName: "albumField"
            implicitWidth: Kirigami.Units.gridUnit * 16
            Kirigami.FormData.label: qsTr("Album:")
            Layout.fillWidth: true
            text: bridge.form.album
            placeholderText: qsTr("Optional, becomes a folder")
            enabled: panel.editable
            Accessible.name: qsTr("Album name")
            onTextEdited: bridge.setField("album", text)
        }

        QQC2.Label {
            objectName: "albumError"
            Layout.fillWidth: true
            visible: panel.error("album") !== ""
            text: panel.error("album")
            wrapMode: Text.WordWrap
            color: Kirigami.Theme.negativeTextColor
        }

        QQC2.Label {
            objectName: "destinationLabel"
            Layout.fillWidth: true
            Layout.preferredWidth: Kirigami.Units.gridUnit * 16
            Layout.minimumWidth: 0
            visible: bridge.destination !== ""
            text: qsTr("Saved as %1").arg(bridge.destination)
            elide: Text.ElideMiddle
            color: Kirigami.Theme.disabledTextColor
            font: Kirigami.Theme.smallFont
        }

        QQC2.TextField {
            objectName: "dateField"
            implicitWidth: Kirigami.Units.gridUnit * 16
            Kirigami.FormData.label: qsTr("Date:")
            Layout.fillWidth: true
            text: bridge.form.date
            placeholderText: qsTr("1975, 1975-06 or 1970/1979")
            enabled: panel.editable
            Accessible.name: qsTr("Date of the photos")
            onTextEdited: bridge.setField("date", text)
        }

        QQC2.Label {
            objectName: "dateError"
            Layout.fillWidth: true
            visible: panel.error("date") !== ""
            text: panel.error("date")
            wrapMode: Text.WordWrap
            color: Kirigami.Theme.negativeTextColor
        }

        QQC2.TextField {
            objectName: "notesField"
            implicitWidth: Kirigami.Units.gridUnit * 16
            Kirigami.FormData.label: qsTr("Notes:")
            Layout.fillWidth: true
            text: bridge.form.notes
            placeholderText: qsTr("Stored in every photo")
            enabled: panel.editable
            Accessible.name: qsTr("Notes for every photo")
            onTextEdited: bridge.setField("notes", text)
        }

        Item {
            Kirigami.FormData.isSection: true
            Kirigami.FormData.label: qsTr("Photos in the feeder")
        }

        QQC2.ComboBox {
            objectName: "feedBox"
            implicitWidth: Kirigami.Units.gridUnit * 16
            Kirigami.FormData.label: qsTr("Loaded:")
            Layout.fillWidth: true
            model: [
                {
                    "text": qsTr("Face down (back first)"),
                    "value": "face-down"
                },
                {
                    "text": qsTr("Face up (front first)"),
                    "value": "face-up"
                }
            ]
            textRole: "text"
            valueRole: "value"
            currentIndex: Math.max(0, indexOfValue(bridge.form.feed))
            enabled: panel.editable
            Accessible.name: qsTr("How the photos are loaded")
            onActivated: bridge.setField("feed", currentValue)
        }

        QQC2.ComboBox {
            objectName: "backsBox"
            implicitWidth: Kirigami.Units.gridUnit * 16
            Kirigami.FormData.label: qsTr("Keep backs:")
            Layout.fillWidth: true
            model: [
                {
                    "text": qsTr("Only with writing"),
                    "value": "auto"
                },
                {
                    "text": qsTr("All"),
                    "value": "always"
                },
                {
                    "text": qsTr("None"),
                    "value": "never"
                }
            ]
            textRole: "text"
            valueRole: "value"
            currentIndex: Math.max(0, indexOfValue(bridge.form.backs))
            enabled: panel.editable
            Accessible.name: qsTr("Which photo backs to keep")
            onActivated: bridge.setField("backs", currentValue)
        }

        QQC2.ComboBox {
            objectName: "dpiBox"
            implicitWidth: Kirigami.Units.gridUnit * 16
            Kirigami.FormData.label: qsTr("Resolution:")
            Layout.fillWidth: true
            model: bridge.dpiChoices
            displayText: qsTr("%1 dpi").arg(currentText)
            currentIndex: Math.max(0, bridge.dpiChoices.indexOf(bridge.form.dpi))
            enabled: panel.editable
            Accessible.name: qsTr("Scan resolution in dots per inch")
            onActivated: bridge.setField("dpi", currentValue)
        }

        Item {
            Kirigami.FormData.isSection: true
            Kirigami.FormData.label: qsTr("Improve each photo")
        }

        QQC2.CheckBox {
            objectName: "orientBox"
            text: qsTr("Turn upright by faces")
            checked: bridge.form.orient
            enabled: panel.editable
            Accessible.name: qsTr("Turn photos upright")
            onToggled: bridge.setField("orient", checked)
        }

        QQC2.CheckBox {
            objectName: "restoreBox"
            text: qsTr("Restore faded colour")
            checked: bridge.form.restore
            enabled: panel.editable
            Accessible.name: qsTr("Restore faded colour")
            onToggled: bridge.setField("restore", checked)
        }

        QQC2.CheckBox {
            objectName: "redeyeBox"
            text: qsTr("Remove red eyes (experimental)")
            checked: bridge.form.redeye
            QQC2.ToolTip.visible: hovered
            QQC2.ToolTip.text: qsTr("Off by default: about 1 fix in 6 is visibly wrong.")
            enabled: panel.editable
            Accessible.name: qsTr("Remove red eyes")
            onToggled: bridge.setField("redeye", checked)
        }

        QQC2.CheckBox {
            objectName: "keepOriginalBox"
            text: qsTr("Keep the plain original too")
            checked: bridge.form.keep_original
            enabled: panel.editable
            Accessible.name: qsTr("Keep the plain original next to the enhanced copy")
            onToggled: bridge.setField("keep_original", checked)
        }
    }

    FolderDialog {
        id: folderDialog

        title: qsTr("Choose the folder for the photos")
        onAccepted: bridge.setOutputFolderUrl(selectedFolder)
    }
}
