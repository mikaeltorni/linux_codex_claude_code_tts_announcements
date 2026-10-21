"""Shared arrow-key selector for installer choices."""

import os
import sys
import termios
import tty


def choose_option(label, current, options):
    """Choose an option while restoring the terminal on every exit.

    Parameters: label - prompt title; current - initially selected value; options - available values.
    Returns: selected value, or None when cancelled.
    """
    print(f'label={label}, current={current}, options={options}', file=sys.stderr)
    options = list(dict.fromkeys((*options, current)))
    index = options.index(current)
    descriptor = sys.stdin.fileno()
    previous = termios.tcgetattr(descriptor)
    result = None
    try:
        tty.setraw(descriptor)
        print(f'{label}: ↑/↓ to choose, Enter to confirm, q to cancel', flush=True)
        while True:
            print('\r\033[K' + '  '.join(('> ' if i == index else '') + value
                                        for i, value in enumerate(options)), end='', flush=True)
            key = os.read(descriptor, 1)
            if key in (b'\r', b'\n'):
                result = options[index]
                break
            if key in (b'q', b'\x03', b'\x04', b''):
                break
            if key == b'\x1b':
                sequence = os.read(descriptor, 2)
                if sequence in (b'[A', b'[D'):
                    index = (index - 1) % len(options)
                elif sequence in (b'[B', b'[C'):
                    index = (index + 1) % len(options)
    finally:
        termios.tcsetattr(descriptor, termios.TCSADRAIN, previous)
        print()
    print(result, file=sys.stderr)
    return result
