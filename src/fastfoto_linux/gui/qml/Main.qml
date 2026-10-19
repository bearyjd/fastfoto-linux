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

    pageStack.initialPage: ScanPage { onSettingsRequested: root.openSettings() }
    property var settingsPage: null
    // Settings replaces the workspace visually; the scan form keeps its full layout underneath.
    pageStack.defaultColumnWidth: (settingsPage !== null || photoEditPage !== null) ? pageStack.width : Kirigami.Units.gridUnit * 20

    function openSettings() {
        if (settingsPage !== null) {
            if (pageStack.currentItem === settingsPage) return;
            settingsPage.destroy();
        }
        settingsPage = settingsComponent.createObject(root.pageStack);
        pageStack.push(settingsPage);
    }

    function closeSettings() {
        if (settingsPage === null) return;
        if (pageStack.currentItem === settingsPage) pageStack.pop();
        const previous = settingsPage;
        settingsPage = null;
        previous.destroy();
    }

    property var reviewPage: null
    property bool syncingReview: false

    function syncReview() {
        if (syncingReview) return;
        syncingReview = true;
        try {
            if (bridge.review.active && reviewPage === null) {
                closeSettings();
                reviewPage = reviewComponent.createObject(root.pageStack);
                pageStack.push(reviewPage);
            } else if (!bridge.review.active && reviewPage !== null) {
                closeSettings();
                const previous = reviewPage;
                pageStack.pop();
                reviewPage = null;
                previous.destroy();
            }
        } finally {
            syncingReview = false;
        }
    }

    property var photoEditPage: null
    property bool syncingPhotoEdit: false
    property bool photoClosingWindow: false

    function syncPhotoEdit() {
        if (syncingPhotoEdit) return;
        syncingPhotoEdit = true;
        try {
            if (bridge.photoEdit.active && photoEditPage === null) {
                closeSettings();
                photoEditPage = photoEditComponent.createObject(root.pageStack);
                pageStack.push(photoEditPage);
            } else if (!bridge.photoEdit.active && photoEditPage !== null) {
                closeSettings();
                const previous = photoEditPage;
                pageStack.pop();
                photoEditPage = null;
                previous.destroy();
            }
        } finally {
            syncingPhotoEdit = false;
        }
    }

    Component.onCompleted: {
        bridge.review.enable();
        syncReview();
        syncPhotoEdit();
    }
    Component { id: reviewComponent; ReviewPage {} }
    Component { id: photoEditComponent; PhotoEditPage {} }
    Component {
        id: settingsComponent
        ScannerSettingsPage {
            onCloseRequested: root.closeSettings()
        }
    }
    Connections {
        target: bridge.review
        function onChanged() { root.syncReview(); }
    }

    Connections {
        target: bridge.photoEdit
        function onChanged() { root.syncPhotoEdit(); }
        function onCloseConfirmationRequired() { photoDiscardDialog.open(); }
    }

    Kirigami.PromptDialog {
        id: photoDiscardDialog
        objectName: "photoDiscardDialog"
        title: qsTr("Discard unsaved photo edits?")
        subtitle: qsTr("Your original and saved copies are kept.")
        standardButtons: QQC2.Dialog.Yes | QQC2.Dialog.No
        onAccepted: {
            const closing = root.photoClosingWindow;
            root.photoClosingWindow = false;
            bridge.photoEdit.close(true);
            if (closing) root.close();
        }
        onRejected: root.photoClosingWindow = false
    }

    // A scan in progress is cancelled first (after asking); the window closes by itself once
    // it has stopped. Closing while it is already being cancelled just waits for that.
    onClosing: close => {
        if (bridge.photoEdit.active) {
            root.photoClosingWindow = true;
            if (!bridge.photoEdit.close()) {
                close.accepted = false;
                return;
            }
            root.photoClosingWindow = false;
        }
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
