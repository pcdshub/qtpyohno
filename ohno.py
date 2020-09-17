import inspect
import logging
import runpy
import sys
import threading
import types

import qtpy
import qtpy.QtCore  # noqa
import qtpy.QtGui  # noqa
import qtpy.QtWidgets  # noqa

MAIN_THREAD = threading.main_thread()
logger = logging.getLogger(__name__)


_patch_cache = {}
ban_list = {
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
    # 'scale',  # hmm? why?

    # TODO: only include QtWidgets/QtGui?
    'QThread',
    'QMutexLocker',
}


class _WrappedBase:
    def __init__(self, owner, func):
        self.owner = owner
        self.func = func

    def __getattr__(self, attr):
        return getattr(self.func, attr)

    def __setattr__(self, attr, value):
        if attr in ('owner', 'func'):
            self.__dict__[attr] = value
            return

        setattr(self.unbound_func, attr, value)

    def _check_thread(self, args, kwargs):
        current_thread = threading.current_thread()
        if current_thread != MAIN_THREAD:
            caller = inspect.stack()[2]
            caller_code = ''.join(caller.code_context).strip()
            caller_location = (
                f'{caller.filename}[{caller.function}:{caller.lineno}]'
            )
            logger.warning(
                '%s in thread %r |%s| calling %s(%s%s)',
                caller_location,
                current_thread.name,
                caller_code,
                self.func.__name__,
                ', '.join(repr(arg) for arg in args),
                ', '.join(f'{k}={v!r}' for k, v in kwargs.items()),
            )


class _WrappedStaticMethod(_WrappedBase):
    def __init__(self, owner, func):
        self.owner = owner
        self.func = func

    def __call__(self, *args, **kwargs):
        self._check_thread(args, kwargs)
        return self.func(*args, **kwargs)


class _WrappedMethod(_WrappedBase):
    def __init__(self, owner, func):
        self.owner = owner
        self.func = types.MethodType(func, owner)

    def __call__(self, *args, **kwargs):
        self._check_thread(args, kwargs)
        return self.func(*args, **kwargs)


class _WrappedDescriptor:
    def __init__(self, owner, attr, func):
        self.owner = owner
        self.attr = attr
        self.func = func

    def __call__(self, *args, **kwargs):
        return self.func(*args, **kwargs)

    def __get__(self, obj, cls=None):
        if obj is None:
            # print('descriptor get', self.owner, self.attr, self.func)
            return self.func

        if self.attr in _method_names_by_class[self.owner]:
            return _WrappedMethod(obj, self.func)
        return _WrappedStaticMethod(obj, self.func)


def _add_class_to_cache(cls):
    methods = [
        cls.staticMetaObject.method(idx)
        for idx in range(cls.staticMetaObject.methodCount())
    ]
    method_names = {
        method.name().data().decode('ascii') for method in methods
    }
    _method_names_by_class[cls] = method_names
    return method_names


def _patch_function(owner, obj_attr, func):
    key = (owner, obj_attr)
    if key in _patch_cache:
        return

    info = dict(func=func, owner=owner, attr=obj_attr)
    try:
        wrapped = _WrappedDescriptor(**info)
        setattr(owner, obj_attr, wrapped)
    except Exception:
        _patch_cache[key] = None
        logger.exception('Failed to patch: %s %s', owner, obj_attr)
    else:
        _patch_cache[key] = wrapped


_not_methods = (qtpy.QtCore.Signal, )


def should_patch(owner, obj_attr, obj):
    if obj_attr in ban_list:
        return False

    if inspect.isclass(obj):
        return hasattr(obj, 'staticMetaObject')

    if owner in _method_names_by_class:
        if isinstance(obj, _not_methods):
            return False
        return True

    return True


_method_names_by_class = {}


def patch(owner, obj_attr, obj):
    if not should_patch(owner, obj_attr, obj):
        return

    if inspect.isclass(obj) and hasattr(obj, 'staticMetaObject'):
        if obj not in _method_names_by_class:
            _add_class_to_cache(obj)

        for attr in _method_names_by_class[obj]:
            child = getattr(obj, attr, None)
            if child is not None and should_patch(obj, attr, child):
                _patch_function(obj, attr, child)


def patch_modules(modules=None):
    if modules is None:
        modules = [
            qtpy, qtpy.QtWidgets, qtpy.QtCore, qtpy.QtGui
        ]

    for module in modules:
        for attr, child in inspect.getmembers(module):
            patch(module, attr, child)


def main():
    patch_modules()

    try:
        _, script, *args = sys.argv
    except ValueError:
        print(f'Usage: {sys.argv[0]} (script.py) (args)')
        sys.exit(1)

    del sys.argv[1]

    runpy.run_path(script, init_globals=None, run_name='__main__')


if __name__ == '__main__':
    main()
