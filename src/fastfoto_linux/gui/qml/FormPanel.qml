import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import QtQuick.Dialogs
import org.kde.kirigami as Kirigami

QQC2.ScrollView {
    id: panel

    objectName: "photosForm"

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
                Accessible.name: qsTr("Save photos in")
                onTextEdited: bridge.setField("output_folder", text)
                onEditingFinished: bridge.checkDisk()
            }

            QQC2.Button {
                objectName: "chooseFolderButton"
                icon.name: "folder-open"
                text: qsTr("Choose…")
                enabled: panel.editable
                Accessible.name: qsTr("Choose…")
                onClicked: folderDialog.open()
            }
        }

        QQC2.Label {
            objectName: "folderError"
            Layout.fillWidth: true
            visible: bridge.form.output_folder !== "" && panel.error("output_folder") !== ""
            text: panel.error("output_folder")
            textFormat: Text.PlainText
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
            Accessible.name: qsTr("Album")
            onTextEdited: bridge.setField("album", text)
            onEditingFinished: bridge.checkDisk()
        }

        QQC2.Label {
            objectName: "albumError"
            Layout.fillWidth: true
            visible: panel.error("album") !== ""
            text: panel.error("album")
            textFormat: Text.PlainText
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
            textFormat: Text.PlainText
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
            Accessible.name: qsTr("Date")
            onTextEdited: bridge.setField("date", text)
        }

        QQC2.Label {
            objectName: "dateError"
            Layout.fillWidth: true
            visible: panel.error("date") !== ""
            text: panel.error("date")
            textFormat: Text.PlainText
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
            Accessible.name: qsTr("Notes")
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
                    "text": qsTr("Face up (back first)"),
                    "value": "face-up"
                },
                {
                    "text": qsTr("Face down (front first)"),
                    "value": "face-down"
                }
            ]
            textRole: "text"
            valueRole: "value"
            currentIndex: Math.max(0, indexOfValue(bridge.form.loaded))
            enabled: panel.editable
            Accessible.name: qsTr("Loaded")
            onActivated: bridge.setField("loaded", currentValue)
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
            Accessible.name: qsTr("Keep backs")
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
            Accessible.name: qsTr("Resolution")
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
            Accessible.name: qsTr("Turn upright by faces")
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
            enabled: panel.editable
            Accessible.name: qsTr("Remove red eyes (experimental)")
            onToggled: bridge.setField("redeye", checked)
        }

        QQC2.Label {
            objectName: "redeyeWarning"
            Layout.fillWidth: true
            Layout.preferredWidth: Kirigami.Units.gridUnit * 16
            Layout.minimumWidth: 0
            text: qsTr("Experimental: about 1 fix in 6 is visibly wrong, so it is off by default.")
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            color: Kirigami.Theme.disabledTextColor
            font: Kirigami.Theme.smallFont
        }

        QQC2.CheckBox {
            objectName: "keepOriginalBox"
            text: qsTr("Keep the plain original too")
            checked: bridge.form.keep_original
            enabled: panel.editable
            Accessible.name: qsTr("Keep the plain original too")
            onToggled: bridge.setField("keep_original", checked)
        }
    }

    FolderDialog {
        id: folderDialog

        title: qsTr("Choose the folder for the photos")
        onAccepted: bridge.setOutputFolderUrl(selectedFolder)
    }
}
