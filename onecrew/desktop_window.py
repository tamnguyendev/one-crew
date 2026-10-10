"""One short-lived, plain-text Windows result window per durable outbox entry."""
import os
from pathlib import Path
import sys

from .desktop_notifications import lock, read, write, snapshots
from .ledger import Ledger, utcnow


def show(root, key):
    if len(key)!=32 or any(c not in '0123456789abcdef' for c in key):
        raise ValueError('Invalid notification ID.')
    path = root/(key+'.json')
    with lock(root, 'ui.'+key):
        with lock(root):
            record = read(path)
            if not record or record['status']!='launching' or not read(root/'config.json', {}).get('enabled'):
                return
            config = read(root/'config.json')
            current = snapshots(Ledger(record['project'], Path(config['state_root'])), task=record['task'])
            if not any(item['id']==key for item in current):
                record.update(status='superseded')
                write(path, record)
                return
            record.update(status='claimed', pid=os.getpid(), claimed_at=utcnow())
            write(path, record)
        window = None
        mapped = False
        try:
            import tkinter as tk
            from tkinter.scrolledtext import ScrolledText
            report = root/(key+'.txt')
            content = report.read_text(encoding='utf-8')
            window = tk.Tk()
            window.title('OneCrew — '+record['phase']+' — '+record['task'])
            window.geometry('850x650')
            tk.Label(window, text='OneCrew: '+record['phase']+'  |  '+record['task'],
                     anchor='w', font=('Segoe UI', 11, 'bold')).pack(fill='x', padx=12, pady=10)
            text = ScrolledText(window, wrap='word', font=('Segoe UI', 10))
            text.pack(fill='both', expand=True, padx=12)
            text.insert('1.0', content)
            text.configure(state='disabled')
            tk.Label(window, text='Báo cáo: '+str(report), wraplength=810, anchor='w').pack(fill='x', padx=12, pady=8)
            buttons = tk.Frame(window)
            buttons.pack(fill='x', padx=12, pady=10)

            def close():
                try:
                    with lock(root):
                        latest = read(path)
                        latest.update(status='closed', closed_at=utcnow(), answers_recorded=False)
                        write(path, latest)
                finally:
                    window.destroy()

            def on_map(event):
                nonlocal mapped
                if event.widget is not window or mapped or not window.winfo_ismapped():
                    return
                with lock(root):
                    latest = read(path)
                    latest.update(status='shown', shown_at=utcnow(), receipt='tk-window-mapped',
                                  user_attention_verified=False, answers_recorded=False)
                    write(path, latest)
                mapped = True

            tk.Button(buttons, text='Mở báo cáo', command=lambda: os.startfile(str(report))).pack(side='left')
            tk.Button(buttons, text='Đóng (không trả lời task)', command=close).pack(side='right')
            window.protocol('WM_DELETE_WINDOW', close)
            window.bind('<Map>', on_map)
            window.attributes('-topmost', True)
            window.after(2000, lambda: window.attributes('-topmost', False))
            window.mainloop()
        except Exception as error:
            # If mapping might already have happened, never silently duplicate it.
            with lock(root):
                latest = read(path)
                latest.update(status='uncertain' if mapped else 'pending', error=str(error)[:500])
                write(path, latest)
            if window is not None:
                window.destroy()
            raise


if __name__=='__main__':
    show(Path(sys.argv[1]).resolve(), sys.argv[2])
