"""The v1 plain-text desktop window and mapped/close receipts, with supplied views."""
import os
from pathlib import Path
from .desktop_core import lock, read, write
from .ledger import Ledger, utcnow
from .snapshots import durable_write

def show(root, key, *, snapshots, text_report):
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
            item = next((item for item in current if item['id']==key), None)
            if item is None:
                record.update(status='superseded')
                write(path, record)
                return
            if item.get('plan_notice'):
                durable_write(root/(key+'.txt'), text_report(item).encode('utf-8'))
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

            def open_report():
                if item.get('plan_notice'):
                    refreshed = snapshots(Ledger(record['project'], Path(config['state_root'])), task=record['task'])
                    latest = next((candidate for candidate in refreshed if candidate['id']==key), None)
                    content_now = (text_report(latest) if latest else
                                   'Thông báo này đã được thay thế. Mở plan present để xem trạng thái hiện tại.\n')
                    durable_write(report, content_now.encode('utf-8'))
                os.startfile(str(report))

            tk.Button(buttons, text='Mở báo cáo', command=open_report).pack(side='left')
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
