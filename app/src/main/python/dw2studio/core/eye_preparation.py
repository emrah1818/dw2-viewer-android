"""Prepare eye sprites outside the Qt render thread, with a bounded cache."""
from functools import lru_cache
from PyQt6.QtCore import QThread,pyqtSignal
from .disc import Disc
from .dw2_eyes import eye_layout,eye_animation_frames

@lru_cache(maxsize=8)
def prepared_eyes(model):
    layout=eye_layout(model)
    if layout is None:return None,()
    return layout,eye_animation_frames(model)

class EyePreparation(QThread):
    ready=pyqtSignal(str,object,object,object);failed=pyqtSignal(str,str)
    def __init__(self,key,image,entry,data=None):
        super().__init__();self.key=key;self.image=image;self.entry=entry;self.data=data
    def run(self):
        try:
            data=self.data
            if data is None:
                disc=Disc(self.image)
                try:data=disc.read(self.entry.lba,self.entry.size)
                finally:disc.close()
            layout,frames=prepared_eyes(bytes(data))
            if not self.isInterruptionRequested():self.ready.emit(self.key,bytes(data),layout,frames)
        except Exception as exc:
            if not self.isInterruptionRequested():self.failed.emit(self.key,str(exc))
