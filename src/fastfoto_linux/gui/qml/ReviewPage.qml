import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami

Kirigami.ScrollablePage {
    id: page
    objectName: "reviewPage"
    title: qsTr("Review documents")

    property int editingPart: 0
    property string editedName: ""
    property bool nameValid: true

    function commitName(number, name) {
        editingPart = 0;
        nameValid = bridge.review.setPartName(number, name);
        return nameValid;
    }

    function commitPendingName() {
        return editingPart ? commitName(editingPart, editedName) : nameValid;
    }

    function saveReview() {
        if (commitPendingName() && bridge.review.canSave) bridge.review.save();
    }

    function backReview() {
        if (commitPendingName()) bridge.review.back();
    }

    function showPreview(number) {
        bridge.review.preview(number);
        previewDialog.open();
    }

    header: QQC2.Pane {
        padding: Kirigami.Units.smallSpacing
        enabled: !bridge.busy
        contentItem: ColumnLayout {
        spacing: Kirigami.Units.smallSpacing

        Kirigami.InlineMessage {
            Layout.fillWidth: true
            visible: bridge.bannerKind === "error"
            type: Kirigami.MessageType.Error
            text: bridge.bannerHtml
        }

        RowLayout {
            Layout.fillWidth: true
            QQC2.Label {
                objectName: "reviewSummary"
                Layout.fillWidth: true
                text: bridge.review.summary
                textFormat: Text.PlainText
                wrapMode: Text.WordWrap
            }
            QQC2.CheckBox {
                objectName: "reviewFlaggedOnly"
                text: qsTr("Only pages to check")
                Accessible.name: qsTr("Only pages to check")
                checked: bridge.review.flaggedOnly
                onToggled: bridge.review.setFlaggedOnly(checked)
            }
        }

        Repeater {
            id: names
            objectName: "reviewPartNames"
            model: bridge.review.parts
            delegate: RowLayout {
                required property var modelData
                Layout.fillWidth: true
                QQC2.Label {
                    text: qsTr("PDF %1 · %2 pages").arg(modelData.number).arg(modelData.pages)
                    textFormat: Text.PlainText
                }
                QQC2.TextField {
                    objectName: "reviewPartName"
                    Layout.fillWidth: true
                    text: modelData.name
                    placeholderText: qsTr("Document name")
                    Accessible.name: qsTr("Document name")
                    onActiveFocusChanged: {
                        if (activeFocus) {
                            page.editingPart = modelData.number;
                            page.editedName = text;
                        }
                    }
                    onTextEdited: page.editedName = text
                    onEditingFinished: page.commitName(modelData.number, text)
                }
            }
        }
        }
    }

    GridView {
        id: grid
        objectName: "reviewGrid"
        enabled: !bridge.busy
        model: bridge.review.items
        cellWidth: Math.max(220, Math.floor(width / Math.max(1, Math.floor(width / 250))))
        cellHeight: 330
        clip: true
        currentIndex: 0
        activeFocusOnTab: true
        keyNavigationEnabled: true
        Accessible.name: qsTr("Document pages")
        Accessible.role: Accessible.List

        delegate: ReviewCell {
            width: grid.cellWidth
            height: grid.cellHeight
            selected: GridView.isCurrentItem
            previousOrderIndex: index > 0 ? (bridge.review.items.get(index - 1).orderIndex ?? -1) : -1
            nextOrderIndex: index + 1 < grid.count ? (bridge.review.items.get(index + 1).orderIndex ?? -1) : -1
            onActivated: {
                grid.currentIndex = index;
                grid.forceActiveFocus();
                bridge.review.focus(number);
            }
            onPreviewRequested: page.showPreview(number)
        }

        Keys.onPressed: event => {
            const row = bridge.review.items.get(currentIndex);
            if (!row || !row.number) return;
            const control = (event.modifiers & Qt.ControlModifier) !== 0;
            const shift = (event.modifiers & Qt.ShiftModifier) !== 0;
            if (event.key === Qt.Key_Delete || event.key === Qt.Key_Space) {
                bridge.review.toggle(row.number);
            } else if (event.key === Qt.Key_R && !control) {
                bridge.review.rotate(row.number, shift ? -1 : 1);
            } else if (event.key === Qt.Key_S && !control) {
                bridge.review.toggleSplit(row.number);
            } else if (control && (event.key === Qt.Key_Left || event.key === Qt.Key_Right)) {
                const target = Math.max(0, Math.min(count - 1, currentIndex + (event.key === Qt.Key_Left ? -1 : 1)));
                bridge.review.move(row.number, bridge.review.items.get(target).orderIndex);
            } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
                page.showPreview(row.number);
            } else {
                return;
            }
            event.accepted = true;
        }
        onCurrentIndexChanged: {
            const row = bridge.review.items.get(currentIndex);
            if (row && row.number) bridge.review.focus(row.number);
        }
    }

    footer: QQC2.Pane {
        padding: Kirigami.Units.smallSpacing
        contentItem: RowLayout {
        QQC2.Button {
            objectName: "reviewBackButton"
            text: qsTr("Back")
            Accessible.name: qsTr("Back")
            onClicked: page.backReview()
        }
        Item { Layout.fillWidth: true }
        QQC2.Button {
            objectName: "reviewSaveButton"
            text: qsTr("Save PDFs")
            Accessible.name: qsTr("Save PDFs")
            icon.name: "document-save"
            enabled: bridge.review.canSave && !bridge.busy
            onClicked: page.saveReview()
        }
        }
    }

    Shortcut {
        sequence: "Ctrl+S"
        enabled: bridge.review.active && bridge.review.canSave && !bridge.busy
        onActivated: page.saveReview()
    }
    Shortcut {
        sequence: "Escape"
        enabled: bridge.review.active && !previewDialog.visible
        onActivated: page.backReview()
    }
    PreviewDialog { id: previewDialog }
}
