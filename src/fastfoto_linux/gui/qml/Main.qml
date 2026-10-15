import QtQuick
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami

Kirigami.ApplicationWindow {
    id: root

    objectName: "mainWindow"
    title: qsTr("FastFoto Linux")
    width: Kirigami.Units.gridUnit * 64
    height: Kirigami.Units.gridUnit * 40
    minimumWidth: Kirigami.Units.gridUnit * 40
    minimumHeight: Kirigami.Units.gridUnit * 30
    visible: true

    pageStack.initialPage: ScanPage {}

    // A scan in progress is cancelled first (after asking); the window closes by itself once
    // it has stopped. Closing while it is already being cancelled just waits for that.
    onClosing: close => {
        if (bridge.running) {
            close.accepted = false;
            if (bridge.canCancel) {
                cancelDialog.open();
            } else {
                bridge.requestClose();
            }
        }
    }

    Connections {
        target: bridge

        function onCloseReady() {
            root.close();
        }
    }

    Kirigami.PromptDialog {
        id: cancelDialog

        objectName: "cancelDialog"
        title: qsTr("Cancel the scan?")
        subtitle: qsTr("A scan is running. The pages scanned so far are kept so you can process them later.")
        standardButtons: QQC2.Dialog.Yes | QQC2.Dialog.No
        onAccepted: bridge.requestClose()
    }
}
