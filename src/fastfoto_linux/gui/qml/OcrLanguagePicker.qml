import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami

ColumnLayout {
    id: picker
    objectName: "docLanguagePicker"
    property bool editable: !bridge.busy && !bridge.documents.languages.busy
    // Folded away by default; only a running check or download holds it open.
    property bool expanded: false
    readonly property bool open: expanded || bridge.documents.languages.busy

    function holdsFocus(item) {
        let focused = Window.window ? Window.window.activeFocusItem : null;
        while (focused) {
            if (focused === item) return true;
            focused = focused.parent;
        }
        return false;
    }

    onOpenChanged: {
        if (!open && (holdsFocus(languageSearch) || holdsFocus(languageScroll)))
            Qt.callLater(() => languageToggle.forceActiveFocus());
    }
    Layout.fillWidth: true
    Layout.preferredWidth: Kirigami.Units.gridUnit * 16
    Layout.minimumWidth: 0
    spacing: Kirigami.Units.smallSpacing

    RowLayout {
        Layout.fillWidth: true
        Layout.minimumWidth: 0

        QQC2.Label {
            objectName: "docLanguageSummary"
            Layout.fillWidth: true
            Layout.preferredWidth: Kirigami.Units.gridUnit * 16
            Layout.minimumWidth: 0
            text: bridge.documents.languages.summary
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
        }

        QQC2.ToolButton {
            id: languageToggle
            objectName: "docLanguageToggle"
            text: bridge.documents.languages.busy ? qsTr("Languages (working…)")
                  : (picker.open ? qsTr("Hide languages") : qsTr("Show languages"))
            icon.name: picker.open ? "arrow-up" : "arrow-down"
            display: QQC2.AbstractButton.IconOnly
            enabled: !bridge.documents.languages.busy
            Accessible.name: qsTr("Languages")
            Accessible.checkable: true
            Accessible.checked: picker.open
            QQC2.ToolTip.text: text
            QQC2.ToolTip.visible: hovered
            QQC2.ToolTip.delay: Kirigami.Units.toolTipDelay
            onClicked: picker.expanded = !picker.expanded
        }
    }

    QQC2.TextField {
        id: languageSearch
        objectName: "docLanguageSearch"
        Layout.fillWidth: true
        implicitWidth: Kirigami.Units.gridUnit * 16
        visible: picker.open
        placeholderText: qsTr("Find a language by name or code")
        Accessible.name: qsTr("Find a text language")
        enabled: picker.editable
        onTextEdited: bridge.documents.languages.setSearch(text)
    }

    QQC2.ScrollView {
        id: languageScroll
        objectName: "docLanguageScroll"
        visible: picker.open
        Layout.fillWidth: true
        Layout.minimumWidth: 0
        Layout.preferredHeight: Kirigami.Units.gridUnit * 11
        clip: true
        contentWidth: availableWidth

        ListView {
            id: languageList
            objectName: "docLanguageList"
            model: bridge.documents.languages.rows
            spacing: Kirigami.Units.smallSpacing

            delegate: ColumnLayout {
                required property var modelData
                width: languageList.width
                spacing: 0

                QQC2.CheckBox {
                    id: languageBox
                    objectName: "docLanguageBox_" + modelData.code
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    text: modelData.name + " (" + modelData.code + ")"
                    checked: modelData.selected
                    enabled: picker.editable
                    Accessible.name: text + ". " + modelData.status
                    onClicked: bridge.documents.languages.setSelected(modelData.code, checked)

                    contentItem: QQC2.Label {
                        leftPadding: languageBox.indicator.width + languageBox.spacing
                        text: languageBox.text
                        textFormat: Text.PlainText
                        wrapMode: Text.WordWrap
                        verticalAlignment: Text.AlignVCenter
                        opacity: languageBox.enabled ? 1 : 0.5
                    }
                }

                QQC2.Label {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    Layout.leftMargin: Kirigami.Units.gridUnit * 2
                    text: modelData.status
                    textFormat: Text.PlainText
                    wrapMode: Text.WordWrap
                    font: Kirigami.Theme.smallFont
                    color: Kirigami.Theme.disabledTextColor
                }
            }
        }
    }

    QQC2.Label {
        objectName: "docLanguageDownloadSummary"
        Layout.fillWidth: true
        Layout.preferredWidth: Kirigami.Units.gridUnit * 16
        Layout.minimumWidth: 0
        text: bridge.documents.languages.downloadText
        textFormat: Text.PlainText
        wrapMode: Text.WordWrap
        visible: text !== ""
        font: Kirigami.Theme.smallFont
    }

    RowLayout {
        Layout.fillWidth: true

        QQC2.Button {
            objectName: "docDownloadLanguagesButton"
            text: qsTr("Download selected languages")
            icon.name: "download"
            enabled: picker.editable && bridge.documents.languages.canDownload
            Accessible.name: qsTr("Download selected languages")
            onClicked: bridge.documents.languages.downloadSelected()
        }

        QQC2.Button {
            objectName: "docRefreshLanguagesButton"
            text: qsTr("Check installed languages")
            icon.name: "view-refresh"
            enabled: picker.editable
            Accessible.name: qsTr("Check installed languages")
            onClicked: bridge.documents.languages.reload()
        }
    }

    QQC2.Label {
        objectName: "docLanguageProgress"
        Layout.fillWidth: true
        Layout.preferredWidth: Kirigami.Units.gridUnit * 16
        Layout.minimumWidth: 0
        text: bridge.documents.languages.progressText
        textFormat: Text.PlainText
        wrapMode: Text.WordWrap
        visible: text !== ""
    }

    RowLayout {
        visible: bridge.documents.languages.busy
        Layout.fillWidth: true

        QQC2.ProgressBar {
            objectName: "docLanguageProgressBar"
            Layout.fillWidth: true
            from: 0
            to: 1
            value: bridge.documents.languages.progress
            indeterminate: value === 0
        }

        QQC2.Button {
            objectName: "docCancelLanguageDownloadButton"
            text: qsTr("Cancel")
            Accessible.name: qsTr("Cancel")
            Accessible.description: qsTr("Cancel language download or check")
            onClicked: bridge.documents.languages.cancel()
        }
    }

    QQC2.Label {
        objectName: "docLanguageMessage"
        Layout.fillWidth: true
        Layout.preferredWidth: Kirigami.Units.gridUnit * 16
        Layout.minimumWidth: 0
        text: bridge.documents.languages.message
        textFormat: Text.PlainText
        wrapMode: Text.WordWrap
        visible: text !== ""
        color: Kirigami.Theme.negativeTextColor
    }

    QQC2.Label {
        objectName: "docLanguageScanHint"
        Layout.fillWidth: true
        Layout.preferredWidth: Kirigami.Units.gridUnit * 16
        Layout.minimumWidth: 0
        text: bridge.documents.languages.scanMessage
        textFormat: Text.PlainText
        wrapMode: Text.WordWrap
        visible: bridge.documents.searchableChecked && !bridge.documents.languages.ready
                 && !bridge.documents.languages.busy
        color: Kirigami.Theme.disabledTextColor
        font: Kirigami.Theme.smallFont
    }
}
