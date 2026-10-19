import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami

// One photo of the results grid: its picture, the back beside it when there is one, its name.
// A sheet saved whole (not processed) says so over the bottom of its picture, with the reason.
// A whole page of which only the back could be read shows that back once, labelled as the back.
Item {
    id: cell

    required property string title
    required property string frontUrl
    required property string enhancedUrl
    required property string backUrl
    required property bool hasEnhanced
    required property bool hasBack
    required property bool unprocessed
    required property string reason
    required property bool backOnly

    property var editReview: null
    property int photoRow: -1
    property bool reviewEligible: false
    property string reviewReason: ""
    property bool showEnhanced: false
    readonly property string pictureUrl: showEnhanced && hasEnhanced ? enhancedUrl : frontUrl

    Accessible.name: unprocessed ? qsTr("%1, not processed: %2").arg(title).arg(reason) : title
    Accessible.role: Accessible.ListItem

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Kirigami.Units.smallSpacing
        spacing: Kirigami.Units.smallSpacing

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: Kirigami.Units.smallSpacing

            // The front always gets the same frame, and the back its own fixed room whether
            // or not there is one, so every cell is laid out alike.
            Item {
                objectName: "frontFrame"
                Layout.fillWidth: true
                Layout.fillHeight: true

                Image {
                    objectName: "frontImage"
                    anchors.fill: parent
                    source: cell.pictureUrl
                    sourceSize.width: 256
                    sourceSize.height: 256
                    fillMode: Image.PreserveAspectFit
                    asynchronous: true
                }

                Rectangle {
                    objectName: "backOnlyBadge"
                    anchors.left: parent.left
                    anchors.top: parent.top
                    width: backOnlyLabel.implicitWidth + 2 * Kirigami.Units.smallSpacing
                    height: backOnlyLabel.implicitHeight + 2 * Kirigami.Units.smallSpacing
                    visible: cell.backOnly
                    color: Kirigami.Theme.backgroundColor
                    opacity: 0.85

                    QQC2.Label {
                        id: backOnlyLabel

                        objectName: "backOnlyLabel"
                        anchors.centerIn: parent
                        text: qsTr("Back page")
                        textFormat: Text.PlainText
                        font: Kirigami.Theme.smallFont
                    }
                }

                Rectangle {
                    objectName: "unprocessedBadge"
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    height: badge.implicitHeight + 2 * Kirigami.Units.smallSpacing
                    visible: cell.unprocessed
                    color: Kirigami.Theme.negativeBackgroundColor

                    ColumnLayout {
                        id: badge

                        anchors.fill: parent
                        anchors.margins: Kirigami.Units.smallSpacing
                        spacing: 0

                        QQC2.Label {
                            objectName: "notProcessedLabel"
                            Layout.fillWidth: true
                            text: qsTr("Not processed")
                            textFormat: Text.PlainText
                            font.bold: true
                            color: Kirigami.Theme.negativeTextColor
                        }

                        QQC2.Label {
                            objectName: "reasonLabel"
                            Layout.fillWidth: true
                            text: cell.reason
                            textFormat: Text.PlainText
                            wrapMode: Text.WordWrap
                            maximumLineCount: 3
                            elide: Text.ElideRight
                            font: Kirigami.Theme.smallFont
                        }
                    }
                }
            }

            Item {
                Layout.preferredWidth: Kirigami.Units.gridUnit * 4
                Layout.fillHeight: true

                ColumnLayout {
                    anchors.top: parent.top
                    anchors.left: parent.left
                    anchors.right: parent.right
                    visible: cell.hasBack
                    spacing: 0

                    Image {
                        objectName: "backImage"
                        Layout.fillWidth: true
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
                        textFormat: Text.PlainText
                        color: Kirigami.Theme.disabledTextColor
                        font: Kirigami.Theme.smallFont
                    }
                }
            }
        }

        QQC2.Button {
            objectName: "reviewRedEyesButton"
            Layout.alignment: Qt.AlignHCenter
            visible: cell.editReview !== null
            text: qsTr("Review red eyes")
            enabled: cell.reviewEligible && cell.editReview !== null && !cell.editReview.busy
            Accessible.name: qsTr("Review red eyes")
            Accessible.description: cell.title + ". " + cell.reviewReason
            onClicked: cell.editReview.openPhoto(cell.photoRow)
            QQC2.ToolTip.visible: hovered && cell.reviewReason !== ""
            QQC2.ToolTip.text: cell.reviewReason
        }
        QQC2.Label {
            Layout.fillWidth: true
            visible: cell.editReview !== null && !cell.reviewEligible
            text: cell.reviewReason
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            maximumLineCount: 2
            elide: Text.ElideRight
            font: Kirigami.Theme.smallFont
        }
        QQC2.Label {
            Layout.fillWidth: true
            text: cell.title
            textFormat: Text.PlainText
            elide: Text.ElideRight
            horizontalAlignment: Text.AlignHCenter
        }
    }
}
