import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami

Kirigami.ScrollablePage {
    id: page
    objectName: "scannerSettingsPage"
    title: qsTr("Scanner settings")
    signal closeRequested()

    ColumnLayout {
        spacing: Kirigami.Units.largeSpacing
        width: page.availableWidth

        Kirigami.Heading {
            text: qsTr("USB power settings")
            level: 2
        }
        QQC2.Label {
            text: bridge.power.targetLabel
            textFormat: Text.PlainText
        }
        QQC2.Label {
            Layout.fillWidth: true
            text: qsTr("Sleep saves power while keeping the scanner ready to wake. Power off shuts it down. These settings are available over USB.")
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
        }
        QQC2.Label {
            objectName: "powerMessage"
            Layout.fillWidth: true
            text: bridge.power.message
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            color: bridge.power.reconnectRequired ? Kirigami.Theme.negativeTextColor : Kirigami.Theme.textColor
            Accessible.role: Accessible.StaticText
        }
        RowLayout {
            QQC2.Button {
                objectName: "powerReadButton"
                text: bridge.power.loaded ? qsTr("Refresh") : qsTr("Read settings")
                icon.name: "view-refresh"
                enabled: bridge.power.canRead
                Accessible.name: text
                onClicked: bridge.power.read()
            }
            QQC2.BusyIndicator {
                running: bridge.power.busy
                visible: running
            }
        }
        QQC2.Button {
            objectName: "powerReconnectButton"
            text: qsTr("Check USB reconnection")
            visible: bridge.power.reconnectRequired
            enabled: bridge.power.canCheckConnection
            Accessible.name: qsTr("Check USB reconnection")
            onClicked: bridge.power.checkConnection()
        }
        Kirigami.FormLayout {
            Layout.fillWidth: true
            ColumnLayout {
                Kirigami.FormData.label: qsTr("Sleep delay:")
                QQC2.Label {
                    text: qsTr("Current on scanner")
                    color: Kirigami.Theme.disabledTextColor
                    textFormat: Text.PlainText
                }
                QQC2.Label {
                    objectName: "sleepCurrent"
                    text: bridge.power.sleepCurrent
                    textFormat: Text.PlainText
                }
                QQC2.ComboBox {
                    objectName: "sleepDraftBox"
                    model: bridge.power.sleepChoices
                    textRole: "label"
                    valueRole: "value"
                    currentIndex: indexOfValue(bridge.power.sleepDraft)
                    enabled: bridge.power.canRead && count > 0
                    Accessible.name: qsTr("Sleep delay draft")
                    onActivated: bridge.power.setValue("sleep_minutes", currentValue)
                }
            }
            ColumnLayout {
                Kirigami.FormData.label: qsTr("Power off delay (AC):")
                QQC2.Label {
                    text: qsTr("Current on scanner")
                    color: Kirigami.Theme.disabledTextColor
                    textFormat: Text.PlainText
                }
                QQC2.Label {
                    objectName: "powerOffCurrent"
                    text: bridge.power.powerOffCurrent
                    textFormat: Text.PlainText
                }
                QQC2.ComboBox {
                    objectName: "powerOffDraftBox"
                    model: bridge.power.powerOffChoices
                    textRole: "label"
                    valueRole: "value"
                    currentIndex: indexOfValue(bridge.power.powerOffDraft)
                    enabled: bridge.power.canRead && count > 0
                    Accessible.name: qsTr("Power off delay draft")
                    onActivated: bridge.power.setValue("power_off_minutes", currentValue)
                }
            }
        }
        QQC2.Label {
            Layout.fillWidth: true
            text: qsTr("Draft values stay local until you choose Apply changes. Only edited timers are sent, then read back for verification.")
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
        }
        RowLayout {
            QQC2.Button {
                objectName: "powerApplyButton"
                text: qsTr("Apply changes")
                enabled: bridge.power.canApply
                Accessible.name: qsTr("Apply changes")
                onClicked: bridge.power.apply()
            }
            QQC2.Button {
                objectName: "powerBackButton"
                text: qsTr("Back to scan")
                Accessible.name: qsTr("Back to scan")
                onClicked: page.closeRequested()
            }
        }
        Item { Layout.fillHeight: true }
    }
}
