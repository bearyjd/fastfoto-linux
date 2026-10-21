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
    readonly property bool cleaned: bridge.review.previewCleaned ?? true
    readonly property bool actualView: outputView && (bridge.review.previewActual ?? false)

    function pick(cleaned, actual) {
        bridge.review.previewOptions(dialog.pageNumber, cleaned, actual, bridge.review.previewCropX ?? 500, bridge.review.previewCropY ?? 500);
    }
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
        RowLayout {
            Layout.fillWidth: true
            visible: dialog.outputView
            QQC2.Switch {
                id: cleanupSwitch
                objectName: "reviewPreviewCleanupSwitch"
                text: qsTr("Paper cleanup")
                checked: dialog.cleaned
                enabled: bridge.review.previewCleanupAvailable ?? false
                Accessible.name: qsTr("Paper cleanup")
                onToggled: {
                    dialog.pick(checked, dialog.actualView);
                    checked = Qt.binding(() => dialog.cleaned);
                }
            }
            QQC2.Switch {
                id: actualSwitch
                objectName: "reviewPreviewActualSwitch"
                text: qsTr("Actual pixels")
                checked: dialog.actualView
                Accessible.name: qsTr("Actual pixels")
                onToggled: {
                    dialog.pick(dialog.cleaned, checked);
                    checked = Qt.binding(() => dialog.actualView);
                }
            }
            QQC2.Label {
                objectName: "reviewPreviewCropHint"
                Layout.fillWidth: true
                text: qsTr("Click the page to inspect that spot at actual pixels.")
                textFormat: Text.PlainText
                wrapMode: Text.WordWrap
            }
        }
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Item {
                objectName: "reviewPreviewFrame"
                visible: !dialog.actualView
                anchors.centerIn: parent
                readonly property int displayTurns: dialog.outputView ? 0 : dialog.turns
                width: displayTurns % 2 ? parent.height : parent.width
                height: displayTurns % 2 ? parent.width : parent.height
                rotation: displayTurns * 90
                Image {
                    id: fittedImage
                    objectName: "reviewPreviewImage"
                    anchors.fill: parent
                    source: dialog.visible && !dialog.actualView ? bridge.review.previewUrl : ""
                    sourceSize.width: 1600
                    sourceSize.height: 1600
                    asynchronous: true
                    cache: false
                    fillMode: Image.PreserveAspectFit
                }
                MouseArea {
                    objectName: "reviewPreviewPickArea"
                    anchors.fill: parent
                    enabled: dialog.outputView
                    cursorShape: Qt.CrossCursor
                    onClicked: mouse => {
                        const image = fittedImage;
                        if (image.paintedWidth <= 0 || image.paintedHeight <= 0) return;
                        const fx = (mouse.x - (width - image.paintedWidth) / 2) / image.paintedWidth;
                        const fy = (mouse.y - (height - image.paintedHeight) / 2) / image.paintedHeight;
                        bridge.review.previewOptions(dialog.pageNumber, dialog.cleaned, true, Math.round(1000 * Math.max(0, Math.min(1, fx))), Math.round(1000 * Math.max(0, Math.min(1, fy))));
                    }
                }
            }
            Flickable {
                objectName: "reviewPreviewCropFlick"
                anchors.fill: parent
                visible: dialog.actualView
                clip: true
                contentWidth: cropImage.width
                contentHeight: cropImage.height
                QQC2.ScrollBar.vertical: QQC2.ScrollBar {}
                QQC2.ScrollBar.horizontal: QQC2.ScrollBar {}
                Image {
                    id: cropImage
                    objectName: "reviewPreviewCropImage"
                    source: dialog.visible && dialog.actualView ? bridge.review.previewUrl : ""
                    asynchronous: true
                    cache: false
                    fillMode: Image.Pad
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
