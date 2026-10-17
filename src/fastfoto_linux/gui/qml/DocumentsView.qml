import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami

// The PDFs this run made: file name, pages, blank pages left out, searchable text, and Open.
ColumnLayout {
    id: results

    objectName: "documentsResults"
    spacing: Kirigami.Units.smallSpacing

    RowLayout {
        Layout.fillWidth: true

        Kirigami.Heading {
            objectName: "documentsHeading"
            level: 3
            text: bridge.documents.heading
        }

        Item {
            Layout.fillWidth: true
        }

        QQC2.Button {
            objectName: "openDocumentsFolderButton"
            text: qsTr("Open folder")
            icon.name: "document-open-folder"
            enabled: bridge.outputUrl !== ""
            Accessible.name: qsTr("Open folder")
            onClicked: Qt.openUrlExternally(bridge.outputUrl)
        }
    }

    Item {
        Layout.fillWidth: true
        Layout.fillHeight: true

        ListView {
            id: list

            objectName: "documentsList"
            anchors.fill: parent
            clip: true
            model: bridge.documents.items
            spacing: Kirigami.Units.smallSpacing
            activeFocusOnTab: true
            keyNavigationEnabled: true
            Accessible.name: qsTr("Scanned documents")
            Accessible.role: Accessible.List

            QQC2.ScrollBar.vertical: QQC2.ScrollBar {}

            delegate: Item {
                id: row

                required property string fileName
                required property string folder
                required property string fileUrl
                required property string pagesText
                required property string droppedText
                required property bool hasDropped
                required property string searchableText
                required property bool ocrWarning

                width: list.width
                implicitHeight: content.implicitHeight + Kirigami.Units.largeSpacing * 2
                height: implicitHeight
                Accessible.name: fileName
                Accessible.role: Accessible.ListItem

                RowLayout {
                    id: content

                    anchors.fill: parent
                    anchors.margins: Kirigami.Units.smallSpacing
                    spacing: Kirigami.Units.largeSpacing

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: Kirigami.Units.smallSpacing

                        QQC2.Label {
                            objectName: "documentFileName"
                            Layout.fillWidth: true
                            text: row.fileName
                            textFormat: Text.PlainText
                            elide: Text.ElideMiddle
                            font.bold: true
                        }

                        QQC2.Label {
                            objectName: "documentPages"
                            Layout.fillWidth: true
                            text: row.pagesText
                            textFormat: Text.PlainText
                        }

                        QQC2.Label {
                            objectName: "documentDropped"
                            Layout.fillWidth: true
                            visible: row.hasDropped
                            text: row.droppedText
                            textFormat: Text.PlainText
                            wrapMode: Text.WordWrap
                        }

                        QQC2.Label {
                            objectName: "documentSearchable"
                            Layout.fillWidth: true
                            text: row.searchableText
                            textFormat: Text.PlainText
                            wrapMode: Text.WordWrap
                            color: row.ocrWarning ? Kirigami.Theme.neutralTextColor : Kirigami.Theme.textColor
                        }

                        QQC2.Label {
                            objectName: "documentFolder"
                            Layout.fillWidth: true
                            text: row.folder
                            textFormat: Text.PlainText
                            elide: Text.ElideMiddle
                            color: Kirigami.Theme.disabledTextColor
                            font: Kirigami.Theme.smallFont
                        }
                    }

                    // In a Flatpak the desktop's portal opens the file; the call is the same.
                    QQC2.Button {
                        objectName: "openDocumentButton"
                        Layout.alignment: Qt.AlignTop
                        text: qsTr("Open")
                        icon.name: "document-open"
                        enabled: row.fileUrl !== ""
                        Accessible.name: qsTr("Open")
                        Accessible.description: qsTr("Open %1").arg(row.fileName)
                        onClicked: Qt.openUrlExternally(row.fileUrl)
                    }
                }
            }
        }

        Kirigami.PlaceholderMessage {
            objectName: "documentsPlaceholder"
            anchors.centerIn: parent
            width: parent.width - Kirigami.Units.gridUnit * 4
            visible: list.count === 0
            icon.name: "x-office-document"
            text: qsTr("No documents yet")
            explanation: qsTr("Load the pages in the feeder, check the settings and press Scan. The PDF appears here when it is made.")
        }
    }
}
