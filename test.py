import sys
import threading

import qtpy
import qtpy.QtWidgets


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
    test()
