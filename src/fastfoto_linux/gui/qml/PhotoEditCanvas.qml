import QtQuick

Item {
    id: canvas
    objectName: "photoEditCanvas"
    property string imageUrl: ""
    property int sourceWidth: 0
    property int sourceHeight: 0
    property real viewZoom: 1
    property real panX: 0
    property real panY: 0
    property bool manualMode: false
    property bool canEdit: true
    property bool showEyes: true
    property bool cropMode: false
    property var crop: [0, 0, 0, 0]
    property int minCropWidth: 1
    property int minCropHeight: 1
    property real defaultRadius: 1
    property var candidates: []
    property string selectedId: ""
    readonly property real clickTolerance: 3
    signal ellipseRequested(real cx, real cy, real rx, real ry)
    signal eyeSelected(string eyeId)
    signal cropRequested(int left, int top, int right, int bottom)
    signal cropRejected()
    clip: true
    focus: true
    activeFocusOnTab: true
    Accessible.role: Accessible.Graphic
    Accessible.name: qsTr("Photo red-eye preview")
    Accessible.description: qsTr("Add eye mode: click or drag an ellipse. Use plus and minus to zoom, arrow keys or middle-drag to pan.")

    function sourcePoint(x: real, y: real): point {
        const p = picture.mapFromItem(canvas, x, y);
        const w = picture.paintedWidth;
        const h = picture.paintedHeight;
        const left = (picture.width - w) / 2;
        const top = (picture.height - h) / 2;
        if (w <= 0 || h <= 0 || sourceWidth <= 0 || sourceHeight <= 0 ||
                !isFinite(p.x) || !isFinite(p.y) ||
                p.x < left || p.y < top || p.x > left + w || p.y > top + h)
            return Qt.point(-1, -1);
        return Qt.point((p.x - left) * sourceWidth / w, (p.y - top) * sourceHeight / h);
    }

    // Mirrors photoeditcoords.source_crop: clamp into the painted image, floor and ceil to pixels.
    function sourceCrop(x0: real, y0: real, x1: real, y1: real): var {
        const w = picture.paintedWidth;
        const h = picture.paintedHeight;
        if (w <= 0 || h <= 0 || sourceWidth <= 0 || sourceHeight <= 0 ||
                ![x0, y0, x1, y1].every(isFinite))
            return null;
        const left = (picture.width - w) / 2;
        const top = (picture.height - h) / 2;
        const a = picture.mapFromItem(canvas, x0, y0);
        const b = picture.mapFromItem(canvas, x1, y1);
        const across = (v, origin, painted, source) =>
            Math.round((Math.min(Math.max(v, origin), origin + painted) - origin) * source / painted * 1e6) / 1e6;
        const xs = [across(a.x, left, w, sourceWidth), across(b.x, left, w, sourceWidth)].sort((p, q) => p - q);
        const ys = [across(a.y, top, h, sourceHeight), across(b.y, top, h, sourceHeight)].sort((p, q) => p - q);
        const box = [Math.floor(xs[0]), Math.floor(ys[0]),
                     Math.min(sourceWidth, Math.ceil(xs[1])), Math.min(sourceHeight, Math.ceil(ys[1]))];
        if (box[2] - box[0] < Math.max(1, minCropWidth) || box[3] - box[1] < Math.max(1, minCropHeight))
            return null;
        return box;
    }

    function commitEllipse(x0: real, y0: real, x1: real, y1: real): void {
        const a = sourcePoint(x0, y0);
        const b = sourcePoint(x1, y1);
        if (!canEdit || a.x < 0 || b.x < 0) return;
        const rx = Math.abs(b.x - a.x) / 2;
        const ry = Math.abs(b.y - a.y) / 2;
        if (rx > 0 && ry > 0)
            ellipseRequested((a.x + b.x) / 2, (a.y + b.y) / 2, rx, ry);
    }

    function fit(): void { viewZoom = 1; panX = 0; panY = 0; }
    function zoom(factor: real): void { viewZoom = Math.max(1, Math.min(8, viewZoom * factor)); }

    Keys.onPressed: event => {
        switch (event.key) {
        case Qt.Key_Plus: case Qt.Key_Equal: zoom(1.25); break;
        case Qt.Key_Minus: zoom(0.8); break;
        case Qt.Key_Left: panX += 20; break;
        case Qt.Key_Right: panX -= 20; break;
        case Qt.Key_Up: panY += 20; break;
        case Qt.Key_Down: panY -= 20; break;
        case Qt.Key_0: fit(); break;
        default: return;
        }
        event.accepted = true;
    }

    Image {
        id: picture
        objectName: "photoCanvasImage"
        x: canvas.panX
        y: canvas.panY
        width: canvas.width
        height: canvas.height
        scale: canvas.viewZoom
        transformOrigin: Item.Center
        source: canvas.imageUrl
        fillMode: Image.PreserveAspectFit
        cache: false
        smooth: true

        Repeater {
            model: canvas.showEyes ? canvas.candidates : []
            delegate: Rectangle {
                objectName: "photoEyeMarker"
                required property var modelData
                x: (picture.width - picture.paintedWidth) / 2 + modelData.roi[0] * picture.paintedWidth / canvas.sourceWidth
                y: (picture.height - picture.paintedHeight) / 2 + modelData.roi[1] * picture.paintedHeight / canvas.sourceHeight
                width: (modelData.roi[2] - modelData.roi[0]) * picture.paintedWidth / canvas.sourceWidth
                height: (modelData.roi[3] - modelData.roi[1]) * picture.paintedHeight / canvas.sourceHeight
                color: "transparent"
                border.width: modelData.id === canvas.selectedId ? 2 / canvas.viewZoom : 1 / canvas.viewZoom
                border.color: modelData.id === canvas.selectedId ? "#ffffff" : (modelData.accepted ? "#75d69c" : "#ffcd70")
                visible: canvas.showEyes && canvas.sourceWidth > 0 && canvas.sourceHeight > 0
            }
        }

        Rectangle {
            objectName: "photoCropRect"
            readonly property bool valid: canvas.cropMode && canvas.sourceWidth > 0 &&
                canvas.sourceHeight > 0 && canvas.crop.length === 4
            x: (picture.width - picture.paintedWidth) / 2 + canvas.crop[0] * picture.paintedWidth / canvas.sourceWidth
            y: (picture.height - picture.paintedHeight) / 2 + canvas.crop[1] * picture.paintedHeight / canvas.sourceHeight
            width: (canvas.crop[2] - canvas.crop[0]) * picture.paintedWidth / canvas.sourceWidth
            height: (canvas.crop[3] - canvas.crop[1]) * picture.paintedHeight / canvas.sourceHeight
            color: "transparent"
            border.width: 2 / canvas.viewZoom
            border.color: "#ffffff"
            visible: valid
        }
    }

    MouseArea {
        id: pointer
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton | Qt.MiddleButton
        property point start: Qt.point(0, 0)
        property point panStart: Qt.point(0, 0)
        property point current: Qt.point(0, 0)
        property bool drawing: false
        property bool cropping: false
        readonly property bool eyeMode: canvas.showEyes && canvas.manualMode
        cursorShape: (eyeMode || canvas.cropMode) ? Qt.CrossCursor : Qt.ArrowCursor
        onPressed: mouse => {
            canvas.forceActiveFocus();
            start = Qt.point(mouse.x, mouse.y);
            current = start;
            panStart = Qt.point(canvas.panX, canvas.panY);
            drawing = mouse.button === Qt.LeftButton && eyeMode && canvas.canEdit;
            cropping = mouse.button === Qt.LeftButton && canvas.cropMode && canvas.canEdit;
        }
        onPositionChanged: mouse => {
            current = Qt.point(mouse.x, mouse.y);
            if (pressedButtons & Qt.MiddleButton) {
                canvas.panX = panStart.x + mouse.x - start.x;
                canvas.panY = panStart.y + mouse.y - start.y;
            }
        }
        onReleased: mouse => {
            drawing = false;
            const wasCropping = cropping;
            cropping = false;
            if (mouse.button !== Qt.LeftButton || !canvas.canEdit) return;
            if (wasCropping) {
                if (Math.hypot(mouse.x - start.x, mouse.y - start.y) < canvas.clickTolerance) return;
                const box = canvas.sourceCrop(start.x, start.y, mouse.x, mouse.y);
                if (box !== null) canvas.cropRequested(box[0], box[1], box[2], box[3]);
                else canvas.cropRejected();
                return;
            }
            if (!canvas.showEyes) return;
            const p = canvas.sourcePoint(mouse.x, mouse.y);
            if (p.x < 0) return;
            if (eyeMode) {
                if (Math.hypot(mouse.x - start.x, mouse.y - start.y) < canvas.clickTolerance)
                    canvas.ellipseRequested(p.x, p.y, canvas.defaultRadius, canvas.defaultRadius);
                else canvas.commitEllipse(start.x, start.y, mouse.x, mouse.y);
            } else {
                for (const eye of canvas.candidates) {
                    const r = eye.roi;
                    if (p.x >= r[0] && p.x < r[2] && p.y >= r[1] && p.y < r[3]) {
                        canvas.eyeSelected(eye.id);
                        break;
                    }
                }
            }
        }
        onCanceled: { drawing = false; cropping = false; }
    }

    Rectangle {
        x: Math.min(pointer.start.x, pointer.current.x)
        y: Math.min(pointer.start.y, pointer.current.y)
        width: Math.abs(pointer.start.x - pointer.current.x)
        height: Math.abs(pointer.start.y - pointer.current.y)
        radius: Math.min(width, height) / 2
        visible: pointer.drawing
        color: "transparent"
        border.color: "white"
        border.width: 1
    }

    Rectangle {
        x: Math.min(pointer.start.x, pointer.current.x)
        y: Math.min(pointer.start.y, pointer.current.y)
        width: Math.abs(pointer.start.x - pointer.current.x)
        height: Math.abs(pointer.start.y - pointer.current.y)
        visible: pointer.cropping
        color: "transparent"
        border.color: "white"
        border.width: 1
    }

    WheelHandler {
        onWheel: event => { canvas.zoom(event.angleDelta.y > 0 ? 1.25 : 0.8); event.accepted = true; }
    }
}
