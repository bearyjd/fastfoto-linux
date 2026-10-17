import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import QtQuick.Dialogs
import org.kde.kirigami as Kirigami

// The Documents settings: where the PDF goes, what it is called, how it is scanned. The folder
// is the one of Photos mode (the bridge keeps one value for both); the rest is Documents' own.
QQC2.ScrollView {
    id: panel

    objectName: "documentsForm"

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
            Kirigami.FormData.label: qsTr("Save documents in:")
            Layout.fillWidth: true

            QQC2.TextField {
                objectName: "docFolderField"
                Layout.fillWidth: true
                implicitWidth: Kirigami.Units.gridUnit * 10
                text: bridge.form.output_folder
                placeholderText: qsTr("Choose a folder")
                enabled: panel.editable
                Accessible.name: qsTr("Save documents in")
                onTextEdited: bridge.setField("output_folder", text)
                onEditingFinished: bridge.checkDisk()
            }

            QQC2.Button {
                objectName: "docChooseFolderButton"
                icon.name: "folder-open"
                text: qsTr("Choose…")
                enabled: panel.editable
                Accessible.name: qsTr("Choose…")
                onClicked: folderDialog.open()
            }
        }

        QQC2.Label {
            objectName: "docFolderError"
            Layout.fillWidth: true
            visible: bridge.form.output_folder !== "" && panel.error("output_folder") !== ""
            text: panel.error("output_folder")
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            color: Kirigami.Theme.negativeTextColor
        }

        QQC2.TextField {
            objectName: "docNameField"
            implicitWidth: Kirigami.Units.gridUnit * 16
            Kirigami.FormData.label: qsTr("Name:")
            Layout.fillWidth: true
            text: bridge.documents.form.name
            placeholderText: qsTr("Document")
            enabled: panel.editable
            Accessible.name: qsTr("Name")
            onTextEdited: bridge.setDocumentField("name", text)
        }

        QQC2.Label {
            objectName: "docNameError"
            Layout.fillWidth: true
            visible: panel.error("name") !== ""
            text: panel.error("name")
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            color: Kirigami.Theme.negativeTextColor
        }

        QQC2.Label {
            objectName: "docDestinationLabel"
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

        Item {
            Kirigami.FormData.isSection: true
            Kirigami.FormData.label: qsTr("Scanning")
        }

        QQC2.ComboBox {
            objectName: "docColourBox"
            implicitWidth: Kirigami.Units.gridUnit * 16
            Kirigami.FormData.label: qsTr("Colour:")
            Layout.fillWidth: true
            model: [
                {
                    "text": qsTr("Colour"),
                    "value": "colour"
                },
                {
                    "text": qsTr("Grey"),
                    "value": "grey"
                },
                {
                    "text": qsTr("Black and white"),
                    "value": "bw"
                }
            ]
            textRole: "text"
            valueRole: "value"
            currentIndex: Math.max(0, indexOfValue(bridge.documents.form.colour))
            enabled: panel.editable
            Accessible.name: qsTr("Colour")
            onActivated: bridge.setDocumentField("colour", currentValue)
        }

        QQC2.ComboBox {
            objectName: "docDpiBox"
            implicitWidth: Kirigami.Units.gridUnit * 16
            Kirigami.FormData.label: qsTr("Resolution:")
            Layout.fillWidth: true
            model: bridge.documents.dpiChoices
            displayText: qsTr("%1 dpi").arg(currentText)
            currentIndex: Math.max(0, bridge.documents.dpiChoices.indexOf(bridge.documents.form.dpi))
            enabled: panel.editable
            Accessible.name: qsTr("Resolution")
            onActivated: bridge.setDocumentField("dpi", currentValue)
        }

        QQC2.CheckBox {
            objectName: "docBothSidesBox"
            text: qsTr("Both sides (drop blank pages)")
            checked: bridge.documents.form.both_sides
            enabled: panel.editable
            Accessible.name: qsTr("Both sides (drop blank pages)")
            onToggled: bridge.setDocumentField("both_sides", checked)
        }

        // A detail of "Both sides": set in and smaller, so that it is not read as a second main choice.
        RowLayout {
            Item {
                implicitWidth: Kirigami.Units.gridUnit
            }

            QQC2.CheckBox {
                objectName: "docKeepBlankBox"
                text: qsTr("Keep blank pages")
                checked: bridge.documents.form.keep_blank
                enabled: panel.editable
                Accessible.name: qsTr("Keep blank pages")
                onToggled: bridge.setDocumentField("keep_blank", checked)
            }
        }

        Item {
            Kirigami.FormData.isSection: true
            Kirigami.FormData.label: qsTr("Searchable text")
        }

        QQC2.CheckBox {
            objectName: "docSearchableBox"
            text: qsTr("Searchable text")
            checked: bridge.documents.searchableChecked
            enabled: panel.editable && bridge.documents.ocrAvailable
            Accessible.name: qsTr("Searchable text")
            onToggled: bridge.setDocumentField("searchable", checked)
        }

        QQC2.Label {
            objectName: "docOcrHint"
            Layout.fillWidth: true
            Layout.preferredWidth: Kirigami.Units.gridUnit * 16
            Layout.minimumWidth: 0
            visible: bridge.documents.ocrHint !== ""
            text: bridge.documents.ocrHint
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            color: Kirigami.Theme.disabledTextColor
            font: Kirigami.Theme.smallFont
        }

        QQC2.TextField {
            objectName: "docLangsField"
            implicitWidth: Kirigami.Units.gridUnit * 16
            Kirigami.FormData.label: qsTr("Text language:")
            Layout.fillWidth: true
            text: bridge.documents.form.langs
            placeholderText: qsTr("eng, or eng+deu for two languages")
            enabled: panel.editable
            Accessible.name: qsTr("Text language")
            onTextEdited: bridge.setDocumentField("langs", text)
        }

        QQC2.Label {
            objectName: "docLangsError"
            Layout.fillWidth: true
            visible: panel.error("langs") !== ""
            text: panel.error("langs")
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            color: Kirigami.Theme.negativeTextColor
        }
    }

    FolderDialog {
        id: folderDialog

        title: qsTr("Choose the folder for the documents")
        onAccepted: bridge.setOutputFolderUrl(selectedFolder)
    }
}
