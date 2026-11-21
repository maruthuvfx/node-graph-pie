"""Manage temporary native Nuke Properties windows."""


def open_panels(nodes, qt):
    core, _, widgets = qt
    app = widgets.QApplication.instance()
    session = getattr(app, "_studio_pie_properties", None)
    if session is not None:
        session.dismiss()

    class Session(core.QObject):
        def __init__(self):
            super().__init__(app)
            self.windows = {}
            self.active = True
            app.installEventFilter(self)
            app._studio_pie_properties = self

        def attach(self, window):
            if window not in self.windows:
                self.windows[window] = window.windowOpacity()
                window.setWindowOpacity(1.0)

        def finish(self):
            self.active = False
            app.removeEventFilter(self)
            if app._studio_pie_properties is self:
                app._studio_pie_properties = None
            self.deleteLater()

        def dismiss(self):
            windows = self.windows
            self.windows = {}
            self.finish()
            for window, opacity in windows.items():
                try:
                    window.setWindowOpacity(opacity)
                    window.close()
                except RuntimeError:
                    pass  # Nuke may already have destroyed the native panel.

        def eventFilter(self, watched, event):
            kind = event.type()
            if kind == core.QEvent.Hide and watched in self.windows:
                watched.setWindowOpacity(self.windows.pop(watched))
                if not self.windows:
                    self.finish()
            if kind in (core.QEvent.ShortcutOverride, core.QEvent.KeyPress):
                focus_window = watched.window() if isinstance(watched, widgets.QWidget) else app.activeWindow()
                if (focus_window in self.windows and event.key() == core.Qt.Key_Escape):
                    event.accept()
                    if kind == core.QEvent.KeyPress:
                        core.QTimer.singleShot(0, lambda: self.dismiss() if self.active else None)
                    return True
            return False

    def visible_windows():
        return {window for window in app.topLevelWidgets()
                if window.isVisible() and not isinstance(window, widgets.QMainWindow)}

    session = Session()
    try:
        for node in nodes:
            before = visible_windows()
            node.showControlPanel(True)
            after = visible_windows()
            active = app.activeWindow()
            named = {window for window in after if node.name() in window.windowTitle()}
            candidates = named - before or after - before
            if not candidates and active in named:
                candidates = {active}
            if len(candidates) == 1:
                session.attach(next(iter(candidates)))
    finally:
        if session.active and not session.windows:
            session.finish()
