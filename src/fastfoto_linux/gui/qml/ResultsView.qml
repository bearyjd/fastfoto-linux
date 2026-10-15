import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami

ColumnLayout {
    id: results

    // Show the enhanced copy of each photo instead of the original.
    property bool showEnhanced: false

    spacing: Kirigami.Units.smallSpacing

    RowLayout {
        Layout.fillWidth: true

        Kirigami.Heading {
            level: 3
            text: bridge.photoCount === 0 ? qsTr("Photos") : qsTr("Photos (%1)").arg(bridge.photoCount)
        }

        Item {
            Layout.fillWidth: true
        }

        QQC2.Switch {
            objectName: "enhancedSwitch"
            text: qsTr("Show enhanced copies")
            checked: results.showEnhanced
            Accessible.name: qsTr("Show enhanced copies")
            onToggled: results.showEnhanced = checked
        }

        QQC2.Button {
            objectName: "openFolderButton"
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

        GridView {
            id: grid

            objectName: "photosGrid"
            anchors.fill: parent
            clip: true
            model: bridge.photos
            cellWidth: Kirigami.Units.gridUnit * 13
            cellHeight: Kirigami.Units.gridUnit * 12
            activeFocusOnTab: true
            keyNavigationEnabled: true
            highlightFollowsCurrentItem: true
            Accessible.name: qsTr("Scanned photos")
            Accessible.role: Accessible.List

            // Shows where the keyboard is, only while the grid has the focus.
            highlight: Rectangle {
                visible: grid.activeFocus
                color: Kirigami.Theme.highlightColor
                opacity: 0.25
                radius: Kirigami.Units.smallSpacing
            }

            QQC2.ScrollBar.vertical: QQC2.ScrollBar {}

            delegate: PhotoCell {
                width: grid.cellWidth
                height: grid.cellHeight
                showEnhanced: results.showEnhanced
            }
        }

        Kirigami.PlaceholderMessage {
            objectName: "emptyPlaceholder"
            anchors.centerIn: parent
            width: parent.width - Kirigami.Units.gridUnit * 4
            visible: grid.count === 0
            icon.name: "view-preview"
            text: qsTr("No photos yet")
            explanation: qsTr("Load photos in the feeder, check the settings and press Scan. Each photo appears here as it is saved.")
        }
    }
}
