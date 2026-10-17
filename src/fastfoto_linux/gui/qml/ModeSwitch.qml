import QtQuick
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami

// Photos | Documents, at the top of the form. The mode cannot change while a job runs.
QQC2.TabBar {
    id: modeSwitch

    objectName: "modeSwitch"
    currentIndex: bridge.mode === "documents" ? 1 : 0
    Accessible.name: qsTr("What to scan")

    QQC2.TabButton {
        objectName: "photosModeButton"
        text: qsTr("Photos")
        icon.name: "view-preview"
        enabled: !bridge.busy
        Accessible.name: qsTr("Photos")
        onClicked: bridge.setMode("photos")
    }

    QQC2.TabButton {
        objectName: "documentsModeButton"
        text: qsTr("Documents")
        icon.name: "x-office-document"
        enabled: !bridge.busy
        Accessible.name: qsTr("Documents")
        onClicked: bridge.setMode("documents")
    }
}
