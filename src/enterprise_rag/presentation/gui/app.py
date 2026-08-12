from __future__ import annotations

import argparse
import importlib
import sys
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path, PurePosixPath
from typing import Any, cast

from enterprise_rag.application.dto.desktop_settings import DesktopSettingsDto
from enterprise_rag.application.dto.job_dashboard import CheckpointStatus, JobDashboardDto
from enterprise_rag.application.dto.job_result import (
    CompletionNotificationDto,
    CompletionNotificationState,
    DocumentJobResultDto,
    JobResultAvailability,
)
from enterprise_rag.application.dto.model_catalog import (
    ModelCatalogDto,
    ModelCatalogEntryDto,
    ModelCompatibility,
)
from enterprise_rag.application.dto.model_download import (
    ModelDownloadProgressDto,
    ModelDownloadState,
)
from enterprise_rag.application.dto.runner import RunnerHealth
from enterprise_rag.application.runtime import JobApplication
from enterprise_rag.domain.errors import ApplicationError, ErrorCategory
from enterprise_rag.domain.jobs import DocumentJobState
from enterprise_rag.presentation.gui.view_model import DesktopViewModel

_FIXED_POLICY_PREVIEW = """고정 정책(편집 불가)
• 원문과 모델 입력은 비신뢰 데이터로 취급
• 허용된 Evidence 밖의 사실 생성 금지
• 출처, 명령, 전제조건, 경고와 충돌 보존
• 파일·셸·도구 실행 및 임의 네트워크 접근 금지
• 최종 품질 게이트 우회 금지"""

_ERROR_GUIDANCE = {
    "INVALID_INPUT": (
        "작업 지시를 입력하고 결과 파일이 상대 경로의 .md 파일인지 확인하세요."
    ),
    "MODEL_NOT_CACHED": (
        "설정 탭에서 로컬 캐시 모델을 선택하거나 모델 다운로드를 완료하세요."
    ),
    "MODEL_SELECTION_INVALID": (
        "설정 탭에서 모델 ID와 40자리 commit을 다시 선택한 뒤 저장하세요."
    ),
    "MODEL_INCOMPATIBLE": (
        "설정 탭의 장비 적합성 결과가 지원됨인 다른 모델을 선택하세요."
    ),
    "DESKTOP_SETTINGS_INVALID": (
        "설정 탭의 작업 폴더와 모델 설정을 확인한 뒤 다시 저장하세요."
    ),
    "SETTINGS_REVISION_CONFLICT": (
        "설정 탭에서 다시 불러오기를 누른 뒤 변경사항을 다시 적용하세요."
    ),
    "CLAIM_LEDGER_INVALID": (
        "저장된 Evidence는 유지됩니다. 문제를 수정한 뒤 `실패 지점부터 복구`를 누르세요."
    ),
    "JOB_ALREADY_RUNNING": (
        "이미 실행 중인 Worker가 있습니다. 실행 탭에서 현재 단계와 heartbeat를 확인하세요."
    ),
    "JOB_NOT_RUNNABLE": (
        "현재 Job 상태를 새로고침하세요. 실패한 Job은 `실패 지점부터 복구`로 "
        "다시 시작할 수 있습니다."
    ),
    "JOB_STATE_CONFLICT": (
        "다른 Worker가 상태를 변경했습니다. 상태를 새로고침한 뒤 표시된 동작만 실행하세요."
    ),
    "JOB_LAUNCH_FAILED": (
        "Worker를 시작하지 못했습니다. 프로그램을 다시 시작한 뒤 실패 Job을 복구하세요."
    ),
    "INPUT_HASH_CHANGED": (
        "Job 생성 후 원본이 변경됐습니다. 변경을 완료한 뒤 새 작업을 생성하세요."
    ),
    "MODEL_CATALOG_UNAVAILABLE": (
        "네트워크 연결을 확인하거나 오프라인 모드에서 로컬 캐시 모델을 선택하세요."
    ),
    "MODEL_SNAPSHOT_INVALID": (
        "설정 탭에서 해당 모델을 다시 다운로드하고 검증을 완료하세요."
    ),
    "MODEL_GENERATION_FAILED": (
        "Worker 상태와 메모리 여유를 확인한 뒤 실패 지점부터 복구하세요."
    ),
    "MODEL_OUTPUT_INCOMPLETE": (
        "출력 토큰 한도를 확인한 뒤 실패 지점부터 복구하세요."
    ),
    "TOKEN_BUDGET_EXCEEDED": (
        "단계별 입력 분할 한도를 초과했습니다. 업데이트된 파이프라인으로 실패 지점부터 "
        "복구하세요. 반복되면 설정 탭에서 context를 늘리거나 추가 시스템 지침을 줄이세요."
    ),
    "TASK_PLAN_INVALID": (
        "저장된 Evidence와 Claim은 유지됩니다. 실패 지점부터 복구해 계획을 다시 생성하세요."
    ),
    "TASK_OUTPUT_INVALID": (
        "해당 Task 출력이 자동 교정 한도를 넘었습니다. 실패 지점부터 복구하세요."
    ),
    "IO_FAILURE": (
        "작업 폴더의 쓰기 권한과 디스크 여유 공간을 확인한 뒤 다시 시도하세요."
    ),
}

_CATEGORY_GUIDANCE = {
    ErrorCategory.TRANSIENT_SOURCE: "원본 파일 변경을 마친 뒤 새 작업을 생성하세요.",
    ErrorCategory.TRANSIENT_NETWORK: "네트워크 연결을 확인한 뒤 요청을 다시 실행하세요.",
    ErrorCategory.RESOURCE_PRESSURE: "디스크와 메모리 여유 공간을 확보한 뒤 다시 시도하세요.",
    ErrorCategory.INVALID_INPUT: "오류와 관련된 입력 항목을 수정한 뒤 다시 시도하세요.",
    ErrorCategory.UNSUPPORTED_FORMAT: "지원되는 UTF-8 텍스트 형식으로 변환한 뒤 다시 시도하세요.",
    ErrorCategory.DATA_CORRUPTION: "손상된 체크포인트나 모델을 다시 생성·다운로드하세요.",
    ErrorCategory.SECURITY_BLOCK: "허용된 작업 폴더와 링크·권한 정책을 확인하세요.",
    ErrorCategory.MODEL_OUTPUT: "출력 한도와 Worker 상태를 확인한 뒤 실패 지점부터 복구하세요.",
    ErrorCategory.CONSISTENCY: "상태를 새로고침하고 저장된 체크포인트부터 복구하세요.",
    ErrorCategory.CANCELLED: "취소가 완료됐습니다. 필요하면 새 작업을 생성하세요.",
    ErrorCategory.INTERNAL: "프로그램을 다시 시작하고 작업 폴더 권한을 확인하세요.",
}

_FEEDBACK_COLORS = {
    "info": ("#EEF3FF", "#2949B6", "#D9E2FF"),
    "success": ("#EAF8F0", "#137A46", "#CDEEDB"),
    "danger": ("#FFF1F2", "#A8202A", "#F5CED1"),
}


def _job_form_error(
    instruction: str,
    output_relative_path: str,
) -> tuple[str, str, str] | None:
    if not instruction.strip():
        return (
            "작업 지시를 입력하세요.",
            "생성할 문서의 목적과 반드시 포함할 내용을 한 문장 이상 작성하세요.",
            "instruction",
        )
    if len(instruction) > 20_000:
        return (
            "작업 지시가 너무 깁니다.",
            "작업 지시는 20,000자 이하로 줄여 주세요.",
            "instruction",
        )
    output = PurePosixPath(output_relative_path)
    if (
        not output_relative_path
        or output.is_absolute()
        or any(part in {"", ".", ".."} for part in output.parts)
        or output.suffix.lower() != ".md"
    ):
        return (
            "결과 파일 이름이 올바르지 않습니다.",
            "절대 경로나 상위 경로(..) 없이 .md 확장자의 상대 경로를 입력하세요.",
            "output",
        )
    return None


def _error_notice(error: Exception) -> tuple[str, str, str]:
    if isinstance(error, ApplicationError):
        guidance = _ERROR_GUIDANCE.get(
            error.code,
            _CATEGORY_GUIDANCE[error.category],
        )
        return error.safe_message, guidance, error.code
    if isinstance(error, ValueError):
        return (
            str(error) or "입력값을 확인할 수 없습니다.",
            "표시된 입력과 설정을 확인한 뒤 다시 시도하세요.",
            "LOCAL_VALIDATION",
        )
    return (
        "처리되지 않은 내부 오류가 발생했습니다.",
        "작업 상태를 새로고침한 뒤 다시 시도하세요.",
        "UNEXPECTED_ERROR",
    )

_APP_STYLE = """
QMainWindow, QWidget#appShell, QWidget[role="page"] {
    background: #F4F7FB;
}
QWidget {
    color: #172033;
    font-size: 13px;
}
QFrame[role="topbar"] {
    background: #FFFFFF;
    border: 1px solid #E6EAF0;
    border-radius: 16px;
}
QFrame[role="card"], QFrame[role="actionBar"] {
    background: #FFFFFF;
    border: 1px solid #E3E8EF;
    border-radius: 14px;
}
QFrame[role="subtlePanel"] {
    background: #F8FAFC;
    border: 1px solid #E7ECF2;
    border-radius: 10px;
}
QLabel[role="brandMark"] {
    background: #3B5BDB;
    color: #FFFFFF;
    border-radius: 10px;
    font-size: 16px;
    font-weight: 700;
    qproperty-alignment: AlignCenter;
}
QLabel[role="brandTitle"] {
    color: #121A2A;
    font-size: 18px;
    font-weight: 700;
}
QLabel[role="eyebrow"] {
    color: #667085;
    font-size: 10px;
    font-weight: 700;
}
QLabel[role="pageTitle"] {
    color: #111827;
    font-size: 22px;
    font-weight: 700;
}
QLabel[role="sectionTitle"] {
    color: #162033;
    font-size: 15px;
    font-weight: 700;
}
QLabel[role="subtitle"], QLabel[role="muted"], QLabel[role="headerMeta"] {
    color: #667085;
}
QLabel[role="fieldLabel"] {
    color: #344054;
    font-size: 12px;
    font-weight: 600;
}
QLabel[role="metricLabel"] {
    color: #667085;
    font-size: 11px;
    font-weight: 600;
}
QLabel[role="metricValue"] {
    color: #202939;
    font-size: 13px;
}
QLabel[role="statusChip"] {
    border-radius: 11px;
    padding: 5px 10px;
    font-size: 11px;
    font-weight: 700;
}
QLabel[role="statusChip"][tone="neutral"] { background: #EEF2F6; color: #475467; }
QLabel[role="statusChip"][tone="info"] { background: #E9EFFF; color: #2949B6; }
QLabel[role="statusChip"][tone="success"] { background: #E7F8EF; color: #137A46; }
QLabel[role="statusChip"][tone="warning"] { background: #FFF3D8; color: #946200; }
QLabel[role="statusChip"][tone="danger"] { background: #FDEBEC; color: #B4232D; }
QLabel[role="callout"] {
    background: #F5F7FF;
    border: 1px solid #E0E6FF;
    border-radius: 9px;
    color: #354052;
    padding: 10px 12px;
}
QLabel[role="feedback"] {
    border-radius: 9px;
    padding: 10px 12px;
    font-weight: 600;
}
QLabel[role="feedback"][tone="info"] {
    background: #EEF3FF;
    border: 1px solid #D9E2FF;
    color: #2949B6;
}
QLabel[role="feedback"][tone="success"] {
    background: #EAF8F0;
    border: 1px solid #CDEEDB;
    color: #137A46;
}
QLabel[role="feedback"][tone="danger"] {
    background: #FFF1F2;
    border: 1px solid #F5CED1;
    color: #A8202A;
}
QLineEdit, QPlainTextEdit, QComboBox, QSpinBox {
    background: #FFFFFF;
    border: 1px solid #D7DEE8;
    border-radius: 8px;
    padding: 7px 9px;
    selection-background-color: #3B5BDB;
}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus {
    border: 1px solid #5C73E6;
}
QLineEdit:read-only, QPlainTextEdit:read-only {
    background: #F7F9FC;
    color: #586174;
}
QComboBox::drop-down {
    border: none;
    width: 28px;
}
QPushButton {
    min-height: 20px;
    border: 1px solid #D3DAE5;
    border-radius: 8px;
    background: #FFFFFF;
    color: #344054;
    padding: 7px 13px;
    font-weight: 600;
}
QPushButton:hover { background: #F7F9FC; border-color: #B9C3D2; }
QPushButton:pressed { background: #EEF2F6; }
QPushButton:disabled { background: #F5F7FA; color: #A7B0BF; border-color: #E5E9F0; }
QPushButton[role="primary"] { background: #3B5BDB; color: #FFFFFF; border-color: #3B5BDB; }
QPushButton[role="primary"]:hover { background: #304CC2; border-color: #304CC2; }
QPushButton[role="danger"] { background: #FFFFFF; color: #C4323B; border-color: #F0C5C8; }
QPushButton[role="danger"]:hover { background: #FFF5F5; border-color: #DF9DA2; }
QPushButton[role="ghost"] { background: transparent; border-color: transparent; color: #526071; }
QPushButton[role="ghost"]:hover { background: #EEF2F6; }
QPushButton[role="primary"]:disabled,
QPushButton[role="danger"]:disabled,
QPushButton[role="ghost"]:disabled {
    background: #F5F7FA;
    color: #A7B0BF;
    border-color: #E5E9F0;
}
QTabWidget, QTabBar { background: #F4F7FB; color: #344054; }
QTabWidget::pane { border: none; background: #F4F7FB; top: -1px; }
QTabWidget#mainTabs, QTabWidget#mainTabs::pane,
QTabBar#mainTabBar {
    background: #F4F7FB;
    border: none;
}
QTabWidget#detailTabs, QTabWidget#detailTabs::pane,
QTabBar#detailTabBar {
    background: #FFFFFF;
    border: none;
}
QTabBar::tab {
    background: transparent;
    color: #667085;
    border: none;
    padding: 10px 18px;
    margin-right: 4px;
    font-weight: 600;
}
QTabBar::tab:selected {
    background: #FFFFFF;
    color: #304CC2;
    border: 1px solid #DFE5ED;
    border-radius: 9px;
}
QTabBar::tab:hover:!selected { color: #344054; background: #EAEEF5; border-radius: 9px; }
QProgressBar {
    min-height: 9px;
    max-height: 9px;
    background: #E8EDF4;
    border: none;
    border-radius: 4px;
    text-align: center;
    color: transparent;
}
QProgressBar::chunk { background: #3B5BDB; border-radius: 4px; }
QTableWidget {
    background: #FFFFFF;
    alternate-background-color: #F8FAFC;
    border: 1px solid #E2E7EE;
    border-radius: 9px;
    gridline-color: #EEF1F5;
    selection-background-color: #E8EDFF;
    selection-color: #172033;
}
QHeaderView::section {
    background: #F6F8FB;
    color: #526071;
    border: none;
    border-bottom: 1px solid #E2E7EE;
    padding: 8px 9px;
    font-size: 11px;
    font-weight: 700;
}
QTableCornerButton::section { background: #F6F8FB; border: none; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { width: 9px; background: transparent; margin: 2px; }
QScrollBar::handle:vertical { background: #CAD2DE; border-radius: 4px; min-height: 32px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QCheckBox { spacing: 8px; color: #344054; }
QCheckBox::indicator { width: 16px; height: 16px; }
QSplitter::handle { background: #E8ECF2; width: 1px; height: 1px; }
QToolTip { background: #111827; color: #FFFFFF; border: none; padding: 6px; }
"""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rag-gui")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--environment", choices=("development", "test", "production"))
    return parser


class _DesktopWindow:
    def __init__(
        self,
        qt_core: Any,
        qt_gui: Any,
        qt_widgets: Any,
        view_model: DesktopViewModel,
    ) -> None:
        self._core = qt_core
        self._gui = qt_gui
        self._widgets = qt_widgets
        self._view_model = view_model
        self._settings: DesktopSettingsDto | None = None
        self._active_job_id: str | None = None
        self._active_download_id: str | None = None
        self._notification_requests: set[str] = set()
        self._result_paths: dict[str, str] = {}
        self._result_fields: dict[str, Any] = {}
        self._result_buttons: dict[str, Any] = {}
        self._closing = False
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="rag-gui-background",
        )
        self._futures: set[Future[Any]] = set()

        class BackgroundBridge(qt_core.QObject):  # type: ignore[misc]
            completed = qt_core.Signal(object)
            failed = qt_core.Signal(object)
            progress = qt_core.Signal(object)

        self._background_bridge = BackgroundBridge()
        self._background_bridge.completed.connect(self._background_completed)
        self._background_bridge.failed.connect(self._background_failed)
        self._background_bridge.progress.connect(self._render_download_progress)
        self.window = qt_widgets.QMainWindow()
        self.window.setWindowTitle("Local Document RAG")
        self.window.resize(1460, 940)
        self.window.setMinimumSize(1120, 720)
        self.window.setStyleSheet(_APP_STYLE)
        self._build()
        self._load_settings()
        self._reload_jobs()
        self._timer = qt_core.QTimer(self.window)
        self._timer.setInterval(2_000)
        self._timer.timeout.connect(self._refresh_dashboard)
        self._timer.start()

    @staticmethod
    def _set_role(widget: Any, role: str) -> Any:
        widget.setProperty("role", role)
        return widget

    def _set_tone(self, widget: Any, tone: str) -> None:
        widget.setProperty("tone", tone)
        style = widget.style()
        style.unpolish(widget)
        style.polish(widget)

    def _show_feedback(self, widget: Any, message: str, tone: str) -> None:
        background, foreground, border = _FEEDBACK_COLORS[tone]
        widget.setText(message)
        self._set_tone(widget, tone)
        widget.setStyleSheet(
            "QLabel {"
            f"background-color: {background}; color: {foreground}; "
            f"border: 1px solid {border}; border-radius: 9px; "
            "padding: 10px 12px; font-weight: 600;"
            "}"
        )
        palette = widget.palette()
        palette.setColor(self._gui.QPalette.ColorRole.Window, self._gui.QColor(background))
        palette.setColor(
            self._gui.QPalette.ColorRole.WindowText,
            self._gui.QColor(foreground),
        )
        palette.setColor(self._gui.QPalette.ColorRole.Text, self._gui.QColor(foreground))
        widget.setPalette(palette)
        widget.setAutoFillBackground(True)
        widget.setAttribute(self._core.Qt.WidgetAttribute.WA_StyledBackground, True)
        widget.setVisible(True)
        widget.updateGeometry()
        if widget is getattr(self, "_job_feedback", None):
            self._execution_top_splitter.setMinimumHeight(410)

    def _clear_feedback(self, widget: Any) -> None:
        widget.clear()
        widget.setVisible(False)
        if widget is getattr(self, "_job_feedback", None):
            self._execution_top_splitter.setMinimumHeight(318)

    def _style_tab_surface(self, tabs: Any, background: str, name: str) -> None:
        tabs.setObjectName(name)
        bar = tabs.tabBar()
        bar.setObjectName(f"{name.removesuffix('s')}Bar")
        color = self._gui.QColor(background)
        for widget in (tabs, bar):
            palette = widget.palette()
            palette.setColor(self._gui.QPalette.ColorRole.Window, color)
            palette.setColor(
                self._gui.QPalette.ColorRole.WindowText,
                self._gui.QColor("#344054"),
            )
            palette.setColor(self._gui.QPalette.ColorRole.Button, color)
            palette.setColor(
                self._gui.QPalette.ColorRole.ButtonText,
                self._gui.QColor("#344054"),
            )
            widget.setPalette(palette)
            widget.setAutoFillBackground(True)
            widget.setAttribute(
                self._core.Qt.WidgetAttribute.WA_StyledBackground,
                True,
            )
        tabs.setStyleSheet(
            f"QTabWidget {{ background: {background}; color: #344054; "
            "border: none; } "
            f"QTabWidget::pane {{ background: {background}; border: none; }} "
            f"QTabBar {{ background: {background}; color: #344054; border: none; }} "
            "QTabBar::tab { background: transparent; color: #667085; border: none; "
            "padding: 10px 18px; margin-right: 4px; font-weight: 600; } "
            "QTabBar::tab:selected { background: #FFFFFF; color: #304CC2; "
            "border: 1px solid #DFE5ED; border-radius: 9px; } "
            "QTabBar::tab:hover:!selected { color: #344054; background: #EAEEF5; "
            "border-radius: 9px; }"
        )

    def _label(self, text: str, role: str, word_wrap: bool = False) -> Any:
        label = self._widgets.QLabel(text)
        self._set_role(label, role)
        label.setWordWrap(word_wrap)
        return label

    def _button(self, text: str, role: str = "secondary") -> Any:
        button = self._widgets.QPushButton(text)
        self._set_role(button, role)
        button.setCursor(self._core.Qt.CursorShape.PointingHandCursor)
        return button

    def _card(
        self,
        title: str,
        description: str | None = None,
    ) -> tuple[Any, Any]:
        card = self._widgets.QFrame()
        self._set_role(card, "card")
        layout = self._widgets.QVBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 20)
        layout.setSpacing(13)
        layout.addWidget(self._label(title, "sectionTitle"))
        if description:
            layout.addWidget(self._label(description, "subtitle", True))
        return card, layout

    def _page_intro(self, title: str, description: str) -> Any:
        container = self._widgets.QWidget()
        row = self._widgets.QHBoxLayout(container)
        row.setContentsMargins(2, 0, 2, 0)
        text = self._widgets.QVBoxLayout()
        text.setSpacing(3)
        text.addWidget(self._label(title, "pageTitle"))
        text.addWidget(self._label(description, "subtitle"))
        row.addLayout(text)
        row.addStretch(1)
        return container

    def _prepare_table(self, table: Any) -> None:
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.setShowGrid(False)
        table.setSelectionBehavior(
            self._widgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        table.setEditTriggers(
            self._widgets.QAbstractItemView.EditTrigger.NoEditTriggers
        )
        table.setFocusPolicy(self._core.Qt.FocusPolicy.NoFocus)

    def _build(self) -> None:
        central = self._widgets.QWidget()
        central.setObjectName("appShell")
        root = self._widgets.QVBoxLayout(central)
        root.setContentsMargins(22, 18, 22, 20)
        root.setSpacing(14)

        topbar = self._widgets.QFrame()
        self._set_role(topbar, "topbar")
        header = self._widgets.QHBoxLayout(topbar)
        header.setContentsMargins(18, 13, 18, 13)
        header.setSpacing(12)
        mark = self._label("R", "brandMark")
        mark.setFixedSize(38, 38)
        brand = self._widgets.QVBoxLayout()
        brand.setSpacing(0)
        brand.addWidget(self._label("DOCUMENT WORKSPACE", "eyebrow"))
        brand.addWidget(self._label("Local Document RAG", "brandTitle"))
        self._header_job = self._widgets.QLabel("활성 Job: 없음")
        self._set_role(self._header_job, "headerMeta")
        self._header_state = self._widgets.QLabel("상태: 대기")
        self._set_role(self._header_state, "statusChip")
        self._set_tone(self._header_state, "neutral")
        header.addWidget(mark)
        header.addLayout(brand)
        header.addStretch(1)
        header.addWidget(self._header_job)
        header.addSpacing(8)
        header.addWidget(self._header_state)
        root.addWidget(topbar)

        self._app_feedback = self._label("", "feedback", True)
        self._app_feedback.setAccessibleName("애플리케이션 오류 안내")
        self._app_feedback.setTextInteractionFlags(
            self._core.Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._app_feedback.setMinimumHeight(48)
        self._app_feedback.hide()
        root.addWidget(self._app_feedback)

        self._main_tabs = self._widgets.QTabWidget()
        self._style_tab_surface(self._main_tabs, "#F4F7FB", "mainTabs")
        self._main_tabs.setDocumentMode(True)
        self._main_tabs.addTab(self._execution_tab(), "실행")
        self._main_tabs.addTab(self._settings_tab(), "설정")
        root.addWidget(self._main_tabs, 1)
        self.window.setCentralWidget(central)

    def _settings_tab(self) -> Any:
        page = self._widgets.QWidget()
        page.setProperty("role", "page")
        page_layout = self._widgets.QVBoxLayout(page)
        page_layout.setContentsMargins(0, 8, 0, 0)
        scroll = self._widgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(
            self._core.Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        canvas = self._widgets.QWidget()
        canvas.setProperty("role", "page")
        canvas_layout = self._widgets.QHBoxLayout(canvas)
        canvas_layout.setContentsMargins(2, 0, 2, 10)
        content = self._widgets.QWidget()
        content.setMaximumWidth(1280)
        layout = self._widgets.QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addWidget(
            self._page_intro(
                "환경 설정",
                "작업공간과 모델 정책을 관리합니다. 저장된 변경은 다음 Job부터 적용됩니다.",
            )
        )

        top_grid = self._widgets.QGridLayout()
        top_grid.setContentsMargins(0, 0, 0, 0)
        top_grid.setHorizontalSpacing(14)
        workspace, workspace_layout = self._card(
            "문서 작업공간",
            "원본과 결과 폴더는 서로 겹치지 않아야 합니다.",
        )
        workspace_form = self._widgets.QFormLayout()
        workspace_form.setContentsMargins(0, 2, 0, 0)
        workspace_form.setHorizontalSpacing(14)
        workspace_form.setVerticalSpacing(10)
        workspace_form.setLabelAlignment(
            self._core.Qt.AlignmentFlag.AlignLeft
            | self._core.Qt.AlignmentFlag.AlignVCenter
        )
        self._source_root = self._widgets.QLineEdit()
        workspace_form.addRow(
            self._label("원본 문서", "fieldLabel"),
            self._folder_row(self._source_root),
        )
        self._output_root = self._widgets.QLineEdit()
        workspace_form.addRow(
            self._label("결과 저장", "fieldLabel"),
            self._folder_row(self._output_root),
        )
        checkpoint_root = self._widgets.QLineEdit(self._view_model.checkpoint_root)
        checkpoint_root.setReadOnly(True)
        workspace_form.addRow(
            self._label("체크포인트", "fieldLabel"),
            checkpoint_root,
        )
        workspace_layout.addLayout(workspace_form)
        top_grid.addWidget(workspace, 0, 0)

        policy, policy_layout = self._card(
            "실행 정책",
            "재시도와 네트워크 사용 범위를 제한합니다.",
        )
        attempts_row = self._widgets.QHBoxLayout()
        attempts_row.addWidget(self._label("Task 최대 시도", "fieldLabel"))
        attempts_row.addStretch(1)
        self._max_attempts = self._widgets.QSpinBox()
        self._max_attempts.setRange(1, 3)
        self._max_attempts.setFixedWidth(84)
        attempts_row.addWidget(self._max_attempts)
        policy_layout.addLayout(attempts_row)
        self._offline_mode = self._widgets.QCheckBox(
            "로컬 캐시만 사용하고 다운로드 차단"
        )
        self._offline_mode.toggled.connect(self._offline_mode_changed)
        self._notify = self._widgets.QCheckBox("게시 완료 시 시스템 알림")
        policy_layout.addWidget(self._offline_mode)
        policy_layout.addWidget(self._notify)
        policy_layout.addStretch(1)
        top_grid.addWidget(policy, 0, 1)
        top_grid.setColumnStretch(0, 2)
        top_grid.setColumnStretch(1, 1)
        layout.addLayout(top_grid)

        model, model_layout = self._card(
            "로컬 LLM",
            "Hugging Face commit을 고정하고 장비 호환성과 로컬 캐시 상태를 확인합니다.",
        )
        model_fields = self._widgets.QGridLayout()
        model_fields.setHorizontalSpacing(12)
        model_fields.setVerticalSpacing(7)
        self._model_id = self._widgets.QLineEdit()
        self._model_revision = self._widgets.QLineEdit()
        self._model_revision.setPlaceholderText("40자리 Hugging Face commit SHA")
        self._context_tokens = self._widgets.QComboBox()
        self._context_tokens.setEditable(True)
        for value in (4_096, 16_384, 24_576, 32_768, 65_536, 131_072):
            self._context_tokens.addItem(f"{value:,}", value)
        self._max_output_tokens = self._widgets.QSpinBox()
        self._max_output_tokens.setRange(512, 131_072)
        self._max_output_tokens.setSingleStep(512)
        model_fields.addWidget(self._label("모델 ID", "fieldLabel"), 0, 0)
        model_fields.addWidget(self._label("고정 commit", "fieldLabel"), 0, 1)
        model_fields.addWidget(self._label("Context tokens", "fieldLabel"), 0, 2)
        model_fields.addWidget(self._label("최대 출력", "fieldLabel"), 0, 3)
        model_fields.addWidget(self._model_id, 1, 0)
        model_fields.addWidget(self._model_revision, 1, 1)
        model_fields.addWidget(self._context_tokens, 1, 2)
        model_fields.addWidget(self._max_output_tokens, 1, 3)
        model_fields.setColumnStretch(0, 3)
        model_fields.setColumnStretch(1, 3)
        model_fields.setColumnStretch(2, 1)
        model_fields.setColumnStretch(3, 1)
        model_layout.addLayout(model_fields)

        self._model_query = self._widgets.QLineEdit()
        self._model_query.setPlaceholderText("모델 검색 · 예: Qwen 27B 4bit")
        self._model_query.setAccessibleName("Hugging Face 모델 검색어")
        search_row = self._widgets.QWidget()
        search_layout = self._widgets.QHBoxLayout(search_row)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(8)
        search_layout.addWidget(self._model_query, 1)
        self._local_models_button = self._button("로컬 캐시", "secondary")
        self._local_models_button.clicked.connect(self._refresh_local_models)
        self._remote_models_button = self._button("최신 모델 검색", "secondary")
        self._remote_models_button.clicked.connect(self._search_remote_models)
        self._inspect_model_button = self._button("현재 선택 검증", "secondary")
        self._inspect_model_button.clicked.connect(self._inspect_current_model)
        search_layout.addWidget(self._local_models_button)
        search_layout.addWidget(self._remote_models_button)
        search_layout.addWidget(self._inspect_model_button)
        model_layout.addWidget(search_row)

        self._model_catalog = self._widgets.QTableWidget(0, 9)
        self._model_catalog.setAccessibleName("로컬 LLM 카탈로그")
        self._model_catalog.setAccessibleDescription(
            "모델 ID, 캐시 위치, 크기, 양자화, 장비 적합성과 고정 commit 목록"
        )
        self._model_catalog.setHorizontalHeaderLabels(
            (
                "모델 ID",
                "위치",
                "크기",
                "양자화",
                "Context",
                "장비 적합성",
                "Commit",
                "라이선스",
                "수정 시각",
            )
        )
        self._prepare_table(self._model_catalog)
        self._model_catalog.setSelectionMode(
            self._widgets.QAbstractItemView.SelectionMode.SingleSelection
        )
        self._model_catalog.itemDoubleClicked.connect(self._apply_selected_model)
        self._model_catalog.itemSelectionChanged.connect(
            self._model_catalog_selection_changed
        )
        self._model_catalog.setMinimumHeight(250)
        self._model_catalog.horizontalHeader().setStretchLastSection(False)
        self._model_catalog.horizontalHeader().setSectionResizeMode(
            0, self._widgets.QHeaderView.ResizeMode.Stretch
        )
        model_layout.addWidget(self._model_catalog)

        catalog_footer = self._widgets.QWidget()
        footer_layout = self._widgets.QHBoxLayout(catalog_footer)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.setSpacing(8)
        self._apply_model_button = self._button("선택 적용", "primary")
        self._apply_model_button.clicked.connect(self._apply_selected_model)
        self._download_model_button = self._button("모델 다운로드", "secondary")
        self._download_model_button.clicked.connect(self._download_selected_model)
        self._cancel_download_button = self._button("다운로드 취소", "danger")
        self._cancel_download_button.clicked.connect(self._cancel_model_download)
        self._cancel_download_button.setEnabled(False)
        self._model_catalog_status = self._widgets.QLabel(
            "로컬 캐시를 확인하는 중입니다."
        )
        self._set_role(self._model_catalog_status, "muted")
        self._model_catalog_status.setWordWrap(True)
        footer_layout.addWidget(self._apply_model_button)
        footer_layout.addWidget(self._download_model_button)
        footer_layout.addWidget(self._cancel_download_button)
        footer_layout.addWidget(self._model_catalog_status, 1)
        model_layout.addWidget(catalog_footer)

        self._download_progress = self._widgets.QProgressBar()
        self._download_progress.setRange(0, 100)
        self._download_progress.setValue(0)
        self._download_progress.setAccessibleName("모델 다운로드 진행률")
        self._download_detail = self._widgets.QLabel("다운로드 대기")
        self._set_role(self._download_detail, "muted")
        self._download_detail.setWordWrap(True)
        download_progress_row = self._widgets.QWidget()
        download_progress_layout = self._widgets.QVBoxLayout(download_progress_row)
        download_progress_layout.setContentsMargins(0, 0, 0, 0)
        download_progress_layout.setSpacing(6)
        download_progress_layout.addWidget(self._download_progress)
        download_progress_layout.addWidget(self._download_detail)
        model_layout.addWidget(download_progress_row)
        layout.addWidget(model)

        prompts, prompts_layout = self._card(
            "시스템 프롬프트",
            "고정 안전 정책은 유지하고 문서 구성에 필요한 추가 지침만 입력합니다.",
        )
        prompt_columns = self._widgets.QHBoxLayout()
        prompt_columns.setSpacing(12)
        fixed_panel = self._widgets.QFrame()
        self._set_role(fixed_panel, "subtlePanel")
        fixed_layout = self._widgets.QVBoxLayout(fixed_panel)
        fixed_layout.setContentsMargins(14, 12, 14, 14)
        fixed_layout.addWidget(self._label("고정 안전 정책", "fieldLabel"))
        fixed = self._widgets.QPlainTextEdit(_FIXED_POLICY_PREVIEW)
        fixed.setReadOnly(True)
        fixed.setMinimumHeight(150)
        fixed_layout.addWidget(fixed)
        custom_panel = self._widgets.QFrame()
        self._set_role(custom_panel, "subtlePanel")
        custom_layout = self._widgets.QVBoxLayout(custom_panel)
        custom_layout.setContentsMargins(14, 12, 14, 14)
        custom_layout.addWidget(self._label("사용자 추가 지침", "fieldLabel"))
        self._additional_prompt = self._widgets.QPlainTextEdit()
        self._additional_prompt.setAccessibleName("사용자 추가 시스템 지침")
        self._additional_prompt.setPlaceholderText(
            "예: 운영 명령과 롤백 절차를 우선하고, 버전별 차이를 별도 표로 정리한다."
        )
        self._additional_prompt.setMinimumHeight(150)
        custom_layout.addWidget(self._additional_prompt)
        prompt_columns.addWidget(fixed_panel, 1)
        prompt_columns.addWidget(custom_panel, 1)
        prompts_layout.addLayout(prompt_columns)
        layout.addWidget(prompts)

        action_bar = self._widgets.QFrame()
        self._set_role(action_bar, "actionBar")
        controls = self._widgets.QHBoxLayout(action_bar)
        controls.setContentsMargins(16, 12, 16, 12)
        self._settings_status = self._label("설정을 불러오는 중", "muted", True)
        controls.addWidget(self._settings_status, 1)
        reload_button = self._button("다시 불러오기", "ghost")
        reload_button.clicked.connect(self._load_settings)
        save = self._button("변경사항 저장", "primary")
        save.clicked.connect(self._save_settings)
        controls.addWidget(reload_button)
        controls.addWidget(save)
        layout.addWidget(action_bar)

        canvas_layout.addStretch(1)
        canvas_layout.addWidget(content, 12)
        canvas_layout.addStretch(1)
        scroll.setWidget(canvas)
        page_layout.addWidget(scroll)
        return page

    def _execution_tab(self) -> Any:
        page = self._widgets.QWidget()
        page.setProperty("role", "page")
        page_layout = self._widgets.QVBoxLayout(page)
        page_layout.setContentsMargins(0, 8, 0, 0)
        scroll = self._widgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(
            self._core.Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        canvas = self._widgets.QWidget()
        canvas.setProperty("role", "page")
        layout = self._widgets.QVBoxLayout(canvas)
        layout.setContentsMargins(2, 0, 2, 10)
        layout.setSpacing(14)
        layout.addWidget(
            self._page_intro(
                "문서 파이프라인",
                "작업을 만들고 실행한 뒤 체크포인트와 품질 검증 상태를 한곳에서 확인합니다.",
            )
        )

        top_splitter = self._widgets.QSplitter(self._core.Qt.Orientation.Horizontal)
        self._execution_top_splitter = top_splitter
        top_splitter.setChildrenCollapsible(False)
        top_splitter.setMinimumHeight(318)
        control, control_layout = self._card(
            "작업 준비",
            "기존 Job을 선택하거나 새로운 문서 작업을 생성하세요.",
        )
        control.setMinimumWidth(650)
        job_row = self._widgets.QHBoxLayout()
        job_row.setSpacing(8)
        self._jobs = self._widgets.QComboBox()
        self._jobs.currentIndexChanged.connect(self._select_job)
        refresh_jobs = self._button("목록 새로고침", "ghost")
        refresh_jobs.clicked.connect(self._reload_jobs)
        job_row.addWidget(self._jobs, 1)
        job_row.addWidget(refresh_jobs)
        control_layout.addWidget(self._label("작업 선택", "fieldLabel"))
        control_layout.addLayout(job_row)

        output_row = self._widgets.QHBoxLayout()
        output_row.setSpacing(10)
        output_label = self._label("결과 파일", "fieldLabel")
        output_label.setFixedWidth(74)
        self._output_name = self._widgets.QLineEdit("integrated-technical-guide.md")
        output_row.addWidget(output_label)
        output_row.addWidget(self._output_name, 1)
        control_layout.addLayout(output_row)

        control_layout.addWidget(self._label("작업 지시", "fieldLabel"))
        self._instruction = self._widgets.QPlainTextEdit()
        self._instruction.setAccessibleName("문서 작업 지시")
        self._instruction.setPlaceholderText(
            "생성할 문서의 목적, 필수 주제, 보존할 운영 세부사항을 입력하세요."
        )
        self._instruction.setFixedHeight(84)
        control_layout.addWidget(self._instruction)

        self._job_feedback = self._label("", "feedback", True)
        self._job_feedback.setAccessibleName("작업 생성 안내")
        self._job_feedback.setTextInteractionFlags(
            self._core.Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._job_feedback.setMinimumHeight(48)
        self._job_feedback.hide()
        control_layout.addWidget(self._job_feedback)

        action_row = self._widgets.QHBoxLayout()
        action_row.setSpacing(8)
        self._create_button = self._button("새 작업 생성", "secondary")
        self._create_button.setToolTip("현재 설정을 고정해 재개 가능한 새 Job을 만듭니다.")
        self._create_button.clicked.connect(self._create_job)
        self._start_button = self._button("파이프라인 시작", "primary")
        self._start_button.setToolTip("선택한 Job을 시작하거나 마지막 체크포인트부터 재개합니다.")
        self._start_button.clicked.connect(self._start_job)
        self._cancel_job_button = self._button("작업 취소", "danger")
        self._cancel_job_button.setToolTip(
            "Worker에 안전한 취소를 요청하며 완료된 체크포인트는 보존합니다."
        )
        self._cancel_job_button.clicked.connect(self._cancel_job)
        refresh = self._button("상태 새로고침", "ghost")
        refresh.clicked.connect(self._refresh_dashboard)
        action_row.addWidget(self._create_button)
        action_row.addWidget(self._start_button)
        action_row.addStretch(1)
        action_row.addWidget(refresh)
        action_row.addWidget(self._cancel_job_button)
        control_layout.addLayout(action_row)
        top_splitter.addWidget(control)

        summary, summary_layout = self._card(
            "실시간 상태",
            "2초마다 Worker와 단계 진행 상태를 갱신합니다.",
        )
        summary.setMinimumWidth(340)
        state_row = self._widgets.QHBoxLayout()
        state_row.addWidget(self._label("현재 상태", "metricLabel"))
        state_row.addStretch(1)
        self._state = self._label("대기", "statusChip")
        self._set_tone(self._state, "neutral")
        state_row.addWidget(self._state)
        summary_layout.addLayout(state_row)

        progress_header = self._widgets.QHBoxLayout()
        progress_header.addWidget(self._label("전체 진행률", "fieldLabel"))
        progress_header.addStretch(1)
        self._progress_value = self._label("0%", "fieldLabel")
        progress_header.addWidget(self._progress_value)
        summary_layout.addLayout(progress_header)
        self._progress = self._widgets.QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setAccessibleName("문서 파이프라인 전체 진행률")
        summary_layout.addWidget(self._progress)
        summary_layout.addWidget(self._label("현재 단계", "metricLabel"))
        self._last_message = self._label("이벤트 없음", "callout", True)
        self._last_message.setMinimumHeight(54)
        summary_layout.addWidget(self._last_message)
        summary_layout.addWidget(self._label("Worker", "metricLabel"))
        self._runner = self._label("시작 기록 없음", "muted", True)
        summary_layout.addWidget(self._runner)
        summary_layout.addStretch(1)
        top_splitter.addWidget(summary)
        top_splitter.setSizes((860, 480))
        layout.addWidget(top_splitter)

        result_group, result_layout = self._card(
            "결과 및 품질",
            "게시 결과의 무결성, coverage, 변경 건수와 알림 전달 상태를 요약합니다.",
        )
        result_group.setMinimumHeight(330)
        metrics = self._widgets.QGridLayout()
        metrics.setContentsMargins(0, 0, 0, 0)
        metrics.setHorizontalSpacing(10)
        metrics.setVerticalSpacing(10)
        self._result_status = self._label("결과 대기 중", "metricValue", True)
        self._quality_summary = self._label("품질 보고서 대기 중", "metricValue", True)
        self._comparison_summary = self._label("비교 보고서 대기 중", "metricValue", True)
        self._notification_status = self._label("알림 상태 대기 중", "metricValue", True)
        for label in (
            self._result_status,
            self._quality_summary,
            self._comparison_summary,
            self._notification_status,
        ):
            label.setWordWrap(True)
        for index, (title, value) in enumerate(
            (
                ("게시 상태", self._result_status),
                ("품질 지표", self._quality_summary),
                ("변경 요약", self._comparison_summary),
                ("완료 알림", self._notification_status),
            )
        ):
            panel = self._widgets.QFrame()
            self._set_role(panel, "subtlePanel")
            panel_layout = self._widgets.QVBoxLayout(panel)
            panel_layout.setContentsMargins(13, 10, 13, 11)
            panel_layout.setSpacing(5)
            panel_layout.addWidget(self._label(title, "metricLabel"))
            panel_layout.addWidget(value)
            metrics.addWidget(panel, index // 2, index % 2)
        metrics.setColumnStretch(0, 1)
        metrics.setColumnStretch(1, 1)
        result_layout.addLayout(metrics)

        result_layout.addWidget(self._label("검증된 산출물", "fieldLabel"))
        files = self._widgets.QGridLayout()
        files.setContentsMargins(0, 0, 0, 0)
        files.setHorizontalSpacing(12)
        files.setVerticalSpacing(8)
        for index, (title, key) in enumerate(
            (
                ("최종 문서", "document"),
                ("품질 JSON", "quality"),
                ("비교 보고서", "comparison"),
                ("합성 보고서", "synthesis"),
            )
        ):
            container = self._widgets.QWidget()
            container_layout = self._widgets.QVBoxLayout(container)
            container_layout.setContentsMargins(0, 0, 0, 0)
            container_layout.setSpacing(5)
            container_layout.addWidget(self._label(title, "metricLabel"))
            container_layout.addWidget(self._result_path_row(key))
            files.addWidget(container, index // 2, index % 2)
        files.setColumnStretch(0, 1)
        files.setColumnStretch(1, 1)
        result_layout.addLayout(files)
        layout.addWidget(result_group)

        detail_card, detail_layout = self._card(
            "실행 상세",
            "저장된 단계와 전체 이벤트 기록을 전환해 확인할 수 있습니다.",
        )
        detail_card.setMinimumHeight(360)
        detail_tabs = self._widgets.QTabWidget()
        self._style_tab_surface(detail_tabs, "#FFFFFF", "detailTabs")
        detail_tabs.setDocumentMode(True)
        checkpoint_page = self._widgets.QWidget()
        checkpoint_layout = self._widgets.QVBoxLayout(checkpoint_page)
        checkpoint_layout.setContentsMargins(0, 8, 0, 0)
        self._checkpoints = self._widgets.QTableWidget(0, 7)
        self._checkpoints.setHorizontalHeaderLabels(
            ("체크포인트", "상태", "건수", "재개", "경로", "상세", "ID")
        )
        self._prepare_table(self._checkpoints)
        checkpoint_header = self._checkpoints.horizontalHeader()
        for column in (0, 1, 2, 3, 4, 6):
            checkpoint_header.setSectionResizeMode(
                column,
                self._widgets.QHeaderView.ResizeMode.ResizeToContents,
            )
        checkpoint_header.setSectionResizeMode(
            5,
            self._widgets.QHeaderView.ResizeMode.Stretch,
        )
        checkpoint_layout.addWidget(self._checkpoints)
        detail_tabs.addTab(checkpoint_page, "체크포인트")

        events_page = self._widgets.QWidget()
        events_layout = self._widgets.QVBoxLayout(events_page)
        events_layout.setContentsMargins(0, 8, 0, 0)
        self._events = self._widgets.QTableWidget(0, 7)
        self._events.setHorizontalHeaderLabels(
            ("순서", "단계", "메시지", "완료/전체", "카운터", "진행률", "시각")
        )
        self._prepare_table(self._events)
        event_header = self._events.horizontalHeader()
        for column in (0, 1, 3, 4, 5, 6):
            event_header.setSectionResizeMode(
                column,
                self._widgets.QHeaderView.ResizeMode.ResizeToContents,
            )
        event_header.setSectionResizeMode(
            2,
            self._widgets.QHeaderView.ResizeMode.Stretch,
        )
        events_layout.addWidget(self._events)
        detail_tabs.addTab(events_page, "이벤트 타임라인")
        detail_layout.addWidget(detail_tabs)
        layout.addWidget(detail_card)
        scroll.setWidget(canvas)
        page_layout.addWidget(scroll)
        return page

    def _result_path_row(self, key: str) -> Any:
        container = self._widgets.QWidget()
        layout = self._widgets.QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        field = self._widgets.QLineEdit()
        field.setReadOnly(True)
        field.setPlaceholderText("게시 완료 후 경로가 표시됩니다.")
        button = self._button("열기", "ghost")
        button.setEnabled(False)
        button.clicked.connect(lambda: self._open_result_path(key))
        self._result_fields[key] = field
        self._result_buttons[key] = button
        layout.addWidget(field, 1)
        layout.addWidget(button)
        return container

    def _folder_row(self, field: Any) -> Any:
        container = self._widgets.QWidget()
        layout = self._widgets.QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        browse = self._button("찾아보기", "secondary")
        browse.clicked.connect(lambda: self._browse_folder(field))
        layout.addWidget(field, 1)
        layout.addWidget(browse)
        return container

    def _browse_folder(self, field: Any) -> None:
        selected = self._widgets.QFileDialog.getExistingDirectory(
            self.window,
            "폴더 선택",
            field.text() or str(Path.home()),
        )
        if selected:
            field.setText(selected)

    def _load_settings(self) -> None:
        try:
            settings = self._view_model.load_settings()
            self._settings = settings
            self._source_root.setText(settings.source_root)
            self._output_root.setText(settings.output_root)
            self._model_id.setText(settings.model_id)
            self._model_revision.setText(settings.model_revision)
            self._set_context_tokens(settings.context_tokens)
            self._max_output_tokens.setValue(settings.max_output_tokens)
            self._additional_prompt.setPlainText(settings.additional_system_prompt)
            self._max_attempts.setValue(settings.max_task_attempts)
            self._offline_mode.setChecked(settings.offline_mode)
            self._notify.setChecked(settings.notify_on_completion)
            self._settings_status.setText(
                f"설정 revision {settings.settings_revision} · 다음 Job부터 적용"
            )
            self._refresh_local_models()
        except Exception as error:
            self._show_error(error)

    def _offline_mode_changed(self, offline: bool) -> None:
        self._remote_models_button.setEnabled(not offline)
        if offline:
            self._model_catalog_status.setText(
                "오프라인 모드에서는 로컬 cache의 정확한 commit만 Job에 사용할 수 있습니다."
            )
        self._model_catalog_selection_changed()

    def _refresh_local_models(self) -> None:
        query = self._model_query.text().strip()
        self._model_catalog_status.setText("로컬 Hugging Face cache를 검사하는 중입니다.")
        self._set_catalog_busy(True)
        self._run_background(
            lambda: self._view_model.local_models(query),
            self._render_model_catalog,
        )

    def _search_remote_models(self) -> None:
        if self._offline_mode.isChecked():
            self._model_catalog_status.setText(
                "최신 모델 검색을 사용하려면 오프라인 모드를 해제하세요."
            )
            return
        query = self._model_query.text().strip()
        self._model_catalog_status.setText(
            "Hugging Face에서 최신 MLX 모델을 검색하는 중입니다."
        )
        self._set_catalog_busy(True)
        self._run_background(
            lambda: self._view_model.search_models(query),
            self._render_model_catalog,
        )

    def _inspect_current_model(self) -> None:
        model_id = self._model_id.text().strip()
        revision = self._model_revision.text().strip().lower()
        offline = self._offline_mode.isChecked()
        self._model_catalog_status.setText("선택한 모델과 commit을 검증하는 중입니다.")
        self._set_catalog_busy(True)
        self._run_background(
            lambda: self._view_model.inspect_model(model_id, revision, offline),
            self._render_model_inspection,
        )

    def _render_model_inspection(self, entry: ModelCatalogEntryDto) -> None:
        self._render_model_catalog(
            ModelCatalogDto(entry.model_id, not entry.cached, (entry,))
        )
        self._model_catalog_status.setText(
            f"검증 완료 · {entry.compatibility.value} · {entry.compatibility_detail}"
        )

    def _render_model_catalog(self, catalog: ModelCatalogDto) -> None:
        self._set_catalog_busy(False)
        self._model_catalog.setRowCount(len(catalog.entries))
        colors = {
            ModelCompatibility.SUPPORTED: "#137A46",
            ModelCompatibility.TIGHT: "#946200",
            ModelCompatibility.TOO_LARGE: "#B4232D",
            ModelCompatibility.UNSUPPORTED: "#B4232D",
            ModelCompatibility.UNKNOWN: "#667085",
        }
        for row, entry in enumerate(catalog.entries):
            location = "로컬 cache" if entry.cached else "Hugging Face"
            if entry.gated:
                location += " · 승인 필요"
            values = (
                entry.model_id,
                location,
                self._human_size(entry.size_bytes),
                entry.quantization,
                "-" if entry.context_tokens is None else f"{entry.context_tokens:,}",
                entry.compatibility.value,
                entry.revision,
                entry.license_name,
                entry.modified_at or "-",
            )
            for column, value in enumerate(values):
                item = self._widgets.QTableWidgetItem(value)
                if column == 0:
                    item.setData(self._core.Qt.ItemDataRole.UserRole, entry)
                if column == 5:
                    item.setForeground(self._gui.QColor(colors[entry.compatibility]))
                    item.setToolTip(entry.compatibility_detail)
                self._model_catalog.setItem(row, column, item)
        self._model_catalog.resizeColumnsToContents()
        source = "Hugging Face 최신 결과" if catalog.remote else "로컬 cache"
        query = f" · 검색어: {catalog.query}" if catalog.query else ""
        self._model_catalog_status.setText(
            f"{source} {len(catalog.entries)}건{query} · 행을 두 번 누르면 적용됩니다."
        )
        if catalog.entries:
            self._model_catalog.selectRow(0)
        self._model_catalog_selection_changed()

    def _selected_model(self) -> ModelCatalogEntryDto | None:
        row = self._model_catalog.currentRow()
        if row < 0:
            return None
        item = self._model_catalog.item(row, 0)
        if item is None:
            return None
        value = item.data(self._core.Qt.ItemDataRole.UserRole)
        return value if isinstance(value, ModelCatalogEntryDto) else None

    def _model_catalog_selection_changed(self) -> None:
        entry = self._selected_model()
        idle = self._active_download_id is None
        self._apply_model_button.setEnabled(idle and entry is not None)
        downloadable = (
            idle
            and entry is not None
            and not entry.cached
            and not entry.gated
            and entry.compatibility
            not in {ModelCompatibility.TOO_LARGE, ModelCompatibility.UNSUPPORTED}
            and not self._offline_mode.isChecked()
        )
        self._download_model_button.setEnabled(downloadable)

    def _apply_selected_model(self, *_: object) -> None:
        entry = self._selected_model()
        if entry is None:
            return
        self._model_id.setText(entry.model_id)
        self._model_revision.setText(entry.revision)
        if (
            entry.context_tokens is not None
            and self._context_value() > entry.context_tokens
            and entry.context_tokens >= 4_096
        ):
            bounded = min(entry.context_tokens, 131_072)
            self._set_context_tokens((bounded // 1_024) * 1_024)
        warning = ""
        if not entry.cached:
            warning = " · 다운로드 단계가 완료되기 전에는 Job을 생성할 수 없습니다."
        self._model_catalog_status.setText(
            f"선택 적용 · {entry.compatibility.value} · {entry.compatibility_detail}{warning}"
        )

    def _download_selected_model(self) -> None:
        entry = self._selected_model()
        if entry is None:
            return
        if self._offline_mode.isChecked():
            self._model_catalog_status.setText(
                "모델을 다운로드하려면 오프라인 모드를 해제하세요."
            )
            return
        if entry.cached:
            self._model_catalog_status.setText("이미 정확한 commit이 로컬에 있습니다.")
            return
        download_id = self._view_model.new_model_download_id()
        self._active_download_id = download_id
        self._download_progress.setValue(0)
        self._download_detail.setText("다운로드 사전 검사를 시작합니다.")
        self._cancel_download_button.setEnabled(True)
        self._set_catalog_busy(True)
        self._run_background(
            lambda: self._view_model.download_model(
                download_id,
                entry.model_id,
                entry.revision,
                self._publish_download_progress,
            ),
            self._model_download_completed,
            error_scope="model_download",
        )

    def _publish_download_progress(self, progress: ModelDownloadProgressDto) -> None:
        if not self._closing:
            self._background_bridge.progress.emit(progress)

    def _render_download_progress(self, value: object) -> None:
        if not isinstance(value, ModelDownloadProgressDto):
            return
        if value.download_id != self._active_download_id:
            return
        self._download_progress.setValue(value.percentage)
        byte_progress = (
            f"{self._human_size(value.completed_bytes)} / "
            f"{self._human_size(value.total_bytes)}"
            if value.total_bytes
            else "용량 계산 중"
        )
        file_progress = f"파일 {value.completed_files}/{value.total_files}"
        self._download_detail.setText(
            f"{value.state.value} · {byte_progress} · {file_progress} · {value.message}"
        )
        if value.state is ModelDownloadState.CANCELLED:
            self._cancel_download_button.setEnabled(False)

    def _cancel_model_download(self) -> None:
        download_id = self._active_download_id
        if download_id is None:
            return
        try:
            accepted = self._view_model.cancel_model_download(download_id)
        except Exception as error:
            self._show_error(error)
            return
        self._cancel_download_button.setEnabled(False)
        self._download_detail.setText(
            "취소를 요청했습니다. 현재 파일의 안전한 중단 지점을 기다리는 중입니다."
            if accepted
            else "다운로드 작업이 이미 종료되었습니다."
        )

    def _model_download_completed(self, entry: ModelCatalogEntryDto) -> None:
        self._active_download_id = None
        self._cancel_download_button.setEnabled(False)
        self._offline_mode.setChecked(True)
        self._model_id.setText(entry.model_id)
        self._model_revision.setText(entry.revision)
        self._render_model_inspection(entry)
        self._download_progress.setValue(100)
        self._download_detail.setText(
            "COMPLETED · snapshot과 가중치 검증 완료 · 오프라인 모드로 전환했습니다."
        )

    @staticmethod
    def _human_size(value: int | None) -> str:
        if value is None:
            return "확인 필요"
        gib = value / (1024**3)
        return f"{gib:.1f} GiB" if gib >= 0.1 else f"{value / (1024**2):.1f} MiB"

    def _set_catalog_busy(self, busy: bool) -> None:
        idle = not busy and self._active_download_id is None
        self._local_models_button.setEnabled(idle)
        self._inspect_model_button.setEnabled(idle)
        self._remote_models_button.setEnabled(
            idle and not self._offline_mode.isChecked()
        )
        if busy:
            self._apply_model_button.setEnabled(False)
            self._download_model_button.setEnabled(False)
        else:
            self._model_catalog_selection_changed()

    def _run_background(
        self,
        operation: Callable[[], Any],
        on_success: Callable[[Any], None],
        *,
        error_scope: str = "general",
    ) -> None:
        if self._closing:
            return
        future = self._executor.submit(operation)
        self._futures.add(future)

        def completed(value: Future[Any]) -> None:
            self._futures.discard(value)
            if self._closing:
                return
            try:
                result = value.result()
            except Exception as error:
                self._background_bridge.failed.emit((error_scope, error))
            else:
                self._background_bridge.completed.emit((on_success, result))

        future.add_done_callback(completed)

    def _background_completed(self, payload: object) -> None:
        if not isinstance(payload, tuple) or len(payload) != 2:
            self._background_failed(RuntimeError("invalid background result"))
            return
        callback = cast(Callable[[Any], None], payload[0])
        result = payload[1]
        try:
            callback(result)
        except Exception as error:
            self._background_failed(("general", error))

    def _background_failed(self, payload: object) -> None:
        if (
            isinstance(payload, tuple)
            and len(payload) == 2
            and isinstance(payload[0], str)
            and isinstance(payload[1], Exception)
        ):
            error_scope = payload[0]
            error = payload[1]
        elif isinstance(payload, Exception):
            error_scope = "general"
            error = payload
        else:
            error_scope = "general"
            error = RuntimeError("invalid background error")
        was_download = error_scope == "model_download"
        was_job_creation = error_scope == "job_creation"
        if was_download:
            self._active_download_id = None
            self._cancel_download_button.setEnabled(False)
        self._set_catalog_busy(False)
        self._create_button.setEnabled(True)
        if (
            was_download
            and isinstance(error, ApplicationError)
            and error.code == "MODEL_DOWNLOAD_CANCELLED"
        ):
            self._download_detail.setText(
                "CANCELLED · 불완전 파일은 모델 snapshot으로 사용되지 않습니다."
            )
            return
        if was_download:
            self._download_detail.setText("FAILED · 모델 다운로드를 완료하지 못했습니다.")
        if was_job_creation:
            message, guidance, code = _error_notice(error)
            self._show_feedback(
                self._job_feedback,
                f"{message}\n{guidance} · 오류 코드: {code}",
                "danger",
            )
            self._last_message.setText(f"작업 생성 실패 · {message}")
        self._show_error(error)

    def _save_settings(self) -> None:
        if self._settings is None:
            return
        try:
            desired = replace(
                self._settings,
                source_root=self._source_root.text().strip(),
                output_root=self._output_root.text().strip(),
                model_id=self._model_id.text().strip(),
                model_revision=self._model_revision.text().strip().lower(),
                context_tokens=self._context_value(),
                max_output_tokens=self._max_output_tokens.value(),
                additional_system_prompt=self._additional_prompt.toPlainText(),
                max_task_attempts=self._max_attempts.value(),
                offline_mode=self._offline_mode.isChecked(),
                notify_on_completion=self._notify.isChecked(),
            )
            self._settings = self._view_model.save_settings(desired)
            self._settings_status.setText(
                f"저장 완료 · revision {self._settings.settings_revision} · 다음 Job부터 적용"
            )
        except Exception as error:
            self._show_error(error)

    def _set_context_tokens(self, value: int) -> None:
        for index in range(self._context_tokens.count()):
            if self._context_tokens.itemData(index) == value:
                self._context_tokens.setCurrentIndex(index)
                return
        self._context_tokens.setEditText(str(value))

    def _context_value(self) -> int:
        data = self._context_tokens.currentData()
        if data is not None and not self._context_tokens.currentText().strip().isdigit():
            return int(data)
        return int(self._context_tokens.currentText().replace(",", "").strip())

    def _reload_jobs(self) -> None:
        try:
            selected = self._active_job_id
            jobs = self._view_model.list_jobs()
            self._jobs.blockSignals(True)
            self._jobs.clear()
            for job in jobs:
                self._jobs.addItem(
                    f"{job.job_id} · {job.state.value} · {job.last_percentage}%",
                    job.job_id,
                )
            self._jobs.blockSignals(False)
            if jobs:
                target = 0
                if selected is not None:
                    for index in range(self._jobs.count()):
                        if self._jobs.itemData(index) == selected:
                            target = index
                            break
                self._jobs.setCurrentIndex(target)
                self._active_job_id = str(self._jobs.itemData(target))
                self._refresh_dashboard()
            else:
                self._active_job_id = None
                self._clear_dashboard()
        except Exception as error:
            self._show_error(error)

    def _select_job(self, index: int) -> None:
        if index < 0:
            return
        value = self._jobs.itemData(index)
        self._active_job_id = None if value is None else str(value)
        self._refresh_dashboard()

    def _create_job(self) -> None:
        instruction = self._instruction.toPlainText()
        output_name = self._output_name.text().strip()
        validation = _job_form_error(instruction, output_name)
        if validation is not None:
            message, guidance, field = validation
            self._show_feedback(
                self._job_feedback,
                f"{message}\n{guidance}",
                "danger",
            )
            self._last_message.setText(f"작업 생성 대기 · {message}")
            target = self._instruction if field == "instruction" else self._output_name
            target.setFocus()
            return
        self._clear_feedback(self._job_feedback)
        self._clear_feedback(self._app_feedback)
        self._create_button.setEnabled(False)
        self._show_feedback(
            self._job_feedback,
            "작업 설정과 로컬 모델을 검증하는 중입니다.",
            "info",
        )
        self._last_message.setText(
            "모델 commit·cache·장비 적합성을 검증한 뒤 Job을 생성합니다."
        )
        self._run_background(
            lambda: self._view_model.create_job(instruction, output_name),
            self._job_created,
            error_scope="job_creation",
        )

    def _job_created(self, job: Any) -> None:
        self._create_button.setEnabled(True)
        self._active_job_id = job.job_id
        self._instruction.clear()
        self._clear_feedback(self._app_feedback)
        self._show_feedback(
            self._job_feedback,
            f"새 작업을 만들었습니다. · {job.job_id}",
            "success",
        )
        self._reload_jobs()

    def _cancel_job(self) -> None:
        if self._active_job_id is None:
            return
        answer = self._widgets.QMessageBox.question(
            self.window,
            "작업 취소",
            "현재 작업을 즉시 취소하시겠습니까?\n\n"
            "모델 생성은 토큰 경계에서 중단하고 저장된 체크포인트는 유지합니다. "
            f"{self._view_model.cancellation_grace_seconds}초 안에 정상 종료되지 않는 "
            "Worker만 강제 종료합니다.",
        )
        if answer != self._widgets.QMessageBox.StandardButton.Yes:
            return
        try:
            self._view_model.cancel_job(self._active_job_id)
            self._last_message.setText(
                "취소 신호를 전달했습니다. 모델 생성 중이면 다음 토큰 경계에서 중단하며 "
                f"최대 {self._view_model.cancellation_grace_seconds}초 동안 정상 종료를 기다립니다."
            )
            self._cancel_job_button.setEnabled(False)
            self._reload_jobs()
        except Exception as error:
            self._show_error(error)

    def _start_job(self) -> None:
        if self._active_job_id is None:
            return
        previous_text = self._start_button.text()
        self._start_button.setText("파이프라인 시작 중")
        self._start_button.setEnabled(False)
        try:
            process_id = self._view_model.start_job(self._active_job_id)
            self._last_message.setText(
                f"실행 프로세스 {process_id}를 시작했습니다. 상태 이벤트를 기다리는 중입니다."
            )
            self._timer.start()
        except Exception as error:
            if isinstance(error, ApplicationError) and error.code == "JOB_ALREADY_RUNNING":
                self._start_button.setText("파이프라인 실행 중")
            else:
                self._start_button.setText(previous_text)
                self._start_button.setEnabled(True)
            self._show_error(error)
        else:
            self._refresh_dashboard()

    def _refresh_dashboard(self) -> None:
        if self._active_job_id is None:
            return
        try:
            dashboard = self._view_model.dashboard(self._active_job_id)
            self._render_dashboard(dashboard)
            result = self._view_model.job_result(self._active_job_id)
            notification = self._view_model.completion_notification_status(
                self._active_job_id
            )
            self._render_result(result, notification)
            self._request_ready_notification(result, notification)
        except ApplicationError as error:
            if error.code == "JOB_NOT_FOUND":
                self._reload_jobs()
            else:
                self._show_error(error)
        except Exception as error:
            self._show_error(error)

    def _render_result(
        self,
        result: DocumentJobResultDto,
        notification: CompletionNotificationDto,
    ) -> None:
        status_text = {
            JobResultAvailability.NOT_READY: "아직 최종 품질·게시 결과가 없습니다.",
            JobResultAvailability.QUALITY_READY: "최종 품질 보고서가 생성됐고 게시를 기다립니다.",
            JobResultAvailability.PUBLISHED: "게시 문서와 비교 보고서 무결성 검증을 통과했습니다.",
        }[result.availability]
        self._result_status.setText(f"{result.availability.value} · {status_text}")
        quality = result.quality
        if quality is None:
            self._quality_summary.setText("품질 보고서 대기 중")
        else:
            errors = "없음" if not quality.error_codes else ", ".join(quality.error_codes)
            self._quality_summary.setText(
                f"{'통과' if quality.valid else '실패'} · "
                f"Task {quality.validated_task_count}/{quality.task_count} · "
                f"Claim {quality.covered_claim_count}/{quality.claim_count} · "
                f"Evidence {quality.covered_evidence_count}/{quality.evidence_count} · "
                f"원본 {quality.source_document_count}개 · 오류 {errors}"
            )
        counts = result.comparison_counts
        if counts is None:
            self._comparison_summary.setText("비교 보고서 대기 중")
        else:
            self._comparison_summary.setText(
                f"추가 {counts.added} · 수정 {counts.modified} · "
                f"삭제 {counts.removed} · 동일 {counts.unchanged} · 전체 {counts.total}"
            )
        self._render_notification(notification)
        paths = {
            "document": result.document_path,
            "quality": result.quality_report_path,
            "comparison": result.comparison_markdown_path,
            "synthesis": result.synthesis_report_path,
        }
        self._result_paths.clear()
        for key, path in paths.items():
            self._result_fields[key].setText(path or "")
            self._result_buttons[key].setEnabled(path is not None)
            if path is not None:
                self._result_paths[key] = path

    def _render_notification(self, notification: CompletionNotificationDto) -> None:
        descriptions = {
            CompletionNotificationState.NOT_READY: "게시 완료를 기다리는 중",
            CompletionNotificationState.DISABLED: "Job 설정에서 비활성화됨",
            CompletionNotificationState.READY: "알림 전달 준비 완료",
            CompletionNotificationState.CLAIMED: "알림 전달 선점됨 · 중복 전달 차단 중",
            CompletionNotificationState.DELIVERED: "시스템 완료 알림 전달 완료",
            CompletionNotificationState.FAILED: "시스템 완료 알림 전달 실패",
        }
        detail = descriptions[notification.state]
        if notification.finished_at is not None:
            detail += " · " + notification.finished_at.astimezone().strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        if notification.error_code is not None:
            detail += f" · 오류 {notification.error_code}"
        self._notification_status.setText(f"{notification.state.value} · {detail}")

    def _request_ready_notification(
        self,
        result: DocumentJobResultDto,
        notification: CompletionNotificationDto,
    ) -> None:
        job_id = result.job_id
        if (
            notification.state is not CompletionNotificationState.READY
            or job_id in self._notification_requests
            or self._closing
        ):
            return
        self._notification_requests.add(job_id)
        self._run_background(
            lambda: self._view_model.notify_completion(job_id),
            self._notification_completed,
        )

    def _notification_completed(self, value: object) -> None:
        if not isinstance(value, CompletionNotificationDto):
            return
        self._notification_requests.discard(value.job_id)
        if value.job_id == self._active_job_id:
            self._render_notification(value)

    def _open_result_path(self, key: str) -> None:
        path = self._result_paths.get(key)
        if path is None:
            return
        url = self._core.QUrl.fromLocalFile(path)
        if not self._gui.QDesktopServices.openUrl(url):
            self._show_error(ValueError("선택한 결과 파일을 열 수 없습니다."))

    def _render_dashboard(self, dashboard: JobDashboardDto) -> None:
        job = dashboard.job
        runner_busy = dashboard.runner is not None and dashboard.runner.health in {
            RunnerHealth.STARTING,
            RunnerHealth.HEALTHY,
        }
        tone = self._job_tone(job.state)
        self._header_job.setText(f"활성 Job: {job.job_id}")
        self._header_state.setText(job.state.value)
        self._set_tone(self._header_state, tone)
        self._state.setText(job.state.value)
        self._set_tone(self._state, tone)
        self._progress.setValue(job.last_percentage)
        self._progress_value.setText(f"{job.last_percentage}%")
        if runner_busy:
            self._start_button.setText("파이프라인 실행 중")
        elif job.state is DocumentJobState.FAILED:
            self._start_button.setText("실패 지점부터 복구")
        else:
            self._start_button.setText(
                "파이프라인 재개" if job.last_percentage else "파이프라인 시작"
            )
        self._start_button.setEnabled(
            not runner_busy
            and (
                job.state is DocumentJobState.FAILED
                or (
                    not job.state.terminal
                    and job.state
                    not in {
                        DocumentJobState.CANCELLING,
                        DocumentJobState.NEEDS_ATTENTION,
                    }
                )
            )
        )
        self._cancel_job_button.setEnabled(
            not job.state.terminal and job.state is not DocumentJobState.CANCELLING
        )
        self._render_runner(dashboard)
        if job.state is DocumentJobState.CANCELLING:
            self._last_message.setText(
                "취소 처리 중 · 모델 토큰 경계에서 중단한 뒤 체크포인트를 닫는 중입니다. "
                f"정상 종료 유예는 {self._view_model.cancellation_grace_seconds}초입니다."
            )
        elif job.state is DocumentJobState.CANCELLED:
            self._last_message.setText(
                "취소 완료 · 완료된 체크포인트는 보존되며 미완성 생성 결과는 게시되지 않습니다."
            )
        elif dashboard.events:
            event = dashboard.events[-1]
            counter = ""
            if event.completed is not None and event.total is not None:
                counter = f" · {event.completed}/{event.total} {event.counter_name or ''}"
            self._last_message.setText(f"{event.message}{counter}")
        else:
            self._last_message.setText("아직 진행 이벤트가 없습니다.")

        self._checkpoints.setRowCount(len(dashboard.checkpoints))
        colors = {
            CheckpointStatus.SAVED: "#137A46",
            CheckpointStatus.IN_PROGRESS: "#946200",
            CheckpointStatus.INVALID: "#B4232D",
            CheckpointStatus.MISSING: "#667085",
        }
        for row, checkpoint in enumerate(dashboard.checkpoints):
            values = (
                checkpoint.label,
                checkpoint.status.value,
                "-" if checkpoint.item_count is None else str(checkpoint.item_count),
                "예" if checkpoint.resumable else "아니요",
                checkpoint.relative_path,
                checkpoint.detail,
                checkpoint.checkpoint_id,
            )
            for column, value in enumerate(values):
                item = self._widgets.QTableWidgetItem(value)
                if column == 1:
                    item.setForeground(self._gui.QColor(colors[checkpoint.status]))
                self._checkpoints.setItem(row, column, item)

        self._events.setRowCount(len(dashboard.events))
        for row, event in enumerate(dashboard.events):
            count = "-"
            if event.completed is not None and event.total is not None:
                count = f"{event.completed}/{event.total}"
            values = (
                "-" if event.sequence is None else str(event.sequence),
                event.stage,
                event.message,
                count,
                event.counter_name or "-",
                "-" if event.percentage is None else f"{event.percentage}%",
                event.occurred_at or "-",
            )
            for column, value in enumerate(values):
                self._events.setItem(row, column, self._widgets.QTableWidgetItem(value))
        if dashboard.events:
            self._events.scrollToBottom()

    @staticmethod
    def _job_tone(state: DocumentJobState) -> str:
        if state is DocumentJobState.COMPLETED:
            return "success"
        if state is DocumentJobState.FAILED:
            return "danger"
        if state in {DocumentJobState.NEEDS_ATTENTION, DocumentJobState.CANCELLING}:
            return "warning"
        if state in {DocumentJobState.CREATED, DocumentJobState.CANCELLED}:
            return "neutral"
        return "info"

    def _render_runner(self, dashboard: JobDashboardDto) -> None:
        if dashboard.runner is None:
            self._runner.setText("시작 기록 없음")
            self._runner.setStyleSheet("")
            return
        runner = dashboard.runner
        lease = runner.lease
        process = "PID 대기 중" if lease.process_id is None else f"PID {lease.process_id}"
        age = f"마지막 heartbeat {runner.heartbeat_age_seconds:.1f}초 전"
        detail = f"{runner.health.value} · {process} · {age} · 실행 #{lease.launch_sequence}"
        if dashboard.job.state is DocumentJobState.CANCELLING:
            detail += (
                " · SIGTERM 전달 · 정상 종료 대기 "
                f"(최대 {self._view_model.cancellation_grace_seconds}초)"
            )
        elif (
            dashboard.job.state is DocumentJobState.CANCELLED
            and runner.health in {RunnerHealth.HEALTHY, RunnerHealth.STALE}
        ):
            detail += " · 취소 완료 후 Worker 종료 확인 중"
        if lease.error_code is not None:
            detail += f" · 오류 {lease.error_code}"
        colors = {
            RunnerHealth.STARTING: "#946200",
            RunnerHealth.HEALTHY: "#137A46",
            RunnerHealth.STALE: "#B4232D",
            RunnerHealth.EXITED: "#2949B6",
            RunnerHealth.FAILED: "#B4232D",
        }
        self._runner.setText(detail)
        self._runner.setStyleSheet(f"color: {colors[runner.health]};")

    def _clear_dashboard(self) -> None:
        self._header_job.setText("활성 Job: 없음")
        self._header_state.setText("대기")
        self._set_tone(self._header_state, "neutral")
        self._state.setText("대기")
        self._set_tone(self._state, "neutral")
        self._progress.setValue(0)
        self._progress_value.setText("0%")
        self._start_button.setText("파이프라인 시작")
        self._start_button.setEnabled(False)
        self._cancel_job_button.setEnabled(False)
        self._runner.setText("시작 기록 없음")
        self._runner.setStyleSheet("")
        self._last_message.setText("이벤트 없음")
        self._checkpoints.setRowCount(0)
        self._events.setRowCount(0)
        self._result_status.setText("결과 대기 중")
        self._quality_summary.setText("품질 보고서 대기 중")
        self._comparison_summary.setText("비교 보고서 대기 중")
        self._notification_status.setText("알림 상태 대기 중")
        self._result_paths.clear()
        for key, field in self._result_fields.items():
            field.clear()
            self._result_buttons[key].setEnabled(False)

    def _show_error(self, error: Exception) -> None:
        message, guidance, code = _error_notice(error)
        self._show_feedback(
            self._app_feedback,
            f"{message}\n{guidance} · 오류 코드: {code}",
            "danger",
        )
        dialog = self._widgets.QMessageBox(self.window)
        dialog.setIcon(self._widgets.QMessageBox.Icon.Critical)
        dialog.setWindowTitle("작업을 완료하지 못했습니다")
        dialog.setText(message)
        dialog.setInformativeText(guidance)
        dialog.setDetailedText(f"오류 코드: {code}")
        dialog.setStandardButtons(self._widgets.QMessageBox.StandardButton.Ok)
        dialog.setStyleSheet(
            "QMessageBox { background-color: #FFFFFF; color: #172033; }"
            "QMessageBox QLabel { background-color: transparent; color: #172033; }"
            "QMessageBox QTextEdit { background-color: #F7F9FC; color: #344054; "
            "border: 1px solid #D7DEE8; border-radius: 8px; }"
            "QMessageBox QPushButton { background-color: #3B5BDB; color: #FFFFFF; "
            "border: 1px solid #3B5BDB; border-radius: 8px; padding: 7px 18px; }"
        )
        palette = dialog.palette()
        palette.setColor(
            self._gui.QPalette.ColorRole.Window,
            self._gui.QColor("#FFFFFF"),
        )
        palette.setColor(
            self._gui.QPalette.ColorRole.WindowText,
            self._gui.QColor("#172033"),
        )
        palette.setColor(
            self._gui.QPalette.ColorRole.Text,
            self._gui.QColor("#172033"),
        )
        dialog.setPalette(palette)
        dialog.exec()

    def close(self) -> None:
        if self._active_download_id is not None:
            try:
                self._view_model.cancel_model_download(self._active_download_id)
            except Exception:
                pass
        self._closing = True
        for future in tuple(self._futures):
            future.cancel()
        self._executor.shutdown(wait=False, cancel_futures=True)


def _configure_qt_theme(qt_gui: Any, qt_widgets: Any, application: Any) -> None:
    application.setStyle("Fusion")
    palette = qt_gui.QPalette()
    colors = {
        qt_gui.QPalette.ColorRole.Window: "#F4F7FB",
        qt_gui.QPalette.ColorRole.WindowText: "#172033",
        qt_gui.QPalette.ColorRole.Base: "#FFFFFF",
        qt_gui.QPalette.ColorRole.AlternateBase: "#F8FAFC",
        qt_gui.QPalette.ColorRole.ToolTipBase: "#111827",
        qt_gui.QPalette.ColorRole.ToolTipText: "#FFFFFF",
        qt_gui.QPalette.ColorRole.Text: "#172033",
        qt_gui.QPalette.ColorRole.Button: "#FFFFFF",
        qt_gui.QPalette.ColorRole.ButtonText: "#344054",
        qt_gui.QPalette.ColorRole.Highlight: "#3B5BDB",
        qt_gui.QPalette.ColorRole.HighlightedText: "#FFFFFF",
        qt_gui.QPalette.ColorRole.PlaceholderText: "#98A2B3",
    }
    for role, value in colors.items():
        palette.setColor(role, qt_gui.QColor(value))
    palette.setColor(
        qt_gui.QPalette.ColorGroup.Disabled,
        qt_gui.QPalette.ColorRole.Text,
        qt_gui.QColor("#A7B0BF"),
    )
    palette.setColor(
        qt_gui.QPalette.ColorGroup.Disabled,
        qt_gui.QPalette.ColorRole.ButtonText,
        qt_gui.QColor("#A7B0BF"),
    )
    palette.setColor(
        qt_gui.QPalette.ColorGroup.Disabled,
        qt_gui.QPalette.ColorRole.WindowText,
        qt_gui.QColor("#A7B0BF"),
    )
    application.setPalette(palette)
    qt_widgets.QToolTip.setPalette(palette)


def main(
    application_factory: Callable[[Path, str | None], JobApplication],
    argv: list[str] | None = None,
) -> int:
    args = _parser().parse_args(argv)
    try:
        qt_core = importlib.import_module("PySide6.QtCore")
        qt_gui = importlib.import_module("PySide6.QtGui")
        qt_widgets = importlib.import_module("PySide6.QtWidgets")
    except ModuleNotFoundError:
        print(
            "PySide6가 설치되지 않았습니다. "
            "`python -m pip install -e '.[gui]'` 후 다시 실행하세요.",
            file=sys.stderr,
        )
        return 2
    try:
        application = application_factory(args.project_root, args.environment)
    except ApplicationError as error:
        print(f"{error.safe_message} ({error.code})", file=sys.stderr)
        return 2
    qt_application = qt_widgets.QApplication(sys.argv[:1])
    _configure_qt_theme(qt_gui, qt_widgets, qt_application)
    view_model = DesktopViewModel(application)
    desktop = _DesktopWindow(qt_core, qt_gui, qt_widgets, view_model)
    qt_application.aboutToQuit.connect(desktop.close)
    qt_application.aboutToQuit.connect(view_model.close)
    desktop.window.show()
    return int(qt_application.exec())
