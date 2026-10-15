import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami

// One photo of the results grid: its picture, the back beside it when there is one, its name.
Item {
    id: cell

    required property string title
    required property string frontUrl
    required property string enhancedUrl
    required property string backUrl
    required property bool hasEnhanced
    required property bool hasBack

    property bool showEnhanced: false
    readonly property string pictureUrl: showEnhanced && hasEnhanced ? enhancedUrl : frontUrl

    Accessible.name: title
    Accessible.role: Accessible.ListItem

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Kirigami.Units.smallSpacing
        spacing: Kirigami.Units.smallSpacing

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: Kirigami.Units.smallSpacing

            Image {
                Layout.fillWidth: true
                Layout.fillHeight: true
                source: cell.pictureUrl
                sourceSize.width: 256
                sourceSize.height: 256
                fillMode: Image.PreserveAspectFit
                asynchronous: true
            }

            ColumnLayout {
                Layout.alignment: Qt.AlignTop
                visible: cell.hasBack
                spacing: 0

                Image {
                    Layout.preferredWidth: Kirigami.Units.gridUnit * 4
                    Layout.preferredHeight: Kirigami.Units.gridUnit * 4
                    source: cell.backUrl
                    sourceSize.width: 128
                    sourceSize.height: 128
                    fillMode: Image.PreserveAspectFit
                    asynchronous: true
                }

                QQC2.Label {
                    Layout.alignment: Qt.AlignHCenter
                    text: qsTr("back")
                    color: Kirigami.Theme.disabledTextColor
                    font: Kirigami.Theme.smallFont
                }
            }
        }

        QQC2.Label {
            Layout.fillWidth: true
            text: cell.title
            elide: Text.ElideRight
            horizontalAlignment: Text.AlignHCenter
        }
    }
}
