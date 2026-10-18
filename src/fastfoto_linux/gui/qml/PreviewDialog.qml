import QtQuick
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami

QQC2.Dialog {
    id: dialog
    objectName: "reviewPreviewDialog"
    parent: QQC2.Overlay.overlay
    anchors.centerIn: parent
    width: Math.min(parent ? parent.width - 32 : 800, 1100)
    height: Math.min(parent ? parent.height - 32 : 600, 900)
    title: qsTr("Page %1").arg(bridge.review.previewNumber)
    modal: true
    standardButtons: QQC2.Dialog.Close

    contentItem: Item {
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
        QQC2.BusyIndicator {
            anchors.centerIn: parent
            running: dialog.visible && bridge.review.previewUrl === ""
            visible: running
        }
    }
}
