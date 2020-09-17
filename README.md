qtpyohno
========

~A simple~ A tool to detect when Qt code is called from outside of the main
thread.

Try it
======

```bash
$ python ohno.py test.py
test.py[oops:16] in thread 'Thread-1' |label.setText('foobar')| calling setText('foobar')
test.py[oops:17] in thread 'Thread-1' |print('text is', label.text())| calling text()
text is foobar
```
