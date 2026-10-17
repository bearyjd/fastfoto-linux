import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami

Kirigami.Page {
    id: page

    objectName: "scanPage"
    title: bridge.mode === "documents" ? qsTr("Scan documents") : qsTr("Scan photos")
    padding: Kirigami.Units.largeSpacing

    function messageType(kind) {
        switch (kind) {
        case "positive":
            return Kirigami.MessageType.Positive;
        case "warning":
            return Kirigami.MessageType.Warning;
        default:
            return Kirigami.MessageType.Information;
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: Kirigami.Units.largeSpacing

        ColumnLayout {
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing

            Kirigami.InlineMessage {
                objectName: "errorBanner"
                Layout.fillWidth: true
                type: Kirigami.MessageType.Error
                visible: bridge.bannerKind === "error"
                // InlineMessage has no textFormat: the bridge hands it escaped text.
                text: bridge.bannerKind === "error" ? bridge.bannerHtml : ""
            }

            Kirigami.InlineMessage {
                objectName: "keptBanner"
                Layout.fillWidth: true
                type: Kirigami.MessageType.Information
                visible: bridge.canProcessKept
                text: bridge.keptHtml
            }

            RowLayout {
                Layout.fillWidth: true
                visible: bridge.canProcessKept
                spacing: Kirigami.Units.largeSpacing

                // A button has no textFormat, so its text stays static; the folder, which the
                // user named, is a plain-text label beside it.
                QQC2.Button {
                    objectName: "processKeptButton"
                    enabled: bridge.canProcessKept
                    icon.name: "system-run"
                    text: bridge.processKeptText
                    Accessible.name: qsTr("Process them now")
                    Accessible.description: qsTr("into %1").arg(bridge.processKeptFolder)
                    onClicked: bridge.processKept()
                }

                QQC2.Label {
                    objectName: "processKeptFolder"
                    Layout.fillWidth: true
                    text: qsTr("into %1").arg(bridge.processKeptFolder)
                    textFormat: Text.PlainText
                    elide: Text.ElideMiddle
                    color: Kirigami.Theme.disabledTextColor
                }
            }

            Kirigami.InlineMessage {
                objectName: "resultBanner"
                Layout.fillWidth: true
                type: page.messageType(bridge.bannerKind)
                visible: bridge.bannerText !== "" && bridge.bannerKind !== "error" && !bridge.canProcessKept
                text: visible ? bridge.bannerHtml : ""
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: Kirigami.Units.largeSpacing

            ColumnLayout {
                Layout.preferredWidth: Kirigami.Units.gridUnit * 28
                Layout.fillHeight: true
                spacing: Kirigami.Units.smallSpacing

                ModeSwitch {
                    Layout.fillWidth: true
                }

                FormPanel {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    visible: bridge.mode === "photos"
                }

                DocumentFormPanel {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    visible: bridge.mode === "documents"
                }

                // How the scanner itself says to load it (the label on the feeder).
                QQC2.Label {
                    objectName: "photosLoadHint"
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    visible: bridge.mode === "photos"
                    text: qsTr("Load photos face up, top edge first")
                    textFormat: Text.PlainText
                    wrapMode: Text.WordWrap
                    color: Kirigami.Theme.disabledTextColor
                    font: Kirigami.Theme.smallFont
                }

                QQC2.Label {
                    objectName: "documentsLoadHint"
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    visible: bridge.mode === "documents"
                    text: qsTr("Load pages face down, top edge first")
                    textFormat: Text.PlainText
                    wrapMode: Text.WordWrap
                    color: Kirigami.Theme.disabledTextColor
                    font: Kirigami.Theme.smallFont
                }
            }

            Kirigami.Separator {
                Layout.fillHeight: true
            }

            ResultsView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                visible: bridge.mode === "photos"
            }

            DocumentsView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                visible: bridge.mode === "documents"
            }
        }

        Kirigami.Separator {
            Layout.fillWidth: true
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Kirigami.Units.largeSpacing

            Kirigami.Chip {
                objectName: "scannerChip"
                text: bridge.state === "checking" ? qsTr("Looking for the scanner…") : (bridge.scannerOk ? qsTr("Scanner found") : qsTr("No scanner"))
                icon.name: bridge.scannerOk ? "emblem-ok-symbolic" : "dialog-warning-symbolic"
                closable: false
                checkable: false
                enabled: true
            }

            QQC2.Button {
                objectName: "checkAgainButton"
                text: qsTr("Check again")
                icon.name: "view-refresh"
                enabled: bridge.canCheck
                Accessible.name: qsTr("Check again")
                onClicked: bridge.checkScanner()
            }

            QQC2.Label {
                objectName: "scannerDetail"
                Layout.fillWidth: true
                visible: !bridge.scannerOk && bridge.state !== "checking" && bridge.state !== "idle"
                text: bridge.scannerText
                textFormat: Text.PlainText
                wrapMode: Text.WordWrap
                maximumLineCount: 8 // the end of a message says what to do: never cut it
                color: Kirigami.Theme.disabledTextColor
            }

            QQC2.Label {
                objectName: "progressLabel"
                Layout.fillWidth: !(!bridge.scannerOk && bridge.state !== "checking" && bridge.state !== "idle")
                visible: bridge.progressText !== ""
                text: bridge.progressText
                textFormat: Text.PlainText
                horizontalAlignment: Text.AlignRight
            }

            QQC2.BusyIndicator {
                running: bridge.busy
                visible: bridge.busy
                implicitHeight: Kirigami.Units.iconSizes.medium
                implicitWidth: Kirigami.Units.iconSizes.medium
            }

            QQC2.Label {
                objectName: "scanBlocker"
                Layout.fillWidth: true
                visible: text !== ""
                text: bridge.whyNotScan
                textFormat: Text.PlainText
                wrapMode: Text.WordWrap
                maximumLineCount: 2
                elide: Text.ElideRight
                horizontalAlignment: Text.AlignRight
                color: Kirigami.Theme.disabledTextColor
            }

            QQC2.Button {
                objectName: "cancelButton"
                text: qsTr("Cancel")
                icon.name: "dialog-cancel"
                enabled: bridge.canCancel || bridge.startingScan
                Accessible.name: qsTr("Cancel")
                onClicked: bridge.cancel()
            }

            QQC2.Button {
                objectName: "scanButton"
                text: qsTr("Scan")
                icon.name: "scanner"
                highlighted: true
                enabled: bridge.canScan
                Accessible.name: qsTr("Scan")
                onClicked: bridge.startScan()
            }
        }
    }
}
