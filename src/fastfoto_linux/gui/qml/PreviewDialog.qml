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
    // The hand crop is drawn on the source view, which is the trimmed page, not turned.
    property bool cropMode: false
    property bool cropRejected: false
    readonly property var cropRect: bridge.review.previewCropRect ?? []
    readonly property bool cropped: cropRect.length === 4

    function endCrop() {
        cropMode = false;
        cropRejected = false;
        cropOverlay.pending = null;
    }
    function beginCrop() {
        cropRejected = false;
        cropOverlay.start();
        cropMode = true;
        cropOverlay.forceActiveFocus();
    }
    onOutputViewChanged: endCrop()
    onPageNumberChanged: endCrop()
    onVisibleChanged: if (!visible) endCrop()

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
            visible: !dialog.outputView
            QQC2.Button {
                objectName: "reviewCropButton"
                text: qsTr("Crop")
                highlighted: dialog.cropMode
                enabled: bridge.review.previewCropMode ?? false
                Accessible.name: qsTr("Crop")
                onClicked: dialog.cropMode ? dialog.endCrop() : dialog.beginCrop()
            }
            QQC2.Button {
                objectName: "reviewCropResetButton"
                text: qsTr("Reset crop")
                enabled: dialog.cropped
                Accessible.name: qsTr("Reset crop")
                onClicked: {
                    dialog.endCrop();
                    bridge.review.clearCrop(dialog.pageNumber);
                }
            }
            QQC2.Label {
                objectName: "reviewCropHint"
                Layout.fillWidth: true
                visible: dialog.cropMode
                text: qsTr("Drag a rectangle on the page to keep only that area. The page is not analysed again.")
                textFormat: Text.PlainText
                wrapMode: Text.WordWrap
            }
            QQC2.Label {
                objectName: "reviewCropTooSmall"
                visible: dialog.cropMode && dialog.cropRejected
                text: qsTr("The crop must be at least 5 mm on each side.")
                textFormat: Text.PlainText
                color: Kirigami.Theme.negativeTextColor
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
                readonly property int displayTurns: dialog.outputView || dialog.cropMode ? 0 : dialog.turns
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
                Item {
                    id: cropOverlay
                    objectName: "reviewCropOverlay"
                    anchors.fill: parent
                    visible: !dialog.outputView
                    activeFocusOnTab: dialog.cropMode
                    Accessible.role: Accessible.Graphic
                    Accessible.name: qsTr("Crop area")
                    Accessible.description: qsTr("Drag a rectangle, or use the arrow keys to move it and Shift with the arrow keys to resize it. Enter applies the crop and Escape cancels.")
                    // The painted page inside this item, and the rectangle being chosen, as
                    // [left, top, right, bottom] in this item's pixels (null when none).
                    readonly property real padX: (width - fittedImage.paintedWidth) / 2
                    readonly property real padY: (height - fittedImage.paintedHeight) / 2
                    property var pending: null
                    readonly property var shown: pending !== null ? pending : committed()
                    readonly property real keyStep: 0.01

                    function committed() {
                        const r = dialog.cropRect;
                        const sw = bridge.review.previewSourceWidth;
                        const sh = bridge.review.previewSourceHeight;
                        if (r.length !== 4 || sw <= 0 || sh <= 0) return null;
                        return [padX + r[0] * fittedImage.paintedWidth / sw, padY + r[1] * fittedImage.paintedHeight / sh,
                                padX + r[2] * fittedImage.paintedWidth / sw, padY + r[3] * fittedImage.paintedHeight / sh];
                    }
                    function start() {
                        const w = fittedImage.paintedWidth, h = fittedImage.paintedHeight;
                        pending = committed() ?? [padX + 0.1 * w, padY + 0.1 * h, padX + 0.9 * w, padY + 0.9 * h];
                    }
                    function apply() {
                        if (pending === null) return;
                        const ok = bridge.review.cropFromDrag(dialog.pageNumber, pending[0], pending[1], pending[2], pending[3],
                                                              fittedImage.paintedWidth, fittedImage.paintedHeight, width, height);
                        if (ok) dialog.endCrop();
                        else dialog.cropRejected = true;
                    }
                    function nudge(dx, dy, resize) {
                        if (pending === null) return;
                        const p = pending.slice();
                        const right = padX + fittedImage.paintedWidth, bottom = padY + fittedImage.paintedHeight;
                        if (resize) {
                            p[2] = Math.max(p[0] + 1, Math.min(right, p[2] + dx));
                            p[3] = Math.max(p[1] + 1, Math.min(bottom, p[3] + dy));
                        } else {
                            const mx = Math.max(padX - p[0], Math.min(right - p[2], dx));
                            const my = Math.max(padY - p[1], Math.min(bottom - p[3], dy));
                            p[0] += mx; p[2] += mx; p[1] += my; p[3] += my;
                        }
                        pending = p;
                    }

                    Keys.onPressed: event => {
                        if (!dialog.cropMode) return;
                        const dx = fittedImage.paintedWidth * keyStep, dy = fittedImage.paintedHeight * keyStep;
                        const resize = (event.modifiers & Qt.ShiftModifier) !== 0;
                        switch (event.key) {
                        case Qt.Key_Left: nudge(-dx, 0, resize); break;
                        case Qt.Key_Right: nudge(dx, 0, resize); break;
                        case Qt.Key_Up: nudge(0, -dy, resize); break;
                        case Qt.Key_Down: nudge(0, dy, resize); break;
                        case Qt.Key_Return: case Qt.Key_Enter: apply(); break;
                        case Qt.Key_Escape: dialog.endCrop(); break;
                        default: return;
                        }
                        event.accepted = true;
                    }

                    Rectangle {
                        objectName: "reviewCropRect"
                        visible: cropOverlay.shown !== null
                        x: cropOverlay.shown ? cropOverlay.shown[0] : 0
                        y: cropOverlay.shown ? cropOverlay.shown[1] : 0
                        width: cropOverlay.shown ? cropOverlay.shown[2] - cropOverlay.shown[0] : 0
                        height: cropOverlay.shown ? cropOverlay.shown[3] - cropOverlay.shown[1] : 0
                        color: "transparent"
                        border.width: 2
                        border.color: dialog.cropMode ? Kirigami.Theme.highlightColor : "#ffffff"
                    }
                    MouseArea {
                        property point origin: Qt.point(0, 0)
                        anchors.fill: parent
                        enabled: dialog.cropMode
                        cursorShape: Qt.CrossCursor
                        onPressed: mouse => {
                            cropOverlay.forceActiveFocus();
                            origin = Qt.point(mouse.x, mouse.y);
                        }
                        onPositionChanged: mouse => cropOverlay.pending = [origin.x, origin.y, mouse.x, mouse.y]
                        onReleased: mouse => {
                            if (Math.hypot(mouse.x - origin.x, mouse.y - origin.y) < 3) return;
                            cropOverlay.pending = [origin.x, origin.y, mouse.x, mouse.y];
                            cropOverlay.apply();
                        }
                    }
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
