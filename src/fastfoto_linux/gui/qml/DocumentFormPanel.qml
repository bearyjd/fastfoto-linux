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
    readonly property bool editable: !bridge.busy && !bridge.documents.languages.busy

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

        QQC2.Button {
            objectName: "openPastScanButton"
            text: qsTr("Open a past scan…")
            Accessible.name: qsTr("Open a past scan…")
            enabled: panel.editable
            icon.name: "folder-open"
            onClicked: pastScanDialog.open()
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
            readonly property var colourChoices: [
                {
                    "text": qsTr("Auto"),
                    "value": "auto"
                },
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
            model: colourChoices
            textRole: "text"
            valueRole: "value"
            currentIndex: Math.max(0, colourChoices.findIndex(choice => choice.value === bridge.documents.form.colour))
            enabled: panel.editable
            Accessible.name: qsTr("Colour")
            onActivated: bridge.setDocumentField("colour", currentValue)
        }

        QQC2.ComboBox {
            objectName: "docCleanupBox"
            implicitWidth: Kirigami.Units.gridUnit * 16
            Kirigami.FormData.label: qsTr("Paper cleanup:")
            Layout.fillWidth: true
            readonly property var cleanupChoices: [
                {
                    "text": qsTr("Off"),
                    "value": "off"
                },
                {
                    "text": qsTr("Light"),
                    "value": "light"
                },
                {
                    "text": qsTr("Strong"),
                    "value": "strong"
                }
            ]
            model: cleanupChoices
            textRole: "text"
            valueRole: "value"
            currentIndex: Math.max(0, cleanupChoices.findIndex(choice => choice.value === bridge.documents.form.cleanup))
            enabled: panel.editable
            Accessible.name: qsTr("Paper cleanup")
            onActivated: bridge.setDocumentField("cleanup", currentValue)
        }

        QQC2.Label {
            objectName: "docCleanupHint"
            Layout.fillWidth: true
            text: qsTr("Off by default. Light and Strong lighten paper tone of grey and colour pages; black-and-white pages are not changed by paper cleanup. Check it in the preview.")
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            color: Kirigami.Theme.disabledTextColor
        }

        QQC2.ComboBox {
            objectName: "docPresetBox"
            implicitWidth: Kirigami.Units.gridUnit * 16
            Kirigami.FormData.label: qsTr("File size:")
            Layout.fillWidth: true
            readonly property var presetChoices: [
                {
                    "text": qsTr("Standard"),
                    "value": ""
                },
                {
                    "text": qsTr("High quality"),
                    "value": "high-quality"
                },
                {
                    "text": qsTr("Small"),
                    "value": "small"
                },
                {
                    "text": qsTr("Lossless"),
                    "value": "lossless"
                }
            ]
            model: presetChoices
            textRole: "text"
            valueRole: "value"
            currentIndex: Math.max(0, presetChoices.findIndex(choice => choice.value === bridge.documents.form.preset))
            enabled: panel.editable
            Accessible.name: qsTr("File size")
            onActivated: bridge.setDocumentField("preset", currentValue)
        }

        QQC2.Label {
            objectName: "docPresetHint"
            Layout.fillWidth: true
            text: qsTr("Standard keeps the page format as before. High quality uses a finer JPEG. Small stores pages at 200 dpi at most. Lossless stores colour and grey pages as PNG, which makes a large PDF. Black-and-white pages are always lossless.")
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            font: Kirigami.Theme.smallFont
        }

        QQC2.CheckBox {
            id: docDespeckleBoxControl
            objectName: "docDespeckleBox"
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            text: qsTr("Remove specks (black and white pages)")
            checked: bridge.documents.form.despeckle ?? false
            enabled: panel.editable
            Accessible.name: qsTr("Remove specks (black and white pages)")
            onToggled: bridge.setDocumentField("despeckle", checked)

            contentItem: QQC2.Label {
                leftPadding: docDespeckleBoxControl.indicator.width + docDespeckleBoxControl.spacing
                text: docDespeckleBoxControl.text
                textFormat: Text.PlainText
                wrapMode: Text.WordWrap
                verticalAlignment: Text.AlignVCenter
                opacity: docDespeckleBoxControl.enabled ? 1 : 0.5
            }
        }

        QQC2.Label {
            objectName: "docDespeckleHint"
            Layout.fillWidth: true
            text: qsTr("Remove specks deletes tiny isolated dots from black-and-white pages; dots near text are kept.")
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            color: Kirigami.Theme.disabledTextColor
        }

        QQC2.CheckBox {
            id: docDeskewBoxControl
            objectName: "docDeskewBox"
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            text: qsTr("Straighten tilted pages")
            checked: bridge.documents.form.deskew ?? false
            enabled: panel.editable
            Accessible.name: qsTr("Straighten tilted pages")
            onToggled: bridge.setDocumentField("deskew", checked)

            contentItem: QQC2.Label {
                leftPadding: docDeskewBoxControl.indicator.width + docDeskewBoxControl.spacing
                text: docDeskewBoxControl.text
                textFormat: Text.PlainText
                wrapMode: Text.WordWrap
                verticalAlignment: Text.AlignVCenter
                opacity: docDeskewBoxControl.enabled ? 1 : 0.5
            }
        }

        QQC2.Label {
            objectName: "docDeskewHint"
            Layout.fillWidth: true
            text: qsTr("Measures each new scan's page tilt (0.3 to 10 degrees) and straightens it; you can undo it per page in the review. Pages opened again are never measured.")
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            color: Kirigami.Theme.disabledTextColor
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
            id: docBothSidesBoxControl
            objectName: "docBothSidesBox"
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            text: qsTr("Both sides (drop blank pages)")
            checked: bridge.documents.form.both_sides
            enabled: panel.editable
            Accessible.name: qsTr("Both sides (drop blank pages)")
            onToggled: bridge.setDocumentField("both_sides", checked)

            contentItem: QQC2.Label {
                leftPadding: docBothSidesBoxControl.indicator.width + docBothSidesBoxControl.spacing
                text: docBothSidesBoxControl.text
                textFormat: Text.PlainText
                wrapMode: Text.WordWrap
                verticalAlignment: Text.AlignVCenter
                opacity: docBothSidesBoxControl.enabled ? 1 : 0.5
            }
        }

        // A detail of "Both sides": set in and smaller, so that it is not read as a second main choice.
        RowLayout {
            Item {
                implicitWidth: Kirigami.Units.gridUnit
            }

            QQC2.CheckBox {
                id: docKeepBlankBoxControl
                objectName: "docKeepBlankBox"
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                text: qsTr("Keep blank pages")
                checked: bridge.documents.form.keep_blank
                enabled: panel.editable
                Accessible.name: qsTr("Keep blank pages")
                onToggled: bridge.setDocumentField("keep_blank", checked)

                contentItem: QQC2.Label {
                    leftPadding: docKeepBlankBoxControl.indicator.width + docKeepBlankBoxControl.spacing
                    text: docKeepBlankBoxControl.text
                    textFormat: Text.PlainText
                    wrapMode: Text.WordWrap
                    verticalAlignment: Text.AlignVCenter
                    opacity: docKeepBlankBoxControl.enabled ? 1 : 0.5
                }
            }
        }

        Item {
            Kirigami.FormData.isSection: true
            Kirigami.FormData.label: qsTr("Searchable text")
        }

        QQC2.CheckBox {
            id: docSearchableBoxControl
            objectName: "docSearchableBox"
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            text: qsTr("Searchable text")
            checked: bridge.documents.searchableChecked
            enabled: panel.editable && bridge.documents.ocrAvailable
            Accessible.name: qsTr("Searchable text")
            onToggled: bridge.setDocumentField("searchable", checked)

            contentItem: QQC2.Label {
                leftPadding: docSearchableBoxControl.indicator.width + docSearchableBoxControl.spacing
                text: docSearchableBoxControl.text
                textFormat: Text.PlainText
                wrapMode: Text.WordWrap
                verticalAlignment: Text.AlignVCenter
                opacity: docSearchableBoxControl.enabled ? 1 : 0.5
            }
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

        OcrLanguagePicker {
            Kirigami.FormData.label: qsTr("Text languages:")
            Layout.fillWidth: true
            editable: panel.editable
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
        id: pastScanDialog
        objectName: "pastScanDialog"
        title: qsTr("Open a past scan")
        currentFolder: bridge.review.rawRootUrl
        onAccepted: bridge.review.openFolder(selectedFolder)
    }

    FolderDialog {
        id: folderDialog

        title: qsTr("Choose the folder for the documents")
        onAccepted: bridge.setOutputFolderUrl(selectedFolder)
    }
}
