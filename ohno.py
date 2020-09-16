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
module_allow_list = {'qtpy.', 'PyQt5.'}
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
    # 'exec_',  # hmmm...
    'scale',  # hmm? why?

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
                self.bound_func.__name__,
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
        self.bound = {}

    def __call__(self, *args, **kwargs):
        return self.func(*args, **kwargs)

    def __get__(self, obj, cls=None):
        if obj is None:
            return self.func

        print('attr', self.attr,
              _method_names_by_class[obj.__class__.__name__],
              self.attr in _method_names_by_class[self.owner.__name__]
              )
        if self.attr in _method_names_by_class[self.owner.__name__]:
            return _WrappedMethod(obj, self.func)
        return _WrappedStaticMethod(obj, self.func)


def _seems_like_a_staticmethod_exception(ex):
    if not isinstance(ex, TypeError):
        return False

    markers = ['arguments did not match any overloaded call',
               'too many arguments',
               'argument 1 has unexpected type',
               ]
    text = str(ex).strip()
    return any(marker in text for marker in markers)


def _patch_function(owner, obj_attr, func):
    key = (owner, obj_attr)
    if key in _patch_cache:
        return

    info = dict(func=func, owner=owner, attr=obj_attr)
    try:
        wrapped = _WrappedDescriptor(**info)
        setattr(owner, obj_attr, wrapped)
    except Exception as ex:
        if not obj_attr.startswith('__'):
            print("failed to patch", owner, obj_attr, ex)
        _patch_cache[key] = None
    else:
        _patch_cache[key] = wrapped


def should_patch(owner, obj_attr, obj):
    if obj_attr in ban_list:
        return False

    module = inspect.getmodule(owner)

    if module is None or not any(module.__name__.startswith(allow)
                                 for allow in module_allow_list):
        return False

    if (owner, obj_attr) in _patch_cache:
        return False

    if isinstance(obj, qtpy.QtCore.Signal):
        return False

    if inspect.ismodule(obj):
        return False

    if inspect.isclass(obj):
        return hasattr(obj, 'staticMetaObject')

    return True


_method_names_by_class = {}


def patch(owner, obj_attr, obj):
    if not should_patch(owner, obj_attr, obj):
        return

    if inspect.isclass(obj):
        if obj.__name__ not in _method_names_by_class:
            methods = [obj.staticMetaObject.method(idx)
                       for idx in range(obj.staticMetaObject.methodCount())]
            method_names = {method.name().data().decode('ascii')
                            for method in methods}
            _method_names_by_class[obj.__name__] = method_names

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


def main():
    patch_modules()

    try:
        argv0, script, *args = sys.argv
    except ValueError:
        print(f'Usage: {sys.argv[0]} (script.py) (args)')
        sys.exit(1)

    del sys.argv[1]

    runpy.run_path(script, init_globals=None, run_name='__main__')


if __name__ == '__main__':
    main()
