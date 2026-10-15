"""Review round 2 (12): the disk is read off the GUI thread, and the page waits for the answer."""

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from fastfoto_linux.gui import controller as controller_module
from fastfoto_linux.gui.controller import CHECKING_DISK_TEXT, Controller, disk_key
from fastfoto_linux.gui.form import ScanForm, validate_filesystem
from fastfoto_linux.gui.state import ActionBlockedError, State
from tests.gui.helpers import FakeWorker


@dataclass
class ManualDisk:
    """A ``disk_check`` runner that only records: the test decides when the disk "answers"."""

    forms: list[ScanForm] = field(default_factory=list)

    def __call__(self, form: ScanForm) -> None:
        self.forms.append(form)

    def answer(
        self, controller: Controller, index: int = -1, errors: dict[str, str] | None = None
    ) -> None:
        form = self.forms[index]
        controller.on_disk(disk_key(form), validate_filesystem(form) if errors is None else errors)


class AsyncPage:
    """A controller with a fake worker and a runner whose answers the test delivers."""

    def __init__(self, form: ScanForm) -> None:
        self.disk = ManualDisk()
        self.worker = FakeWorker()
        self.controller = Controller(self.worker, form, disk_check=self.disk)

    def ready(self) -> Controller:
        """The scanner is found and the folder has been looked at (and is fine)."""
        self.controller.check_scanner()
        self.controller.on_scanner(None)
        self.controller.check_disk()
        self.disk.answer(self.controller)
        assert self.controller.can_scan
        return self.controller


@pytest.fixture
def page(out: Path) -> AsyncPage:
    return AsyncPage(ScanForm(output_folder=str(out)))


def test_a_controller_with_a_runner_does_not_read_the_disk_when_it_is_made(
    out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(form: ScanForm) -> dict[str, str]:
        raise AssertionError("the disk was read on the caller's thread")

    monkeypatch.setattr(controller_module, "validate_filesystem", refuse)
    controller = Controller(
        FakeWorker(), ScanForm(output_folder=str(out / "gone")), disk_check=ManualDisk()
    )
    assert controller.errors == {}


def test_check_disk_hands_the_form_to_the_runner_and_shows_the_answer_when_it_comes(
    out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(form: ScanForm) -> dict[str, str]:
        raise AssertionError("the disk was read on the caller's thread")

    monkeypatch.setattr(controller_module, "validate_filesystem", refuse)
    page = AsyncPage(ScanForm(output_folder=str(out / "gone")))
    controller = page.controller
    controller.check_disk()
    assert page.disk.forms == [controller.form]
    assert controller.errors == {}  # nothing is known yet
    assert controller.scan_blocker == CHECKING_DISK_TEXT
    page.disk.answer(controller)
    assert "does not exist" in controller.errors["output_folder"]
    assert controller.scan_blocker != CHECKING_DISK_TEXT


def test_scan_waits_while_the_folder_is_being_checked(page: AsyncPage) -> None:
    controller = page.ready()
    controller.check_disk()
    assert not controller.can_scan
    assert controller.scan_blocker == CHECKING_DISK_TEXT
    with pytest.raises(ActionBlockedError):
        controller.start_scan()
    page.disk.answer(controller)
    assert controller.can_scan


def test_a_late_answer_for_another_folder_is_ignored(page: AsyncPage, tmp_path: Path) -> None:
    controller = page.ready()
    old = disk_key(controller.form)
    controller.set_field("output_folder", str(tmp_path / "other"))
    controller.check_disk()
    controller.on_disk(old, {"output_folder": "an answer about the old folder"})
    assert controller.errors == {}
    assert controller.scan_blocker == CHECKING_DISK_TEXT  # still waiting for the right answer
    page.disk.answer(controller)
    assert "does not exist" in controller.errors["output_folder"]


def test_editing_the_folder_forgets_a_check_that_is_under_way(
    page: AsyncPage, tmp_path: Path
) -> None:
    controller = page.ready()
    controller.check_disk()
    controller.set_field("output_folder", str(tmp_path / "other"))
    page.disk.answer(controller, 0)  # the answer about what was typed before
    assert controller.errors == {}
    assert controller.scan_blocker != CHECKING_DISK_TEXT
    assert controller.can_scan  # the folder is looked at when the user leaves the field


def test_starting_a_scan_looks_at_the_folder_first_and_scans_when_it_is_fine(
    page: AsyncPage,
) -> None:
    controller = page.ready()
    controller.start_scan()
    assert page.worker.names == ["check"]  # no scan yet
    assert controller.state is State.READY
    assert controller.busy
    assert not controller.can_scan
    assert not controller.can_check
    assert controller.scan_blocker == CHECKING_DISK_TEXT
    page.disk.answer(controller)
    assert controller.state is State.SCANNING
    assert page.worker.calls[-1] == ("scan", controller.form)


def test_a_folder_that_went_bad_while_starting_is_a_message_and_no_scan(page: AsyncPage) -> None:
    controller = page.ready()
    controller.start_scan()
    page.disk.answer(controller, errors={"output_folder": "The folder /srv/demo is gone."})
    assert controller.state is State.READY
    assert not controller.busy
    assert controller.banner is not None
    assert "is gone" in controller.banner.text
    assert "scan" not in page.worker.names


def test_no_scan_starts_when_the_folder_is_edited_while_it_waits(
    page: AsyncPage, tmp_path: Path
) -> None:
    controller = page.ready()
    controller.start_scan()
    controller.set_field("output_folder", str(tmp_path / "other"))
    page.disk.answer(controller, 0)
    assert "scan" not in page.worker.names
    assert not controller.busy
    assert controller.state is State.READY


def test_nothing_else_starts_while_the_folder_check_of_a_scan_runs(page: AsyncPage) -> None:
    controller = page.ready()
    controller.start_scan()
    for action in (controller.start_scan, controller.check_scanner):
        with pytest.raises(ActionBlockedError):
            action()


def test_the_window_may_close_while_the_folder_is_being_checked(page: AsyncPage) -> None:
    controller = page.ready()
    controller.start_scan()
    assert controller.request_close() is True


def test_a_runner_that_cannot_start_leaves_nothing_waiting(out: Path) -> None:
    def broken(form: ScanForm) -> None:
        raise RuntimeError("no threads")

    controller = Controller(FakeWorker(), ScanForm(output_folder=str(out)), disk_check=broken)
    controller.check_scanner()
    controller.on_scanner(None)
    for action in (controller.check_disk, controller.start_scan):
        with pytest.raises(RuntimeError):
            action()
        assert not controller.busy
        assert controller.scan_blocker != CHECKING_DISK_TEXT


def test_a_scan_does_not_start_once_the_window_was_allowed_to_close(page: AsyncPage) -> None:
    controller = page.ready()
    controller.start_scan()
    assert controller.request_close() is True
    page.disk.answer(controller)  # the answer comes while the window is going away
    assert "scan" not in page.worker.names
    assert controller.state is State.READY


def test_a_folder_check_that_never_answers_can_be_given_up_with_cancel(page: AsyncPage) -> None:
    controller = page.ready()
    controller.start_scan()
    assert controller.starting_scan
    assert not controller.can_cancel  # that is for a running job
    controller.cancel()
    assert not controller.starting_scan
    assert not controller.busy
    assert controller.can_check
    assert not controller.can_cancel
    assert "cancel" not in page.worker.names  # no job was running: there is nothing to stop
    page.disk.answer(controller)  # an answer that comes after all changes nothing
    assert "scan" not in page.worker.names
    assert controller.state is State.READY
    controller.start_scan()  # and Scan can be pressed again
    page.disk.answer(controller)
    assert controller.state is State.SCANNING
