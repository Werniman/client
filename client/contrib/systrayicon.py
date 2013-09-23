#!/usr/bin/env python
# Module     : SysTrayIcon.py
# Synopsis   : Windows System tray icon.
# Programmer : Simon Brunning - simon@brunningonline.net
# Date       : 11 April 2005
# Notes      : Based on (i.e. ripped off from) Mark Hammond's
#              win32gui_taskbar.py and win32gui_menu.py demos from PyWin32

         
import os
import time
import atexit
import locale
import win32api
import win32con
import win32gui_struct
try:
    import winxpgui as win32gui
except ImportError:
    import win32gui

from gevent.lock import Semaphore

from .. import event

os_encoding = locale.getpreferredencoding()

class SysTrayIcon(object):
    '''TODO'''
    QUIT = 'QUIT'
    SPECIAL_ACTIONS = [QUIT]
    
    FIRST_ID = 1023
    instance = None
    
    def __init__(self,
                 icon,
                 menu_options,
                 on_quit=None,
                 default_menu_index=None,
                 window_class_name=None,
                 lock=None,
                 init_callback=None,
                 update_tooltip_callback=None):
        SysTrayIcon.instance = self
        
        self.icon = icon
        self.icon_cache = dict()
        self.on_quit = on_quit

        self.notify_id = None
        self.tooltip_text = ""
        self.tooltip_lock = Semaphore()
        self.update_tooltip_callback = update_tooltip_callback
        self.last_tooltip_update = 0
        self.update_tooltip_text()

        self.hmenu = None
        self.lock = lock
        
        self.init_menu_options(menu_options)
        
        self.default_menu_index = (default_menu_index or 0)
        self.window_class_name = window_class_name or "SysTrayIconPy"

        try:
            message_map = {win32gui.RegisterWindowMessage("TaskbarCreated"): self.restart,
                           win32con.WM_DESTROY: self.destroy,
                           win32con.WM_COMMAND: self.command,
                           win32con.WM_USER+20: self.notify,
                           win32con.WM_USER+21: self._refresh_icon_event}
            # Register the Window class.
            window_class = win32gui.WNDCLASS()
            hinst = window_class.hInstance = win32gui.GetModuleHandle(None)
            window_class.lpszClassName = self.window_class_name
            window_class.style = win32con.CS_VREDRAW | win32con.CS_HREDRAW
            window_class.hCursor = win32gui.LoadCursor(0, win32con.IDC_ARROW)
            window_class.hbrBackground = win32con.COLOR_WINDOW
            window_class.lpfnWndProc = message_map # could also specify a wndproc.
            classAtom = win32gui.RegisterClass(window_class)
            # Create the Window.
            style = win32con.WS_OVERLAPPED | win32con.WS_SYSMENU
            self.hwnd = win32gui.CreateWindow(classAtom,
                                              self.window_class_name,
                                              style,
                                              0,
                                              0,
                                              win32con.CW_USEDEFAULT,
                                              win32con.CW_USEDEFAULT,
                                              0,
                                              0,
                                              hinst,
                                              None)
            win32gui.UpdateWindow(self.hwnd)
            self.refresh_icon_handler()
            atexit.register(self.destroy, None, None, None, None)
            self.threadid = win32api.GetCurrentThreadId()
        finally:
            if init_callback is not None:
                init_callback(self)
        win32gui.PumpMessages()

    def update_tooltip_text(self):
        with self.tooltip_lock:
            if self.update_tooltip_callback and (not self.last_tooltip_update or self.last_tooltip_update + 1 < time.time()):
                #r = AsyncResult()
                event.call_from_thread(self.update_tooltip_callback)
                #self.tooltip_text = r.get() or ""
                self.last_tooltip_update = time.time()

    def init_menu_options(self, menu_options):
        self.hide_menu()
        self._init_menu_options(menu_options)
        #if self.lock is not None:
        #    with self.lock:
        #        self._init_menu_options(menu_options)
        #else:
        #    self._init_menu_options(menu_options)

    def _init_menu_options(self, menu_options):
        self._next_action_id = self.FIRST_ID
        self.menu_actions_by_id = set()
        self.menu_options = self._add_ids_to_menu_options(list(menu_options))
        self.menu_actions_by_id = dict(self.menu_actions_by_id)
        del self._next_action_id
        
    def stop(self):
        win32gui.PostMessage(self.hwnd, win32con.WM_DESTROY, 0, 0)
        
    def refresh_icon(self):
        win32gui.PostMessage(self.hwnd, win32con.WM_USER+21, 0, 0)
        
    def _add_ids_to_menu_options(self, menu_options):
        result = []
        for menu_option in menu_options:
            option_text, option_icon, option_action = menu_option
            if callable(option_action) or option_action in self.SPECIAL_ACTIONS:
                self.menu_actions_by_id.add((self._next_action_id, option_action))
                result.append(menu_option + (self._next_action_id,))
            elif non_string_iterable(option_action):
                result.append((option_text,
                               option_icon,
                               self._add_ids_to_menu_options(option_action),
                               self._next_action_id))
            else:
                print 'Unknown item', option_text, option_icon, option_action
            self._next_action_id += 1
        return result
        
    def _refresh_icon_event(self,  hwnd, msg, wparam, lparam):
        self.refresh_icon_handler()
        
    def refresh_icon_handler(self):
        # Try and find a custom icon
        hinst = win32gui.GetModuleHandle(None)
        hicon = self.icon_cache.get(self.icon, None)
        if hicon is None:
            if os.path.isfile(self.icon):
                hicon = win32gui.LoadImage(hinst,
                                           self.icon,
                                           win32con.IMAGE_ICON,
                                           0,
                                           0,
                                           win32con.LR_LOADFROMFILE | win32con.LR_DEFAULTSIZE)
            else:
                print "Can't find icon file - using default."
                hicon = win32gui.LoadIcon(0, win32con.IDI_APPLICATION)
            self.icon_cache[self.icon] = hicon

        if self.notify_id:
            message = win32gui.NIM_MODIFY
        else:
            message = win32gui.NIM_ADD

        self.notify_id = (self.hwnd,
                          0,
                          win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP,
                          win32con.WM_USER+20,
                          hicon,
                          self.tooltip_text.encode(os_encoding))

        try:
            win32gui.Shell_NotifyIcon(message, self.notify_id)
        except:
            if message == win32gui.NIM_ADD:
                self.notify_id = None
            raise

    def restart(self, hwnd, msg, wparam, lparam):
        self.refresh_icon_handler()

    def destroy(self, hwnd, msg, wparam, lparam):
        if self.on_quit:
            self.on_quit(self)
        nid = (self.hwnd, 0)
        try:
            win32gui.Shell_NotifyIcon(win32gui.NIM_DELETE, nid)
        except:
            pass
        win32gui.PostQuitMessage(0) # Terminate the app.

    def notify(self, hwnd, msg, wparam, lparam):
        if lparam == win32con.WM_LBUTTONDBLCLK:
            self.execute_menu_option(self.default_menu_index + self.FIRST_ID)
        elif lparam == win32con.WM_RBUTTONUP:
            self.show_menu()
        elif lparam == 512: # MOUSE MOVE?!
            self.update_tooltip_text()
        return True
        
    def show_menu(self):
        self._show_menu()
        #if self.lock is not None:
        #    with self.lock:
        #        self._show_menu()
        #else:
        #    self._show_menu()

    def _show_menu(self):
        self.hmenu = win32gui.CreatePopupMenu()
        self.create_menu(self.hmenu, self.menu_options)
        #win32gui.SetMenuDefaultItem(self.hmenu, 1000, 0)
        
        pos = win32gui.GetCursorPos()
        # See http://msdn.microsoft.com/library/default.asp?url=/library/en-us/winui/menus_0hdi.asp
        win32gui.SetForegroundWindow(self.hwnd)
        win32gui.TrackPopupMenu(self.hmenu,
                                win32con.TPM_LEFTALIGN,
                                pos[0],
                                pos[1],
                                0,
                                self.hwnd,
                                None)
        win32gui.PostMessage(self.hwnd, win32con.WM_NULL, 0, 0)

    def hide_menu(self):
        self._hide_menu()
        #if self.lock is not None:
        #    with self.lock:
        #        self._hide_menu()
        #else:
        #    self._hide_menu()

    def _hide_menu(self):
        if self.hmenu is not None:
            try:
                win32gui.DestroyMenu(self.hmenu)
            except:
                pass
            self.hmenu = None
    
    def create_menu(self, menu, menu_options):
        for option_text, option_icon, option_action, option_id in menu_options[::-1]:
            if option_icon:
                option_icon = self.prep_menu_icon(option_icon)
            
            if option_id in self.menu_actions_by_id:
                item, extras = win32gui_struct.PackMENUITEMINFO(text=option_text.encode(os_encoding),
                                                                hbmpItem=option_icon,
                                                                wID=option_id)
                win32gui.InsertMenuItem(menu, 0, 1, item)
            else:
                submenu = win32gui.CreatePopupMenu()
                self.create_menu(submenu, option_action)
                item, extras = win32gui_struct.PackMENUITEMINFO(text=option_text.encode(os_encoding),
                                                                hbmpItem=option_icon,
                                                                hSubMenu=submenu)
                win32gui.InsertMenuItem(menu, 0, 1, item)

    def prep_menu_icon(self, icon):
        # First load the icon.
        ico_x = win32api.GetSystemMetrics(win32con.SM_CXSMICON)
        ico_y = win32api.GetSystemMetrics(win32con.SM_CYSMICON)
        color = win32gui.GetSysColor(win32con.COLOR_MENU)
        icon = icon(ico_x, ico_y, color)
        
        if not os.path.exists(icon):
            print "WARNING: error loading icon {}".format(icon)
            return

        if icon.endswith('.bmp'):
            return win32gui.LoadImage(0, icon, win32con.IMAGE_BITMAP, ico_x, ico_y, win32con.LR_LOADFROMFILE)
        else:
            raise NotImplementedError("Require BMP")

    def command(self, hwnd, msg, wparam, lparam):
        id = win32gui.LOWORD(wparam)
        self.execute_menu_option(id)
        
    def execute_menu_option(self, id):
        menu_action = self.menu_actions_by_id[id]
        if menu_action == self.QUIT:
            win32gui.DestroyWindow(self.hwnd)
        else:
            menu_action(self)
            
def non_string_iterable(obj):
    try:
        iter(obj)
    except TypeError:
        return False
    else:
        return not isinstance(obj, basestring)
