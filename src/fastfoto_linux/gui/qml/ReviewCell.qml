import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami

Item {
    id: cell
    required property var model
    property string outputText: ""
    required property int index
    required property int orderIndex
    property int previousOrderIndex: -1
    property int nextOrderIndex: -1
    required property int number
    required property string thumbUrl
    required property bool included
    required property int turns
    required property var flags
    required property string flagText
    required property var marks
    required property bool startsPart
    required property int part
    required property bool dropped
    property bool selected: false
    signal activated()
    signal previewRequested()
    Accessible.name: qsTr("Page %1, %2").arg(number).arg(included ? qsTr("kept") : qsTr("removed"))
    Accessible.role: Accessible.ListItem

    Rectangle {
        anchors.fill: parent
        anchors.margins: 4
        color: cell.selected ? Kirigami.Theme.alternateBackgroundColor : Kirigami.Theme.backgroundColor
        border.color: cell.selected ? Kirigami.Theme.highlightColor : Kirigami.Theme.disabledTextColor
        border.width: cell.selected ? 2 : 1
        radius: 4
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 12
        spacing: Kirigami.Units.smallSpacing
        QQC2.Label {
            Layout.fillWidth: true
            text: cell.startsPart ? qsTr("Page %1 · New PDF %2").arg(cell.number).arg(cell.part) : qsTr("Page %1").arg(cell.number)
            textFormat: Text.PlainText
            font.bold: cell.startsPart
        }
        QQC2.Label {
            text: qsTr("Source preview")
            textFormat: Text.PlainText
            font: Kirigami.Theme.smallFont
            color: Kirigami.Theme.disabledTextColor
        }
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            opacity: cell.included ? 1 : 0.4
            Item {
                id: rotated
                anchors.centerIn: parent
                width: cell.turns % 2 ? parent.height : parent.width
                height: cell.turns % 2 ? parent.width : parent.height
                rotation: cell.turns * 90
                Image {
                    id: thumbnail
                    anchors.fill: parent
                    source: cell.thumbUrl
                    sourceSize.width: 240
                    sourceSize.height: 240
                    asynchronous: true
                    cache: false
                    fillMode: Image.PreserveAspectFit
                }
                Item {
                    anchors.centerIn: parent
                    width: thumbnail.paintedWidth
                    height: thumbnail.paintedHeight
                    Repeater {
                        model: cell.marks
                        Rectangle {
                            required property var modelData
                            x: modelData.x0 * parent.width
                            y: modelData.y0 * parent.height
                            width: (modelData.x1 - modelData.x0) * parent.width
                            height: (modelData.y1 - modelData.y0) * parent.height
                            color: "transparent"
                            border.color: Kirigami.Theme.negativeTextColor
                            border.width: 1
                        }
                    }
                }
            }
            MouseArea {
                anchors.fill: parent
                onClicked: cell.activated()
                onDoubleClicked: cell.previewRequested()
            }
        }
        QQC2.Label {
            Layout.fillWidth: true
            text: cell.included ? (cell.flags.length ? cell.flagText : qsTr("Keep")) : (cell.dropped ? qsTr("Blank, click Keep to restore") : qsTr("Removed"))
            textFormat: Text.PlainText
            elide: Text.ElideRight
            color: cell.flags.length ? Kirigami.Theme.neutralTextColor : Kirigami.Theme.textColor
            QQC2.ToolTip.visible: flagHover.hovered && cell.flags.length > 0
            QQC2.ToolTip.text: cell.flagText
            HoverHandler { id: flagHover }
        }
        QQC2.Label {
            Layout.fillWidth: true
            visible: cell.outputText !== ""
            text: cell.outputText
            textFormat: Text.PlainText
            elide: Text.ElideRight
            font: Kirigami.Theme.smallFont
            QQC2.ToolTip.visible: outputHover.hovered
            QQC2.ToolTip.text: cell.outputText
            HoverHandler { id: outputHover }
        }
        RowLayout {
            spacing: 2
            QQC2.Button {
                objectName: "reviewKeepButton"
                text: cell.included ? qsTr("Remove") : qsTr("Keep")
                Accessible.name: cell.included ? qsTr("Remove") : qsTr("Keep")
                onClicked: { cell.activated(); bridge.review.toggle(cell.number); }
            }
            QQC2.ToolButton {
                objectName: "reviewRotateButton"
                text: qsTr("Rotate")
                Accessible.name: qsTr("Rotate")
                QQC2.ToolTip.text: qsTr("Rotate clockwise")
                QQC2.ToolTip.visible: hovered
                onClicked: { cell.activated(); bridge.review.rotate(cell.number, 1); }
            }
            QQC2.ToolButton {
                objectName: "reviewSplitButton"
                text: qsTr("Split")
                Accessible.name: qsTr("Split")
                QQC2.ToolTip.text: qsTr("Start new PDF")
                QQC2.ToolTip.visible: hovered
                onClicked: { cell.activated(); bridge.review.toggleSplit(cell.number); }
            }
            QQC2.ToolButton {
                objectName: "reviewPreviewButton"
                text: qsTr("Preview")
                Accessible.name: qsTr("Preview")
                onClicked: { cell.activated(); cell.previewRequested(); }
            }
        }
        RowLayout {
            QQC2.ToolButton {
                text: "←"
                Accessible.name: qsTr("Move earlier")
                enabled: cell.previousOrderIndex >= 0
                onClicked: { cell.activated(); bridge.review.move(cell.number, cell.previousOrderIndex); }
            }
            QQC2.ToolButton {
                text: "→"
                Accessible.name: qsTr("Move later")
                enabled: cell.nextOrderIndex >= 0
                onClicked: { cell.activated(); bridge.review.move(cell.number, cell.nextOrderIndex); }
            }
            QQC2.Label {
                text: qsTr("Drag to move")
                textFormat: Text.PlainText
                MouseArea {
                    id: dragHandle
                    objectName: "reviewDragHandle"
                    anchors.fill: parent
                    drag.target: dragToken
                    onPressed: mouse => {
                        cell.activated();
                        const point = mapToItem(cell, mouse.x, mouse.y);
                        dragToken.x = point.x - dragToken.width / 2;
                        dragToken.y = point.y - dragToken.height / 2;
                    }
                    onReleased: { dragToken.Drag.drop(); dragToken.x = 0; dragToken.y = 0; }
                }
            }
        }
    }
    Item {
        id: dragToken
        width: 32
        height: 32
        Drag.active: dragHandle.drag.active
        Drag.source: cell
        Drag.hotSpot.x: 16
        Drag.hotSpot.y: 16
    }
    DropArea {
        anchors.fill: parent
        onDropped: drop => {
            if (drop.source && drop.source !== cell) {
                bridge.review.move(drop.source.number, cell.orderIndex);
                drop.acceptProposedAction();
            }
        }
    }
}
