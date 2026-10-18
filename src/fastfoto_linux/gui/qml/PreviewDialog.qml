import QtQuick
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami

QQC2.Dialog {
    id: dialog
    objectName: "reviewPreviewDialog"
    property int turns: 0
    property int pageNumber: 0
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

    contentItem: Item {
        Item {
            objectName: "reviewPreviewFrame"
            anchors.centerIn: parent
            width: dialog.turns % 2 ? parent.height : parent.width
            height: dialog.turns % 2 ? parent.width : parent.height
            rotation: dialog.turns * 90
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
