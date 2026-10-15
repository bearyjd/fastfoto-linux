import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami

Kirigami.Page {
    id: page

    title: qsTr("Scan photos")
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

            QQC2.Button {
                objectName: "processKeptButton"
                visible: bridge.canProcessKept
                enabled: bridge.canProcessKept
                icon.name: "system-run"
                text: qsTr("Process them now")
                Accessible.name: qsTr("Process them now")
                onClicked: bridge.processKept()
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

            FormPanel {
                Layout.preferredWidth: Kirigami.Units.gridUnit * 28
                Layout.fillHeight: true
            }

            Kirigami.Separator {
                Layout.fillHeight: true
            }

            ResultsView {
                Layout.fillWidth: true
                Layout.fillHeight: true
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
                elide: Text.ElideRight
                maximumLineCount: 2
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
                enabled: bridge.canCancel
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
