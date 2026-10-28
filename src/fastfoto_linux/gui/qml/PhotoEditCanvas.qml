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
    property var cropRatio: []  // [rw, rh] in the shown frame; [] = free
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
        return box.every(isFinite) ? box : null;
    }

    // Mirrors photoeditaspect.aspect_crop (the ratio drag): the raw box, or null; the minimum is tooSmall's.
    function aspectCrop(x0: real, y0: real, x1: real, y1: real): var {
        const w = picture.paintedWidth;
        const h = picture.paintedHeight;
        if (cropRatio.length !== 2 || w <= 0 || h <= 0 || sourceWidth <= 0 || sourceHeight <= 0 ||
                ![x0, y0, x1, y1].every(isFinite))
            return null;
        const rw = cropRatio[0], rh = cropRatio[1];
        const left = (picture.width - w) / 2;
        const top = (picture.height - h) / 2;
        const a = picture.mapFromItem(canvas, x0, y0);
        const b = picture.mapFromItem(canvas, x1, y1);
        const across = (v, origin, painted, source) =>
            Math.round((Math.min(Math.max(v, origin), origin + painted) - origin) * source / painted * 1e6) / 1e6;
        const halfUp = (n, d) => Math.floor((2 * n + d) / (2 * d));
        const axis = (anchor, pointer, source) => {
            const sign = pointer >= anchor ? 1 : -1;
            const start = sign > 0 ? Math.floor(anchor) : Math.ceil(anchor);
            return { sign: sign, start: start,
                     extent: pointer === anchor ? 0 : Math.ceil(Math.round(Math.abs(pointer - start) * 1e6) / 1e6),
                     room: sign > 0 ? source - start : start };
        };
        const ax = axis(across(a.x, left, w, sourceWidth), across(b.x, left, w, sourceWidth), sourceWidth);
        const ay = axis(across(a.y, top, h, sourceHeight), across(b.y, top, h, sourceHeight), sourceHeight);
        const reach = (limit, a, b) => Math.floor(((2 * limit + 1) * a - 1) / (2 * b));
        const shapeIn = (width, height) => {
            const wa = Math.min(width, reach(height, rw, rh));
            const hb = Math.min(height, reach(width, rh, rw));
            const found = [[wa, halfUp(wa * rh, rw)], [halfUp(hb * rw, rh), hb]].filter(c => c[0] >= 1 && c[1] >= 1);
            if (found.length === 0) return [0, 0];
            const last = found[found.length - 1];
            return last[0] * last[1] > found[0][0] * found[0][1] ? last : found[0];
        };
        // The least width whose rounded height reaches the drag's height (none when it has none).
        const covering = ay.extent === 0 ? 0 : Math.ceil((2 * ay.extent - 1) * rw / (2 * rh));
        const want = Math.max(ax.extent, covering);
        const [bw, bh] = want <= Math.min(ax.room, reach(ay.room, rw, rh))
            ? [want, halfUp(want * rh, rw)]
            : shapeIn(ax.room, ay.room);
        if (!(bw >= 1 && bh >= 1)) return null;
        const bl = ax.sign > 0 ? ax.start : ax.start - bw;
        const bt = ay.sign > 0 ? ay.start : ay.start - bh;
        return [bl, bt, bl + bw, bt + bh];
    }

    // A real box that is under the minimum crop; sourceCrop's null (unusable canvas) is not this.
    function tooSmall(box: var): bool {
        return box[2] - box[0] < Math.max(1, minCropWidth) || box[3] - box[1] < Math.max(1, minCropHeight);
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

        Rectangle {
            objectName: "photoAspectBand"
            readonly property var box: pointer.cropping && canvas.cropRatio.length === 2
                ? canvas.aspectCrop(pointer.start.x, pointer.start.y, pointer.current.x, pointer.current.y) : null
            x: box ? (picture.width - picture.paintedWidth) / 2 + box[0] * picture.paintedWidth / canvas.sourceWidth : 0
            y: box ? (picture.height - picture.paintedHeight) / 2 + box[1] * picture.paintedHeight / canvas.sourceHeight : 0
            width: box ? (box[2] - box[0]) * picture.paintedWidth / canvas.sourceWidth : 0
            height: box ? (box[3] - box[1]) * picture.paintedHeight / canvas.sourceHeight : 0
            color: "transparent"
            border.width: 2 / canvas.viewZoom
            border.color: "#ffffff"
            visible: box !== null
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
                const box = canvas.cropRatio.length === 2
                    ? canvas.aspectCrop(start.x, start.y, mouse.x, mouse.y)
                    : canvas.sourceCrop(start.x, start.y, mouse.x, mouse.y);
                if (box === null) return;
                if (canvas.tooSmall(box)) canvas.cropRejected();
                else canvas.cropRequested(box[0], box[1], box[2], box[3]);
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
        visible: pointer.cropping && canvas.cropRatio.length !== 2
        color: "transparent"
        border.color: "white"
        border.width: 1
    }

    WheelHandler {
        onWheel: event => { canvas.zoom(event.angleDelta.y > 0 ? 1.25 : 0.8); event.accepted = true; }
    }
}
