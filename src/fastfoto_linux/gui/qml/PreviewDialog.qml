import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami

QQC2.Dialog {
    id: dialog
    objectName: "reviewPreviewDialog"
    property int turns: 0
    property int pageNumber: 0
    readonly property bool outputView: (bridge.review.previewView ?? "source") === "output"
    parent: QQC2.Overlay.overlay
    anchors.centerIn: parent
    width: Math.min(parent ? parent.width - 32 : 800, 1100)
    height: Math.min(parent ? parent.height - 32 : 600, 900)
    title: qsTr("Page %1").arg(dialog.pageNumber)
    modal: true
    standardButtons: QQC2.Dialog.Close

    Connections {
        target: bridge.review
        function onChanged() {
            if (dialog.visible && bridge.bannerKind === "error" && bridge.review.previewUrl === "") {
                dialog.close();
            }
        }
    }

    contentItem: ColumnLayout {
        RowLayout {
            Layout.fillWidth: true
            QQC2.ComboBox {
                objectName: "reviewPreviewViewBox"
                model: [
                    { "text": qsTr("Source"), "value": "source" },
                    { "text": qsTr("Output"), "value": "output" }
                ]
                textRole: "text"
                valueRole: "value"
                currentIndex: dialog.outputView ? 1 : 0
                Accessible.name: qsTr("Preview view")
                onActivated: bridge.review.previewMode(dialog.pageNumber, currentValue)
            }
            QQC2.Label {
                objectName: "reviewPreviewKindLabel"
                Layout.fillWidth: true
                text: bridge.review.previewLabel ?? qsTr("Source preview")
                textFormat: Text.PlainText
                wrapMode: Text.WordWrap
            }
        }
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Item {
                objectName: "reviewPreviewFrame"
                anchors.centerIn: parent
                readonly property int displayTurns: dialog.outputView ? 0 : dialog.turns
                width: displayTurns % 2 ? parent.height : parent.width
                height: displayTurns % 2 ? parent.width : parent.height
                rotation: displayTurns * 90
                Image {
                    objectName: "reviewPreviewImage"
                    anchors.fill: parent
                    source: dialog.visible ? bridge.review.previewUrl : ""
                    sourceSize.width: 1600
                    sourceSize.height: 1600
                    asynchronous: true
                    cache: false
                    fillMode: Image.PreserveAspectFit
                }
            }
            QQC2.BusyIndicator {
                anchors.centerIn: parent
                running: dialog.visible && bridge.review.previewUrl === ""
                visible: running
            }
        }
    }
}
