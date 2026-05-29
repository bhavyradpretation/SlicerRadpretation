import threading
import queue
import qt
from Utils.logger import logger

class MainThreadDispatcher:
    """Safely dispatches function calls from background threads to the main Slicer Qt thread."""
    _instance = None
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = MainThreadDispatcher()
        return cls._instance

    def __init__(self):
        import slicer
        self.queue = queue.Queue()
        # Bind timer to the main window to ensure it stays alive and ticks in the main event loop
        self.timer = qt.QTimer(slicer.util.mainWindow())
        self.timer.timeout.connect(self._process_queue)
        self.timer.start(50)  # Check queue every 50ms on the main thread
        
    def _process_queue(self):
        while not self.queue.empty():
            func, args, kwargs = self.queue.get()
            try:
                func(*args, **kwargs)
            except Exception as e:
                logger.error(f"Error in main thread dispatcher: {e}")

    def dispatch(self, func, *args, **kwargs):
        """Queue a function to be executed on the main thread."""
        func_name = getattr(func, "__name__", type(func).__name__)
        if func_name not in ("show_status", "<lambda>"):
            logger.info(f"Dispatching function to main thread: {func_name}")
        self.queue.put((func, args, kwargs))

class AsyncTaskRunner:
    """Helper to run tasks in the background without blocking the Slicer UI thread."""
    
    @staticmethod
    def run(task_func, callback=None, *args, **kwargs):
        """
        Runs `task_func` in a background thread.
        Once completed, executes `callback` on the main UI thread with the result.
        """
        def thread_target():
            try:
                logger.info(f"AsyncTaskRunner starting execution of {task_func.__name__}")
                result = task_func(*args, **kwargs)
                logger.info(f"AsyncTaskRunner execution completed. Queuing callback.")
                if callback:
                    MainThreadDispatcher.get_instance().dispatch(callback, result)
            except Exception as e:
                logger.error(f"Error in background task: {e}")
                if callback:
                    MainThreadDispatcher.get_instance().dispatch(callback, None)
        
        logger.info(f"Spawning background thread for {task_func.__name__}...")
        thread = threading.Thread(target=thread_target)
        thread.daemon = True
        thread.start()
