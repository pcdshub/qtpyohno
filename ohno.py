import inspect
import logging
import sys
import threading

import qtpy
import qtpy.QtCore  # noqa
import qtpy.QtGui  # noqa
import qtpy.QtWidgets  # noqa

MAIN_THREAD = threading.main_thread()
logger = logging.getLogger(__name__)


_patch_cache = {}
module_allow_list = {'qtpy.', 'PyQt5.'}
func_ban_list = {
    '__getattribute__',
    '__setattribute__',
    '__getattr__',
    '__setattr__',
    '__hash__',
    '__init__',
    '__repr__',
    '__str__',
    'emit',  # safe
    'singleShot',  # safe
    'singleShot',  # safe
    'exec_',  # hmmm...
}


def is_wrapped(func):
    return getattr(func, '_is_wrapped_', False)


def _patch_function(owner, obj_attr, func):
    key = (owner, obj_attr)
    if key in _patch_cache or is_wrapped(func):
        return

    def wrapper(_orig_info):
        func = _orig_info['func']

        def wrapped(*args, **kwargs):
            current_thread = threading.current_thread()
            if current_thread != MAIN_THREAD:
                caller = inspect.stack()[1]
                caller_code = ''.join(caller.code_context).strip()
                caller_location = (
                    f'{caller.filename}[{caller.function}:{caller.lineno}]'
                )
                logger.warning(
                    '%s in thread %r |%s| calling %s(%s%s)',
                    caller_location,
                    current_thread.name,
                    caller_code,
                    func.__name__,
                    ', '.join(repr(arg) for arg in args),
                    ', '.join(f'{k}={v!r}' for k, v in kwargs.items()),
                )
            return func(*args, **kwargs)

        wrapped._is_wrapped_ = True
        return wrapped

    info = dict(func=func, owner=owner, attr=obj_attr)
    try:
        wrapped = wrapper(info)
        setattr(owner, obj_attr, wrapped)
    except Exception as ex:
        if not obj_attr.startswith('__'):
            print("failed to patch", owner, obj_attr, ex)
        _patch_cache[key] = None
    else:
        _patch_cache[key] = wrapped


def should_patch(owner, obj_attr, obj):
    if obj_attr in func_ban_list:
        return False

    module = inspect.getmodule(owner)

    if module is None or not any(module.__name__.startswith(allow)
                                 for allow in module_allow_list):
        return False

    if (owner, obj_attr) in _patch_cache:
        return False

    if inspect.ismodule(obj):
        return False

    if inspect.isclass(obj):
        # TODO: only patch Q* classes
        return obj.__name__.startswith('Q')

    return True


def patch(owner, obj_attr, obj):
    if not should_patch(owner, obj_attr, obj):
        return

    if inspect.isclass(obj):
        for attr, child in inspect.getmembers(obj):
            patch(obj, attr, child)
    elif callable(obj) or inspect.ismethod(obj):
        _patch_function(owner, obj_attr, obj)


def patch_modules(modules=None):
    if modules is None:
        modules = [
            qtpy, qtpy.QtWidgets, qtpy.QtCore, qtpy.QtGui
        ]

    for module in modules:
        for attr, child in inspect.getmembers(module):
            patch(module, attr, child)

    assert qtpy.QtWidgets.QLabel.setText._is_wrapped_


def test():
    app = qtpy.QtWidgets.QApplication(sys.argv)

    label = qtpy.QtWidgets.QLabel('my label')
    label.setText('test')
    label.text()

    def oops():
        label.setText('foobar')
        print('text is', label.text())

    th = threading.Thread(target=oops)
    th.start()
    th.join()
    app.exec_()


if __name__ == '__main__':
    patch_modules()
    test()
