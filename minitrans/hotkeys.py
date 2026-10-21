"""Phím tắt toàn cục (hoạt động cả khi đang focus app khác)."""
from pynput import keyboard


class HotkeyManager:
    def __init__(self, hotkeys: dict, emit):
        self.listener = None
        self.hotkeys = hotkeys
        self.emit = emit  # emit(name) -> Bridge.hotkey.emit

    def start(self):
        self.stop()
        mapping = {combo: (lambda n=name: self.emit(n)) for name, combo in self.hotkeys.items() if combo}
        self.listener = keyboard.GlobalHotKeys(mapping)
        self.listener.daemon = True
        self.listener.start()

    def stop(self):
        if self.listener:
            self.listener.stop()
            self.listener = None
