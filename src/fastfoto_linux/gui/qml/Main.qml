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
    property var reviewPage: null

    function syncReview() {
        if (bridge.review.active && reviewPage === null) {
            reviewPage = pageStack.push(reviewComponent);
        } else if (!bridge.review.active && reviewPage !== null) {
            pageStack.pop();
            reviewPage = null;
        }
    }

    Component.onCompleted: {
        bridge.review.enable();
        syncReview();
    }
    Component { id: reviewComponent; ReviewPage {} }
    Connections {
        target: bridge.review
        function onChanged() { root.syncReview(); }
    }

    // A scan in progress is cancelled first (after asking); the window closes by itself once
    // it has stopped. Closing while it is already being cancelled just waits for that.
    onClosing: close => {
        if (bridge.review.active && !bridge.running &&
                ((reviewPage !== null && !reviewPage.commitPendingName()) || !bridge.review.flush())) {
            close.accepted = false;
            return;
        }
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
        title: bridge.closeTitle
        subtitle: bridge.closeText
        standardButtons: QQC2.Dialog.Yes | QQC2.Dialog.No
        // The scan may have finished while the question was open: then there is nothing to
        // wait for and the window closes now (otherwise closeReady closes it).
        onAccepted: {
            if (bridge.requestClose()) {
                root.close();
            }
        }
    }
}
